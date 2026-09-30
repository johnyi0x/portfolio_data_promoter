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

SYSTEM = """You write the caption under a chart that is ALREADY on the tweet.
The chart title already shows the ticker and the percent move. Do not open by repeating that title.

What makes someone tap bagrank.xyz: the chart is one name. The site is the rest of the board.
Use ALSO when present — another coin on the same board the image does not plot.

Vary the shape. Pick one, and do not reuse a shape you would have used last time:
- One short line plus the site URL. Chart does the talking.
- Lead with the OTHER coin, then one clause on the focus name.
- Say what the number means (share of wallets, one vote) without "moved from X% to Y%" as the first sentence.
- A ranked observation, not a press release.

Rules:
- 1-3 lines. Last line is exactly SOURCE_LINE when SOURCE is yes. Never write "source:".
- Keep the end percent and the hours exactly. You may omit the start percent — the chart has it.
- Cashtags uppercase. Sentence case. No hashtags, emojis, questions, or hype.
- Banned openers and phrases: "is coming off the board", "started loading", "started dumping", "moved from", "been adding", "not one whale", "the 7d pnl crowd".
- Do not invent coins, prices, or reasons that are not in FACTS.
Voice: someone who already looked at the board and is pointing at the part the screenshot left out."""


def _tick(label: str) -> str:
    return "$" + str(label).strip().lstrip("$").upper()


def _crowd(story: Story) -> str:
    listed = story.listed
    if story.ranker == "both":
        return random.choice(
            [
                f"the top {listed} on PnL + ROI",
                f"PnL + ROI, top {listed}",
            ]
        )
    window = str(story.facts.get("window") or ("7d PnL" if story.ranker == "pnl" else "7d ROI"))
    return random.choice(
        [
            f"the top {listed} ({window})",
            f"top {listed}, {window}",
        ]
    )


def _metric(story: Story) -> str:
    if story.ranker == "both":
        return "PnL + ROI"
    return str(story.facts.get("window") or ("7d PnL" if story.ranker == "pnl" else "7d ROI"))


def _side_word(side: str) -> str:
    if side == "long":
        return "longs"
    if side == "short":
        return "shorts"
    return ""


def _also_line(story: Story) -> str:
    f = story.facts
    label = f.get("also_label")
    pct = f.get("also_pct")
    if not label or pct is None:
        return ""
    if str(label).upper() == str(f.get("label") or "").upper():
        return ""
    side = _side_word(str(f.get("also_side") or ""))
    bit = f" {side}" if side else ""
    return f"{_tick(str(label))}{bit} still {pct}% on the same board — that's the part this chart leaves out."


def _maybe_source(story: Story, lines: list[str]) -> str:
    text = "\n".join(line for line in lines if line).strip()
    if story.include_source and story.source_line not in text:
        text = f"{text}\n{story.source_line}"
    return text.strip()


def _load(story: Story) -> str:
    f = story.facts
    t = _tick(f["label"])
    board = _crowd(story)
    also = _also_line(story)
    side = _side_word(str(f.get("side") or ""))
    side_bit = f" {side}" if side else ""
    voices = [
        [
            f"{t}{side_bit} now {f['to_pct']}% of {board}, {f['hours']}h.",
            also or "One line. The rest of the names are on the map.",
        ],
        [
            also or f"The chart is only {t}.",
            f"{f['pp']}pp in {f['hours']}h, now {f['to_pct']}%.",
        ],
        [
            f"{f['hours']}h, {t}{side_bit} at {f['to_pct']}%.",
            also or f"Was {f['from_pct']}% — the other tiles are why the link is there.",
        ],
    ]
    if float(f["to_pct"]) >= float(f["from_pct"]) * 1.9 and float(f["from_pct"]) > 0:
        voices.append(
            [
                f"{t}{side_bit} nearly doubled in {f['hours']}h. Now {f['to_pct']}%.",
                also or "The board shows who didn't.",
            ]
        )
    return _maybe_source(story, random.choice(voices))


def _dump(story: Story) -> str:
    f = story.facts
    t = _tick(f["label"])
    board = _crowd(story)
    also = _also_line(story)
    side = _side_word(str(f.get("side") or ""))
    side_bit = f" {side}" if side else ""
    voices = [
        [
            f"{t}{side_bit} down to {f['to_pct']}% of {board} in {f['hours']}h.",
            also or "Whatever took that share is on the map.",
        ],
        [
            also or f"Look at who is still large.",
            f"{t} gave up {f['pp']}pp. {f['to_pct']}% left after {f['hours']}h.",
        ],
        [
            f"{f['hours']}h and {t} is {f['to_pct']}% of {board}.",
            also or f"It was {f['from_pct']}%. The link is the other names.",
        ],
    ]
    return _maybe_source(story, random.choice(voices))


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
        needed = [f"{f['to_pct']}", str(f["hours"])]
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
    banned = (
        "source:",
        "been adding",
        "this tracks",
        "is coming off the board",
        "started loading",
        "started dumping",
        "moved from",
        "not one whale",
        "pnl pnl",
        "roi roi",
    )
    if any(phrase in low for phrase in banned) or low.startswith("yeah"):
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
        log.info("Claude output dropped: %s", (text or "")[:180].replace("\n", " | "))
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
