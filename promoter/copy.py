"""Sentences are built from the board. Claude stays off unless CLAUDE_RATE is set."""

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


def _who(story: Story) -> str:
    n = story.listed
    if story.ranker == "roi":
        return f"the top {n} wallets by 7-day return"
    if story.ranker == "both":
        return f"the top {n} wallets by profit and return"
    return f"the top {n} wallets by 7-day profit"


def _side_word(side: str) -> str:
    if side == "long":
        return "long"
    if side == "short":
        return "short"
    return ""


def _also_bit(story: Story) -> str:
    f = story.facts
    label = f.get("also_label")
    pct = f.get("also_pct")
    if not label or pct is None:
        return ""
    if str(label).upper() == str(f.get("label") or f.get("top_label") or "").upper():
        return ""
    side = _side_word(str(f.get("also_side") or ""))
    bit = f" {side}" if side else ""
    return f"{_tick(str(label))} is still {pct}%{bit} on that same board."


def _maybe_source(story: Story, lines: list[str]) -> str:
    # A URL in the text is $0.20. The same post with no URL is $0.015.
    # The chart already prints bagrank.xyz. Do not put it in the tweet.
    return "\n".join(line for line in lines if line).strip()


def _opener(text: str) -> str:
    line = text.strip().split("\n", 1)[0].lower()
    return " ".join(line.split()[:4])


def _choose(story: Story, voices: list[list[str]], recent: list[str] | None) -> str:
    used = {_opener(t) for t in (recent or [])}
    order = voices[:]
    random.shuffle(order)
    fallback = ""
    for lines in order:
        text = _maybe_source(story, [ln for ln in lines if ln])
        if not fallback:
            fallback = text
        if _opener(text) not in used:
            return text
    return fallback


def _load(story: Story, recent: list[str] | None = None) -> str:
    f = story.facts
    t = _tick(f["label"])
    who = _who(story)
    also = _also_bit(story)
    voices = [
        [
            f"{t} is a bigger share of {who} than it was {f['hours']} hours ago.",
            f"{f['from_pct']}% then, {f['to_pct']}% now.",
        ],
        [
            f"{f['hours']} hours ago, {f['from_pct']}% of {who} were in {t}.",
            f"It's {f['to_pct']}% now.",
        ],
        [
            also,
            f"{t} grew from {f['from_pct']}% to {f['to_pct']}% in {f['hours']} hours.",
        ],
    ]
    return _choose(story, voices, recent)


def _dump(story: Story, recent: list[str] | None = None) -> str:
    f = story.facts
    t = _tick(f["label"])
    who = _who(story)
    also = _also_bit(story)
    voices = [
        [
            f"{t} is a smaller share of {who} than it was {f['hours']} hours ago.",
            f"{f['from_pct']}% then, {f['to_pct']}% now.",
        ],
        [
            f"{f['hours']} hours ago, {f['from_pct']}% of {who} were in {t}.",
            f"{f['to_pct']}% are now.",
        ],
        [
            also,
            f"{t} went from {f['from_pct']}% to {f['to_pct']}% over {f['hours']} hours.",
        ],
    ]
    return _choose(story, voices, recent)


def _inflow(story: Story, recent: list[str] | None = None) -> str:
    f = story.facts
    t = _tick(f["label"])
    side = _side_word(str(f.get("side") or ""))
    side_bit = f" {side}" if side else ""
    voices = [
        [
            f"Over the last hour, more of {_who(story)} moved into {t}.",
            f"{f['hold_pct']}% of them are{side_bit} it now.",
        ],
        [
            f"{t} picked up share this hour.",
            f"{f['hold_pct']}% of {_who(story)} are{side_bit} it.",
        ],
    ]
    return _choose(story, voices, recent)


def _outflow(story: Story, recent: list[str] | None = None) -> str:
    f = story.facts
    t = _tick(f["label"])
    side = _side_word(str(f.get("side") or ""))
    side_bit = f" {side}" if side else ""
    voices = [
        [
            f"Over the last hour, fewer of {_who(story)} are in {t}.",
            f"{f['hold_pct']}% are still{side_bit}.",
        ],
        [
            f"{t} lost share in the last hour.",
            f"{f['hold_pct']}% of {_who(story)} are still{side_bit} it.",
        ],
    ]
    return _choose(story, voices, recent)


def _dominate(story: Story, recent: list[str] | None = None) -> str:
    f = story.facts
    t = _tick(f["label"])
    side = _side_word(str(f.get("side") or ""))
    who = _who(story)
    voices = [
        [
            f"This is where {who} are sitting.",
            f"{t} is the biggest slice, {f['hold_pct']}% {side}.",
        ],
        [
            f"{f['hold_pct']}% of {who} are {side} {t}.",
            "That's the largest name on the board.",
        ],
        [
            f"{f['wallets']} of {who} are in {t}, {f['agree']}% on the same side.",
        ],
    ]
    return _choose(story, voices, recent)


def _flip(story: Story, recent: list[str] | None = None) -> str:
    f = story.facts
    t = _tick(f["label"])
    voices = [
        [
            f"{t} was {f['from_side']}. {_who(story)} are {f['to_side']} it now.",
            f"{f['hold_pct']}% of them.",
        ],
        [
            f"{_who(story)} flipped {t} from {f['from_side']} to {f['to_side']}.",
            f"{f['hold_pct']}% of the board.",
        ],
    ]
    return _choose(story, voices, recent)


def _digest(story: Story, recent: list[str] | None = None) -> str:
    f = story.facts
    t = _tick(f["top_label"])
    side = _side_word(str(f.get("top_side") or ""))
    voices = [
        [
            f"{t} is still the biggest name on {_who(story)}, {f['top_pct']}% {side}.",
            "The rest of the names are on the board.",
        ],
    ]
    return _choose(story, voices, recent)


def _ranks(story: Story, recent: list[str] | None = None) -> str:
    f = story.facts
    bits = []
    for row in (f.get("rows") or [])[:3]:
        bits.append(f"{_tick(row['label'])} {row['hold_pct']}% {row['side']}")
    voices = [
        [f"Right now, {_who(story)}: {', '.join(bits)}."],
    ]
    return _choose(story, voices, recent)


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


def template_text(story: Story, recent: list[str] | None = None) -> str:
    return _fit(TEMPLATES[story.kind](story, recent))

def _split_cta(text: str) -> tuple[str, str]:
    lines = [ln.rstrip() for ln in text.strip().split("\n")]
    if lines and "bagrank.xyz" in lines[-1].lower():
        return "\n".join(lines[:-1]).strip(), lines[-1].strip()
    return text.strip(), ""


_URL = re.compile(
    r"https?://\S+|www\.\S+|\b[\w.-]+\.(?:xyz|com|io|app|gg|net|org)\b\S*",
    re.I,
)


def strip_urls(text: str) -> str:
    """X bills a post with a link at $0.20 and a post without one at $0.015."""
    kept: list[str] = []
    for line in text.splitlines():
        cleaned = _URL.sub("", line).strip(" \t-–—")
        if cleaned:
            kept.append(cleaned)
    return "\n".join(kept).strip()


def _fit(text: str, limit: int = 280) -> str:
    text = strip_urls(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) <= limit:
        return text
    while text and len(text) > limit:
        if "\n" in text:
            text = text.rsplit("\n", 1)[0]
        else:
            text = text[:limit].rstrip()
            break
    return text.strip()[:limit]


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
    recent = store.recent_texts()
    base = template_text(story, recent)
    # Off unless CLAUDE_RATE is set above 0. A dropped rewrite is money spent for nothing.
    if cfg.claude_rate <= 0 or not cfg.has_claude():
        return base, False
    if store.claude_today(now) >= cfg.claude_max_per_day:
        return base, False
    if random.random() > cfg.claude_rate:
        return base, False
    rewritten = _claude(cfg, story)
    if not rewritten or _too_close(rewritten, recent):
        return base, False
    store.mark_claude(now)
    return rewritten, True
