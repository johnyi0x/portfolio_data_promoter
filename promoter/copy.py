"""Templates own the facts. Claude only rearranges words, and only sometimes."""

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

SYSTEM = """Rewrite FACTS into one X post.
Keep every number exactly (percents, pp, hours, ranks, wallet counts, times).
1-3 short lines. Under 240 characters before the source line.
lowercase is fine. no hashtags, no emojis, no "what do you think".
no hype (massive, huge, incredible, alert, breaking, just in).
do not explain bagrank. do not invent coins or moves.
If SOURCE is yes, last line must be exactly the given SOURCE_LINE.
Sound like a person glancing at a board, not a newsletter."""


def _tick(label: str, *, lower: bool | None = None) -> str:
    name = label.strip()
    if lower is None:
        lower = random.random() < 0.55
    return f"${name.lower() if lower else name}"


def _dex(dex: str) -> str:
    return f" · {dex}" if dex else ""


def _crowd(story: Story) -> str:
    listed = story.listed
    if story.ranker == "both":
        return random.choice(
            [
                "hyperliquid pnl + roi crowd",
                "pnl + roi wallets",
                "the combined pnl+roi board",
            ]
        )
    metric = "pnl" if story.ranker == "pnl" else "roi"
    return random.choice(
        [
            f"hyperliquid's top {listed} traders (7d {metric})",
            f"the 7d {metric} crowd",
            f"top {listed} {metric} wallets",
            f"hyperliquid top {listed} ({story.facts.get('window', metric)})",
        ]
    )


def _maybe_source(story: Story, lines: list[str]) -> str:
    text = "\n".join(lines).strip()
    if story.include_source:
        if story.source_line not in text:
            text = f"{text}\n{story.source_line}"
    return text.strip()


def _load(story: Story) -> str:
    f = story.facts
    t = _tick(f["label"])
    crowd = _crowd(story)
    a = [
        [
            f"{crowd} started loading {t} at {f['start']}.",
            f"from {f['from_pct']}% → {f['to_pct']}% in {f['hours']} hours — +{f['pp']}pp, still climbing.",
        ],
        [
            f"{t} {f['side']} jumped {f['from_pct']}% → {f['to_pct']}% in {f['hours']}h on the 7d {story.ranker} board.",
            f"+{f['pp']}pp since {f['start']}.",
        ],
        [
            f"{t} hold {f['from_pct']}% → {f['to_pct']}% in {f['hours']} hours.",
            f"{crowd} been adding.",
        ],
        [
            f"{crowd} loading {t} since {f['start']}.",
            f"{f['from_pct']}% to {f['to_pct']}% (+{f['pp']}pp).",
        ],
    ]
    return _maybe_source(story, random.choice(a))


def _dump(story: Story) -> str:
    f = story.facts
    t = _tick(f["label"])
    crowd = _crowd(story)
    a = [
        [
            f"{crowd} started dumping {t} at {f['start']}.",
            f"from {f['from_pct']}% → {f['to_pct']}% in {f['hours']} hours — {f['pp']}pp off.",
        ],
        [
            f"{t} just got dumped by the 7d {story.ranker} crowd.",
            f"hold {f['from_pct']}% → {f['to_pct']}% in {f['hours']} hours.",
        ],
        [
            f"{t} hold faded {f['from_pct']}% → {f['to_pct']}% in {f['hours']}h.",
            f"{crowd} stepping out.",
        ],
    ]
    return _maybe_source(story, random.choice(a))


def _inflow(story: Story) -> str:
    f = story.facts
    t = _tick(f["label"])
    a = [
        [
            f"biggest inflow this hour: {t} {f['side']} +{f['pp']}pp (now {f['hold_pct']}%).",
        ],
        [
            f"{t} {f['side']} +{f['pp']}pp this hour on bagrank.",
            f"hold now {f['hold_pct']}%.",
        ],
        [
            f"{_crowd(story)} added {t} this hour — +{f['pp']}pp, {f['hold_pct']}% {f['side']}.",
        ],
    ]
    return _maybe_source(story, random.choice(a))


def _outflow(story: Story) -> str:
    f = story.facts
    t = _tick(f["label"])
    a = [
        [
            f"biggest outflow this hour: {t} {f['side']} −{f['pp']}pp (now {f['hold_pct']}%).",
        ],
        [
            f"{t} −{f['pp']}pp this hour. {_crowd(story)} cutting it.",
        ],
        [
            f"{t} {f['side']} hold {f['hold_pct']}% after −{f['pp']}pp vs last hour.",
        ],
    ]
    return _maybe_source(story, random.choice(a))


def _dominate(story: Story) -> str:
    f = story.facts
    t = _tick(f["label"])
    a = [
        [
            f"{t} {f['side']} is dominating with {f['hold_pct']}% on bagrank.",
            f"{f['wallets']} of {_crowd(story)} in it ({f['agree']}% agree).",
        ],
        [
            f"{t} {f['side']} {f['hold_pct']}% — #1 on the {story.facts.get('window', '7d')} map.",
        ],
        [
            f"{_crowd(story)}: {t} {f['side']} still the biggest tile at {f['hold_pct']}%.",
        ],
    ]
    return _maybe_source(story, random.choice(a))


def _flip(story: Story) -> str:
    f = story.facts
    t = _tick(f["label"])
    a = [
        [
            f"{t} flipped {f['from_side']} → {f['to_side']} at {f['when']}.",
            f"hold {f['hold_pct']}% on the {story.ranker} board.",
        ],
        [
            f"{_crowd(story)} flipped {t} to {f['to_side']} ({f['hold_pct']}%).",
        ],
    ]
    return _maybe_source(story, random.choice(a))


def _digest(story: Story) -> str:
    f = story.facts
    t = _tick(f["top_label"])
    extra = []
    if f.get("in_label") and f.get("in_pp") is not None:
        extra.append(f"{_tick(f['in_label'])} in {f['in_pp']}pp")
    if f.get("out_label") and f.get("out_pp") is not None:
        extra.append(f"{_tick(f['out_label'])} out {f['out_pp']}pp")
    move = ", ".join(extra) if extra else "quiet tape vs last hour"
    a = [
        [
            f"{t} still #1 at {f['top_pct']}% {f['top_side']}.",
            f"{move}.",
        ],
        [
            f"{_crowd(story)} this hour: {t} {f['top_pct']}% {f['top_side']}.",
            f"{move}.",
        ],
    ]
    return _maybe_source(story, random.choice(a))


def _ranks(story: Story) -> str:
    f = story.facts
    metric = {
        "pnl": "7d pnl",
        "roi": "7d roi",
        "both": "pnl+roi",
    }[story.ranker]
    hour = f.get("hour") or "this hour"
    lines = [f"{metric} · top 5 · {hour}"]
    for row in f.get("rows") or []:
        dex = f" · {row['dex']}" if row.get("dex") else ""
        lines.append(
            f"{row['rank']} {_tick(row['label'], lower=False)} {row['side']} {row['hold_pct']}%{dex}"
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
    fn = TEMPLATES[story.kind]
    return _fit(fn(story))


def _fit(text: str, limit: int = 280) -> str:
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) <= limit:
        return text
    source = ""
    body = text
    if "\nsource:" in text.lower():
        idx = text.lower().rfind("\nsource:")
        body, source = text[:idx], text[idx + 1 :]
    while body and len(body) + (1 + len(source) if source else 0) > limit:
        if "\n" in body:
            body = body.rsplit("\n", 1)[0]
        else:
            keep = limit - (1 + len(source) if source else 0)
            body = body[: max(0, keep)].rstrip()
            break
    return (f"{body}\n{source}" if source else body).strip()[:limit]


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
        f"VOICE: {'analytical list' if story.kind == 'ranks' else 'punchy'}\n"
        f"SOURCE: {'yes' if story.include_source else 'no'}\n"
        f"SOURCE_LINE: {story.source_line}"
    )
    try:
        client = Anthropic(api_key=cfg.anthropic_key, timeout=20.0)
        resp = client.messages.create(
            model=cfg.claude_model,
            max_tokens=120,
            temperature=0.75,
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
    if not text or not _numbers_ok(story, text):
        log.info("Claude output dropped (numbers missing or empty)")
        return None
    if story.include_source and story.source_line not in text:
        text = _fit(f"{text}\n{story.source_line}")
    return text


def compose(cfg: Settings, story: Story, store: Store, now) -> tuple[str, bool]:
    base = template_text(story)
    # Analytical ranks stay as a list — more useful than prose, and free.
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
