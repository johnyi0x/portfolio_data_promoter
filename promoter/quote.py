"""Find a real post about a high bagrank pair, skip bots/rugs/shills, quote it."""

from __future__ import annotations

import logging
import math
import random
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from .config import Settings
from .state import Store

log = logging.getLogger("promoter")

SPAM = re.compile(
    r"""
    airdrop|giveaway|whitelist|presale|stealth\s*launch|pump\.fun|pumpfun|
    \bca[:\s]|contract\s*address|0x[a-fA-F0-9]{40}|t\.me/|discord\.gg|
    follow\s*(me|for)|like\s*(and|&)\s*(rt|retweet)|rt\s*if|
    \b1000x\b|\b100x\b|\b50x\b|free\s*mint|claim\s*(now|your)|
    send\s*(sol|eth|usdc)|signal\s*group|vip\s*group|entry\s*(now|zone)|
    dm\s*me|my\s*calls|tap\s*in\b|don't\s*miss|dont\s*miss|
    referral|ref\s*link|promo\s*code|use\s*code
    """,
    re.I | re.X,
)

BOT_NAME = re.compile(
    r"bot$|alert|signals?|calls?\b|pump|gems?|whale.?alert|copy.?trade|"
    r"entry.?alert|alpha.?group|calls.?group",
    re.I,
)

NOISY_TICKERS = {
    "BTC",
    "ETH",
    "SOL",
    "GOLD",
    "SILVER",
    "USD",
    "EUR",
    "OIL",
}


@dataclass
class PairHint:
    coin: str
    label: str
    dex: str
    side: str
    hold_pct: float
    rank: int
    ranker: str
    listed: int


@dataclass
class FoundTweet:
    tweet_id: str
    username: str
    author_id: str
    text: str
    score: float
    pair: PairHint


def search_query(pair: PairHint) -> str:
    tag = pair.label.strip().upper()
    cash = f"${tag}"
    # HIP-3 / generic names collide with unrelated markets.
    if pair.dex or tag in NOISY_TICKERS:
        return (
            f"({cash} OR {tag}) (hyperliquid OR hl OR hip-3 OR hip3 OR xyz) "
            f"lang:en -is:retweet -is:reply -is:nullcast "
            f"-airdrop -giveaway -presale -whitelist"
        )
    return (
        f"({cash} OR {tag}) (hyperliquid OR hl OR hype) "
        f"lang:en -is:retweet -is:reply -is:nullcast "
        f"-airdrop -giveaway -presale -whitelist"
    )


def quote_comment(pair: PairHint, include_source: bool, host: str) -> str:
    tick = "$" + pair.label.strip().lstrip("$").upper()
    pct = f"{pair.hold_pct * 100:.1f}%"
    if pair.ranker == "roi":
        board = f"top {pair.listed} on 7d ROI"
        src = f"{host}/?ranker=roi"
    elif pair.ranker == "both":
        board = f"top {pair.listed} PnL+ROI"
        src = f"{host}/?ranker=both"
    else:
        board = f"top {pair.listed} on 7d PnL"
        src = host
    lines = random.choice(
        [
            [
                f"Same tape on the board. {board} is {pct} {pair.side} {tick} right now.",
            ],
            [
                f"{tick} is #{pair.rank} on the {board} hold map ({pct} {pair.side}).",
            ],
            [
                f"{pct} of {board} sitting {pair.side} {tick}. Share of wallets, not one size.",
            ],
        ]
    )
    text = "\n".join(lines)
    if include_source:
        text = f"{text}\n{src}"
    return text.strip()[:280]


def _age_days(created: datetime | None, now: datetime) -> float:
    if created is None:
        return 0.0
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return (now - created).total_seconds() / 86400.0


def _age_min(created: datetime | None, now: datetime) -> float:
    if created is None:
        return 9999.0
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return (now - created).total_seconds() / 60.0


def reject_reason(
    *,
    text: str,
    username: str,
    name: str,
    description: str,
    followers: int,
    following: int,
    account_days: float,
    tweet_min: float,
    likes: int,
    replies: int,
    hashtags: int,
    urls: int,
    cashtags: int,
    self_user: str,
    seen_ids: set[str],
    seen_authors: set[str],
    tweet_id: str,
    author_id: str,
) -> str | None:
    handle = username.lower().lstrip("@")
    if handle == self_user or handle in {"bagrank", "bagindex"}:
        return "self"
    if tweet_id in seen_ids or author_id in seen_authors:
        return "already used"
    if account_days < 45:
        return "new account"
    if followers < 80:
        return "tiny account"
    if followers < 400 and following > max(1, followers) * 8:
        return "follow-spam ratio"
    if BOT_NAME.search(username) or BOT_NAME.search(name) or BOT_NAME.search(description or ""):
        return "signal/bot name"
    if SPAM.search(text) or SPAM.search(description or ""):
        return "promo/rug language"
    if hashtags > 3 or urls > 1 or cashtags > 2:
        return "shill entities"
    if len(text.strip()) < 28:
        return "too thin"
    # No traction on an older tweet from a small account = likely dead promo.
    if tweet_min > 90 and likes + replies == 0 and followers < 2500:
        return "no traction"
    if tweet_min > 36 * 60:
        return "stale"
    if tweet_min < 8:
        return "too fresh"
    return None


def _metrics(obj, *keys: str) -> int:
    raw = getattr(obj, "public_metrics", None) or {}
    if not isinstance(raw, dict):
        return 0
    for key in keys:
        if key in raw and raw[key] is not None:
            try:
                return int(raw[key])
            except (TypeError, ValueError):
                return 0
    return 0


def _entities_count(tweet, kind: str) -> int:
    ent = getattr(tweet, "entities", None) or {}
    if not isinstance(ent, dict):
        return 0
    return len(ent.get(kind) or [])


def pick_quote(
    cfg: Settings,
    store: Store,
    pairs: list[PairHint],
) -> tuple[FoundTweet, str] | None:
    if cfg.dry_run:
        if not pairs:
            return None
        pair = pairs[0]
        fake = FoundTweet(
            tweet_id="0",
            username="example",
            author_id="0",
            text="(dry-run) would search recent posts",
            score=0,
            pair=pair,
        )
        comment = quote_comment(pair, True, cfg.site_host)
        return fake, comment

    if not cfg.has_x():
        return None

    from .xpost import make_search_client, search_recent

    client = make_search_client(cfg)
    if not cfg.x_bearer:
        log.warning(
            "X_BEARER_TOKEN is unset. Recent search with the posting keys returned 401 before. "
            "Quotes need the Bearer Token from Keys & Tokens (app-only), not the OAuth 1.0 access token."
        )
    now = datetime.now(timezone.utc)
    seen_ids = store.quoted_ids()
    seen_authors = store.quoted_authors()
    best: FoundTweet | None = None

    for pair in pairs[:3]:
        query = search_query(pair)
        try:
            tweets, users = search_recent(client, query)
        except Exception as exc:
            log.warning("X search failed for %s: %s", pair.label, exc)
            msg = str(exc).lower()
            if "403" in msg or "401" in msg or "not available" in msg:
                store.pause_quotes(hours=24)
                if not cfg.x_bearer:
                    log.warning(
                        "X recent search 401/403. Posting works; search does not, on these keys. "
                        "Set X_BEARER_TOKEN to the Bearer Token on Keys & Tokens. "
                        "The X plan also has to include recent search. Quotes paused 24h."
                    )
                else:
                    log.warning(
                        "X recent search 401/403 even with the bearer token. "
                        "This app's plan does not include recent search, so quote-reposts cannot run. Paused 24h."
                    )
                return None
            continue
        log.info("Search %s hits=%s", pair.label, len(tweets))
        for tw in tweets:
            uid = str(getattr(tw, "author_id", "") or "")
            user = users.get(uid)
            if user is None:
                continue
            text = str(getattr(tw, "text", "") or "")
            username = str(getattr(user, "username", "") or "")
            reason = reject_reason(
                text=text,
                username=username,
                name=str(getattr(user, "name", "") or ""),
                description=str(getattr(user, "description", "") or ""),
                followers=_metrics(user, "followers_count"),
                following=_metrics(user, "following_count"),
                account_days=_age_days(getattr(user, "created_at", None), now),
                tweet_min=_age_min(getattr(tw, "created_at", None), now),
                likes=_metrics(tw, "like_count"),
                replies=_metrics(tw, "reply_count"),
                hashtags=_entities_count(tw, "hashtags"),
                urls=_entities_count(tw, "urls"),
                cashtags=_entities_count(tw, "cashtags"),
                self_user=cfg.x_user,
                seen_ids=seen_ids,
                seen_authors=seen_authors,
                tweet_id=str(tw.id),
                author_id=uid,
            )
            if reason:
                continue
            likes = _metrics(tw, "like_count")
            replies = _metrics(tw, "reply_count")
            quotes = _metrics(tw, "quote_count")
            fol = max(1, _metrics(user, "followers_count"))
            score = likes + 2 * replies + 0.4 * quotes + 2 * math.log10(fol + 1)
            if getattr(user, "verified", False):
                score += 2
            cand = FoundTweet(
                tweet_id=str(tw.id),
                username=username,
                author_id=uid,
                text=text,
                score=score,
                pair=pair,
            )
            if best is None or cand.score > best.score:
                best = cand
        if best is not None:
            break

    if best is None:
        return None
    comment = quote_comment(best.pair, True, cfg.site_host)
    return best, comment
