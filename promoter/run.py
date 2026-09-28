"""Always-on loop: 2 board posts, then 1 filtered quote of a related live tweet."""

from __future__ import annotations

import argparse
import logging
import random
import sys
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from .charts import render_story
from .config import Settings, load_settings
from .copy import compose
from .facts import pick_ranker, pick_story
from .neon import load_board
from .quote import PairHint, pick_quote
from .state import Store
from .xpost import post_tweet, quote_tweet

log = logging.getLogger("promoter")


def setup_logging() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
        stream=sys.stdout,
    )
    logging.Formatter.converter = time.gmtime


def next_interval_s(cfg: Settings, *, after_quote: bool = False) -> float:
    lo = cfg.min_interval_min * 60.0
    hi = cfg.max_interval_min * 60.0
    base = random.triangular(lo, hi, (lo + hi) / 2)
    extra = random.uniform(0, 17 * 60)
    landed = (time.time() + base + extra) % 3600
    if landed < 180 or landed > 3420:
        extra += random.uniform(6 * 60, 19 * 60)
    s = max(lo, base + extra)
    if after_quote:
        s *= random.uniform(1.12, 1.38)
    return s


def seconds_until_utc_midnight(now: datetime) -> float:
    nxt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(60.0, (nxt - now).total_seconds() + random.uniform(12 * 60, 55 * 60))


def alt_text(story) -> str:
    f = story.facts
    label = f.get("label") or f.get("top_label") or "bagrank"
    board = {"pnl": "7d PnL", "roi": "7d ROI", "both": "PnL+ROI"}.get(story.ranker, "7d PnL")
    return f"bagrank.xyz {board} chart — {story.kind} for {label}, top {story.listed} wallets"


def pairs_payload(board) -> list[dict]:
    return [
        {
            "coin": p.coin,
            "label": p.label,
            "dex": p.dex,
            "side": p.side,
            "hold_pct": p.hold_pct,
            "rank": p.rank,
            "ranker": board.ranker,
            "listed": board.listed,
        }
        for p in board.rows[:8]
    ]


def hints_from_store(store: Store) -> list[PairHint]:
    out: list[PairHint] = []
    for row in store.last_pairs():
        try:
            out.append(
                PairHint(
                    coin=str(row["coin"]),
                    label=str(row["label"]),
                    dex=str(row.get("dex") or ""),
                    side=str(row.get("side") or "long"),
                    hold_pct=float(row["hold_pct"]),
                    rank=int(row.get("rank") or 1),
                    ranker=str(row.get("ranker") or "pnl"),
                    listed=int(row.get("listed") or 200),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out


def run_quote(cfg: Settings, store: Store, now: datetime) -> bool:
    hints = hints_from_store(store)
    if not hints:
        board = load_board(cfg.pnl_url, cfg.roi_url, "pnl", cfg.venue)
        if board.rows:
            store.set_last_pairs(pairs_payload(board), persist=True)
            hints = hints_from_store(store)
    if not hints:
        log.warning("Quote skipped — no bagrank pairs cached")
        store.mark_quote_fail()
        return False

    picked = pick_quote(cfg, store, hints)
    if picked is None:
        log.info("No clean tweet to quote")
        store.mark_quote_fail()
        return False
    found, comment = picked
    log.info(
        "Quote @%s id=%s pair=%s score=%.1f\n%s",
        found.username,
        found.tweet_id,
        found.pair.label,
        found.score,
        comment,
    )

    if cfg.dry_run:
        out_dir = cfg.data_dir / "out"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        (out_dir / f"{stamp}_quote.txt").write_text(
            f"quote {found.tweet_id} @{found.username}\n{comment}\n",
            encoding="utf-8",
        )
        store.mark_post(
            now=now,
            key=f"quote:{found.pair.coin}:{now.strftime('%Y%m%d%H')}",
            ranker=found.pair.ranker,
            kind="quote",
            text=comment,
            used_claude=False,
            tweet_id=None,
            interval_s=0,
            quote_tweet_id=found.tweet_id,
            quote_author_id=found.author_id,
        )
        return True

    tweet_id = quote_tweet(cfg, comment, found.tweet_id)
    store.mark_post(
        now=now,
        key=f"quote:{found.pair.coin}:{now.strftime('%Y%m%d%H')}",
        ranker=found.pair.ranker,
        kind="quote",
        text=comment,
        used_claude=False,
        tweet_id=tweet_id,
        interval_s=0,
        quote_tweet_id=found.tweet_id,
        quote_author_id=found.author_id,
    )
    log.info("Quoted tweet_id=%s -> %s", found.tweet_id, tweet_id)
    return True


def run_promo(cfg: Settings, store: Store, now: datetime) -> bool:
    ranker = pick_ranker(cfg.has_roi(), store.last_ranker())
    include_source = True
    log.info("Board post ranker=%s source=%s", ranker, include_source)
    board = load_board(cfg.pnl_url, cfg.roi_url, ranker, cfg.venue)
    if board.error and not board.rows:
        log.error("No board: %s", board.error)
        return False
    store.set_last_pairs(pairs_payload(board))

    story = pick_story(board, cfg.site_host, include_source, store.recent_keys())
    if story is None:
        log.warning("No story to post")
        return False

    text, used_claude = compose(cfg, story, store, now)
    log.info("Story %s key=%s claude=%s\n%s", story.kind, story.key, used_claude, text)
    png = render_story(board, story)

    if cfg.dry_run:
        out_dir = cfg.data_dir / "out"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        (out_dir / f"{stamp}_{story.kind}.png").write_bytes(png)
        (out_dir / f"{stamp}_{story.kind}.txt").write_text(text + "\n", encoding="utf-8")
        log.info("DRY_RUN wrote %s bytes png", len(png))
        store.mark_post(
            now=now,
            key=story.key,
            ranker=story.ranker,
            kind=story.kind,
            text=text,
            used_claude=used_claude,
            tweet_id=None,
            interval_s=0,
        )
        return True

    if not cfg.has_x():
        raise RuntimeError("X API keys missing (set DRY_RUN=1 to skip posting)")

    tweet_id = post_tweet(cfg, text, png, alt_text(story))
    store.mark_post(
        now=now,
        key=story.key,
        ranker=story.ranker,
        kind=story.kind,
        text=text,
        used_claude=used_claude,
        tweet_id=tweet_id,
        interval_s=0,
    )
    log.info("Posted tweet_id=%s", tweet_id)
    return True


def run_once(cfg: Settings, store: Store, *, force: bool = False) -> str:
    """Return 'promo' | 'quote' | 'skip'."""
    now = datetime.now(timezone.utc)
    if not force and store.posts_today(now) >= cfg.max_posts_per_day:
        log.info("Daily cap %s reached — skip", cfg.max_posts_per_day)
        return "skip"

    if not force and store.posts_today(now) > 0 and random.random() < cfg.skip_rate:
        log.info("Leaving this slot empty so the account is not a metronome")
        return "skip"

    if store.want_quote(cfg.promo_before_quote):
        if run_quote(cfg, store, now):
            return "quote"
        if store.want_quote(cfg.promo_before_quote):
            return "skip"
        log.info("Quote gave up — board post this slot")

    if run_promo(cfg, store, now):
        return "promo"
    return "skip"


def run_forever(cfg: Settings) -> None:
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    store = Store(cfg.data_dir, neon_dsn=cfg.pnl_url)
    log.info(
        "Promoter start dry=%s claude=%s x=%s roi=%s interval=%.0f-%.0fmin cap=%s/day quote_every=%s",
        cfg.dry_run,
        cfg.has_claude(),
        cfg.has_x(),
        cfg.has_roi(),
        cfg.min_interval_min,
        cfg.max_interval_min,
        cfg.max_posts_per_day,
        cfg.promo_before_quote,
    )

    last = store.last_post_at()
    if last > 0:
        remain = next_interval_s(cfg) - (time.time() - last)
        if remain > 45:
            log.info("Last post %.0fmin ago — sleep %.0fs first", (time.time() - last) / 60, remain)
            time.sleep(remain)
    else:
        warmup = random.uniform(90, 8 * 60)
        log.info("First run — warmup sleep %.0fs", warmup)
        time.sleep(warmup)

    while True:
        after_quote = False
        try:
            now = datetime.now(timezone.utc)
            if store.posts_today(now) >= cfg.max_posts_per_day:
                sleep_s = seconds_until_utc_midnight(now)
                log.info("Day cap hit — sleep until after UTC midnight (%.0fs)", sleep_s)
                time.sleep(sleep_s)
                continue
            kind = run_once(cfg, store)
            after_quote = kind == "quote"
        except KeyboardInterrupt:
            log.info("Stopped")
            return
        except Exception as exc:
            msg = str(exc).lower()
            if "429" in msg or "rate limit" in msg:
                sleep_s = random.uniform(50 * 60, 95 * 60)
                log.exception("X rate limit — sleep %.0fmin", sleep_s / 60)
                time.sleep(sleep_s)
                continue
            log.exception("Cycle error — retry in 90s")
            time.sleep(90.0)
            continue
        sleep_s = next_interval_s(cfg, after_quote=after_quote)
        log.info("Next slot in %.0fmin", sleep_s / 60.0)
        time.sleep(sleep_s)


def main(argv: list[str] | None = None) -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="bagrank X promoter")
    parser.add_argument("--once", action="store_true", help="one cycle then exit")
    parser.add_argument("--dry-run", action="store_true", help="write PNG+text, do not post")
    args = parser.parse_args(argv)
    cfg = load_settings()
    if args.dry_run:
        cfg = replace(cfg, dry_run=True)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    store = Store(cfg.data_dir, neon_dsn=cfg.pnl_url)
    if args.once:
        run_once(cfg, store, force=True)
        return
    run_forever(cfg)
