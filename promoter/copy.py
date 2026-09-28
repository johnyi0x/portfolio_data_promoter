"""Facts stay in templates. Claude only rearranges words, and only sometimes."""

from __future__ import annotations

import json
import logging
import random
import re
from typing import Any

from .config import Settings
from .models import Story
from .state import Store

log = logging.getLogger("promoter")

SYSTEM = """You write the caption under a chart screenshot on X.
Goal: a Hyperliquid trader reads it, understands the chart, and taps bagrank.xyz.

Structure, in order:
1. Hook — sentence case, leading cashtag ($SUI). What changed, in plain English. Not a metric dump.
2. Meaning — one short line of what the number is (share of top-N wallets ranked on 7d PnL or ROI; one wallet, one vote). Do not repeat this if the hook already said it.
3. Site line — if SOURCE is yes, last line must be exactly SOURCE_LINE. Never write "source:".

Rules:
- 2-4 lines. Under 220 characters before the site line.
- Last line is always the site URL when SOURCE is yes. That line is the only clickable path to the board — do not skip it, do not prefix "source:".
- Keep every number exactly (percents, pp, hours, ranks, wallet counts, times).
- Cashtags: $TICKER in uppercase.
- Sentence case. Never all-lowercase. Never all-caps except tickers and PnL/ROI.
- No hashtags, no emojis, no "what do you think", no "thread", no "GM".
- No hype: massive, huge, incredible, alert, breaking, just in, don't fade, ape, moon.
- No bot tells: "been adding", "this tracks", "yeah —", "the 7d pnl crowd", "source:", "live board:".
- Do not invent coins, moves, prices, or reasons (funding, news, liquidations) that are not in FACTS.
- Do not pitch the product. The chart plus bagrank.xyz is the pitch.
Voice: a trader showing a screenshot of something they noticed, not a promo account."""


def _tick(label: str) -> str:
    return "$" + str(label).strip().lstrip("$").upper()


def _crowd(story: Story) -> str:
    listed = story.listed
    if story.ranker == "both":
        return random.choice(
            [
                f"Hyperliquid's top {listed} (PnL + ROI)",
                f"the combined PnL+ROI top {listed}",
            ]
        )
    metric = "PnL" if story.ranker == "pnl" else "ROI"
    window = story.facts.get("window") or "7d"
    return random.choice(
        [
            f"Hyperliquid's top {listed} ({window} {metric})",
            f"the top {listed} wallets on {window} {metric}",
            f"top {listed} {metric} wallets",
        ]
    )


def _metric(story: Story) -> str:
    if story.ranker == "both":
        return "PnL+ROI"
    metric = "PnL" if story.ranker == "pnl" else "ROI"
    window = story.facts.get("window") or "7d"
    return f"{window} {metric}"


def _maybe_source(story: Story, lines: list[str]) -> str:
    text = "\n".join(line for line in lines if line).strip()
    if story.include_source and story.source_line not in text:
        text = f"{text}\n{story.source_line}"
    return text.strip()


def _load(story: Story) -> str:
    f = story.facts
    t = _tick(f["label"])
    crowd = _crowd(story)
    from_pct = float(f["from_pct"])
    to_pct = float(f["to_pct"])
    ratio = (to_pct / from_pct) if from_pct > 0 else 1.0
    if ratio >= 2.9:
        hook = [
            f"{t} just tripled on the board — {f['from_pct']}% → {f['to_pct']}% in {f['hours']} hours.",
            f"That's the share of {crowd} sitting in it. One wallet, one vote.",
        ]
    elif ratio >= 1.9:
        hook = [
            f"{t} more than doubled among {crowd}.",
            f"Hold {f['from_pct']}% → {f['to_pct']}% in {f['hours']} hours.",
        ]
    else:
        hook = [
            f"{t} hold among {crowd} went {f['from_pct']}% → {f['to_pct']}% in {f['hours']} hours.",
            "Not one whale — share of wallets in the name.",
        ]
    a = [hook]
    a.append(
        [
            f"{crowd} started loading {t} at {f['start']}.",
            f"{f['from_pct']}% → {f['to_pct']}% (+{f['pp']}pp) in {f['hours']} hours.",
        ]
    )
    if ratio < 1.9:
        a.append(
            [
                f"{t} is getting crowded. {f['from_pct']}% of {crowd} → {f['to_pct']}% in {f['hours']}h.",
            ]
        )
    return _maybe_source(story, random.choice(a))


def _dump(story: Story) -> str:
    f = story.facts
    t = _tick(f["label"])
    crowd = _crowd(story)
    a = [
        [
            f"{t} is coming off the board.",
            f"{crowd} cut hold {f['from_pct']}% → {f['to_pct']}% in {f['hours']} hours.",
        ],
        [
            f"{crowd} started dumping {t} at {f['start']}.",
            f"{f['from_pct']}% → {f['to_pct']}% ({f['pp']}pp off).",
        ],
        [
            f"{t} faded {f['from_pct']}% → {f['to_pct']}% in {f['hours']}h among {crowd}.",
        ],
    ]
    return _maybe_source(story, random.choice(a))


def _inflow(story: Story) -> str:
    f = story.facts
    t = _tick(f["label"])
    a = [
        [
            f"Biggest add this hour: {t} {f['side']}s, +{f['pp']}pp.",
            f"Now {f['hold_pct']}% of {_crowd(story)}.",
        ],
        [
            f"{t} {f['side']} +{f['pp']}pp vs the last hour.",
            f"{_crowd(story)} now {f['hold_pct']}% in it.",
        ],
    ]
    return _maybe_source(story, random.choice(a))


def _outflow(story: Story) -> str:
    f = story.facts
    t = _tick(f["label"])
    a = [
        [
            f"Biggest cut this hour: {t} {f['side']}s, −{f['pp']}pp.",
            f"Still {f['hold_pct']}% of {_crowd(story)}.",
        ],
        [
            f"{t} −{f['pp']}pp this hour. {_crowd(story)} stepping out.",
            f"Hold now {f['hold_pct']}%.",
        ],
    ]
    return _maybe_source(story, random.choice(a))


def _dominate(story: Story) -> str:
    f = story.facts
    t = _tick(f["label"])
    a = [
        [
            f"{t} {f['side']} still owns the map at {f['hold_pct']}%.",
            f"{f['wallets']} of {_crowd(story)} in it ({f['agree']}% same side).",
        ],
        [
            f"{t} is #1 on the {_metric(story)} hold map — {f['hold_pct']}% {f['side']}.",
            f"{f['wallets']} wallets, {f['agree']}% agreement.",
        ],
    ]
    return _maybe_source(story, random.choice(a))


def _flip(story: Story) -> str:
    f = story.facts
    t = _tick(f["label"])
    a = [
        [
            f"{t} flipped {f['from_side']} → {f['to_side']} at {f['when']}.",
            f"Hold {f['hold_pct']}% on the {_metric(story)} board.",
        ],
        [
            f"{_crowd(story)} just flipped {t} to {f['to_side']} ({f['hold_pct']}%).",
        ],
    ]
    return _maybe_source(story, random.choice(a))


def _digest(story: Story) -> str:
    f = story.facts
    t = _tick(f["top_label"])
    extra = []
    if f.get("in_label") and f.get("in_pp") is not None:
        extra.append(f"{_tick(f['in_label'])} +{f['in_pp']}pp")
    if f.get("out_label") and f.get("out_pp") is not None:
        extra.append(f"{_tick(f['out_label'])} −{f['out_pp']}pp")
    move = " · ".join(extra) if extra else "quiet vs last hour"
    a = [
        [
            f"{t} still #1 at {f['top_pct']}% {f['top_side']}.",
            f"This hour: {move}.",
        ],
        [
            f"{_crowd(story)} this hour — {t} {f['top_pct']}% {f['top_side']}.",
            move + ".",
        ],
    ]
    return _maybe_source(story, random.choice(a))


def _ranks(story: Story) -> str:
    f = story.facts
    hour = f.get("hour") or "this hour"
    lines = [f"{_metric(story)} · top 5 · {hour}"]
    for row in f.get("rows") or []:
        dex = f" · {row['dex']}" if row.get("dex") else ""
        lines.append(
            f"{row['rank']}  {_tick(row['label'])} {row['side']}  {row['hold_pct']}%{dex}"
        )
    return _maybe_source(story, lines)


TEMPLATES = {
    "load": _load,
    "dump": _dump,
    "inflow": _inflow,
    "outflow": _outflow,
    "dominate": _dominate,
    "flip": _flip,
    "digest": _digest,
    "ranks": _ranks,
}


def template_text(story: Story) -> str:
    return _fit(TEMPLATES[story.kind](story))


def _split_cta(text: str) -> tuple[str, str]:
    lines = [ln.rstrip() for ln in text.strip().split("\n")]
    if lines and "bagrank.xyz" in lines[-1].lower():
        return "\n".join(lines[:-1]).strip(), lines[-1].strip()
    return text.strip(), ""


def _fit(text: str, limit: int = 280) -> str:
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) <= limit:
        return text
    body, cta = _split_cta(text)
    reserve = (1 + len(cta)) if cta else 0
    while body and len(body) + reserve > limit:
        if "\n" in body:
            body = body.rsplit("\n", 1)[0]
        else:
            body = body[: max(0, limit - reserve)].rstrip()
            break
    return (f"{body}\n{cta}" if cta else body).strip()[:limit]


def _numbers_ok(story: Story, text: str) -> bool:
    f = story.facts
    needed: list[str] = []
    if story.kind in {"load", "dump"}:
        needed = [f"{f['from_pct']}", f"{f['to_pct']}", str(f["hours"])]
    elif story.kind in {"inflow", "outflow"}:
        needed = [f"{f['pp']}", f"{f['hold_pct']}"]
    elif story.kind == "dominate":
        needed = [f"{f['hold_pct']}"]
    elif story.kind == "ranks":
        needed = [str(r["hold_pct"]) for r in (f.get("rows") or [])[:3]]
    elif story.kind == "digest":
        needed = [f"{f['top_pct']}"]
    elif story.kind == "flip":
        needed = [f"{f['hold_pct']}"]
    return all(n in text for n in needed)


def _too_close(text: str, recent: list[str]) -> bool:
    compact = re.sub(r"\s+", " ", text.lower())
    for prev in recent:
        p = re.sub(r"\s+", " ", prev.lower())
        if compact == p:
            return True
        if len(compact) > 40 and compact[:40] == p[:40]:
            return True
    return False


def _looks_bot(text: str) -> bool:
    low = text.lower()
    if low == text and len(text) > 40:
        return True
    if "source:" in low:
        return True
    if "been adding" in low or "this tracks" in low or low.startswith("yeah"):
        return True
    return False


def _claude(cfg: Settings, story: Story) -> str | None:
    try:
        from anthropic import Anthropic
    except ImportError:
        log.warning("anthropic package missing — templates only")
        return None
    payload: dict[str, Any] = {
        "kind": story.kind,
        "ranker": story.ranker,
        "listed": story.listed,
        "facts": story.facts,
        "include_source": story.include_source,
        "source_line": story.source_line,
    }
    user = (
        f"FACTS:\n{json.dumps(payload, separators=(',', ':'))}\n"
        f"VOICE: {'compact ranked list, keep the numbers aligned' if story.kind == 'ranks' else 'trader screenshot caption'}\n"
        f"SOURCE: {'yes' if story.include_source else 'no'}\n"
        f"SOURCE_LINE: {story.source_line}"
    )
    try:
        # anthropic 1.x removed temperature= from messages.create(); passing it
        # raises TypeError locally and never hits the API. Haiku 4.5 is fine
        # without it — templates already pick the voice.
        client = Anthropic(api_key=cfg.anthropic_key, timeout=20.0)
        resp = client.messages.create(
            model=cfg.claude_model,
            max_tokens=180,
            system=SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
    except Exception:
        log.exception("Claude call failed — using template")
        return None
    parts = []
    for block in resp.content:
        if getattr(block, "type", "") == "text":
            parts.append(block.text)
    text = _fit("\n".join(parts).strip())
    usage = getattr(resp, "usage", None)
    if usage:
        log.info(
            "Claude tokens in=%s out=%s",
            getattr(usage, "input_tokens", "?"),
            getattr(usage, "output_tokens", "?"),
        )
    if not text or not _numbers_ok(story, text) or _looks_bot(text):
        log.info("Claude output dropped (numbers, empty, or bot-like)")
        return None
    if story.include_source and story.source_line not in text:
        text = _fit(f"{text}\n{story.source_line}")
    return text


def compose(cfg: Settings, story: Story, store: Store, now) -> tuple[str, bool]:
    base = template_text(story)
    if story.kind == "ranks" or not cfg.has_claude():
        return base, False
    if store.claude_today(now) >= cfg.claude_max_per_day:
        return base, False
    if random.random() > cfg.claude_rate:
        return base, False
    rewritten = _claude(cfg, story)
    if not rewritten or _too_close(rewritten, store.recent_texts()):
        return base, False
    store.mark_claude(now)
    return rewritten, True
