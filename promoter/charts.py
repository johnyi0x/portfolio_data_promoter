"""PNG cards that match bagrank.xyz (heatmap, 24h hold, movers)."""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .models import Board, Pair, Series, Story

W, H = 1200, 675
PAD = 22
HEADER_H = 40
HEADER_GAP = 8
INK = (245, 245, 247)
MUTED = (245, 245, 247, 132)
LINE = (255, 255, 255, 31)
WELL = (12, 13, 16)
PANEL = (22, 23, 26)
LONG = (48, 209, 141)
SHORT = (255, 69, 58)
CHART_LINE = [
    (48, 209, 141),
    (100, 210, 255),
    (255, 159, 10),
    (191, 90, 242),
    (255, 69, 58),
]


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    names = (
        [
            "C:/Windows/Fonts/segoeuib.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ]
        if bold
        else [
            "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]
    )
    for name in names:
        if Path(name).exists():
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _who(ranker: str) -> str:
    return {"pnl": "PNL RANKER", "roi": "ROI RANKER", "both": "PNL + ROI"}.get(
        ranker, "PNL RANKER"
    )


def _blend(rgb: tuple[int, int, int], a: float, bg: tuple[int, int, int] = WELL) -> tuple[int, int, int]:
    a = max(0.0, min(1.0, a))
    return tuple(int(c * a + b * (1 - a)) for c, b in zip(rgb, bg))  # type: ignore[return-value]


def _tile_fill(pair: Pair) -> tuple[int, int, int]:
    a = 0.18 + pair.agreement * 0.42
    return _blend(LONG if pair.side == "long" else SHORT, a)


def _text(draw: ImageDraw.ImageDraw, xy, text, font, fill=INK, anchor="lt"):
    draw.text(xy, text, font=font, fill=fill, anchor=anchor)


def _card(ranker: str, listed: int, captured: str | None) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    im = Image.new("RGBA", (W, H), PANEL + (255,))
    d = ImageDraw.Draw(im, "RGBA")
    f15 = _font(15, True)
    f13 = _font(13, True)
    left = f"HYPERLIQUID {listed} BAGRANK · {_who(ranker)}"
    _text(d, (PAD, PAD + 12), left, f15, MUTED, "lm")
    refreshed = (
        f"LAST REFRESHED AT {captured} UTC" if captured else "LAST REFRESHED —"
    )
    right = "REFRESH EVERY 1H    " + refreshed
    _text(d, (W - PAD, PAD + 12), right, f13, MUTED, "rm")
    return im, d


def _map_box() -> tuple[int, int, int, int]:
    x0, y0 = PAD, PAD + HEADER_H + HEADER_GAP
    x1, y1 = W - PAD, H - PAD
    return x0, y0, x1, y1


def _well(d: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    d.rounded_rectangle(box, radius=14, fill=WELL)


def _mark(d: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    x0, y0, x1, y1 = box
    _text(d, (x1 - 16, y0 + 18), "bagrank.xyz", _font(22, True), (245, 245, 247, 66), "rm")


# --- squarify (same algorithm as the website) ---

def _worst(row: list[tuple[str, float]], w: float) -> float:
    s = sum(v for _, v in row)
    if s <= 0:
        return 1e9
    worst = 0.0
    for _, v in row:
        r = (w * w * v) / (s * s)
        worst = max(worst, r, 1 / r if r else 1e9)
    return worst


def squarify(items: list[tuple[str, float]], width: float, height: float):
    total = sum(v for _, v in items)
    if total <= 0 or width <= 0 or height <= 0:
        return []
    nodes = sorted(
        ((i, (v / total) * width * height) for i, v in items if v > 0),
        key=lambda x: -x[1],
    )
    out = []
    box = [0.0, 0.0, width, height]
    row: list[tuple[str, float]] = []

    def flush(final: bool = False) -> None:
        nonlocal row
        if not row:
            return
        bx, by, bw, bh = box
        vertical = bw >= bh
        s = sum(v for _, v in row)
        if vertical:
            rw = s / bh if bh else 0
            off = 0.0
            for i, v in row:
                h = bh * (v / s) if s else 0
                out.append((i, bx, by + off, rw, h))
                off += h
            box[0] += rw
            box[2] -= rw
        else:
            rh = s / bw if bw else 0
            off = 0.0
            for i, v in row:
                w = bw * (v / s) if s else 0
                out.append((i, bx + off, by, w, rh))
                off += w
            box[1] += rh
            box[3] -= rh
        row = []
        if final and box[2] > 0 and box[3] > 0:
            pass

    while nodes:
        nxt = nodes[0]
        w = min(box[2], box[3])
        if not row or _worst(row + [nxt], w) <= _worst(row, w):
            row.append(nodes.pop(0))
            continue
        flush()
    flush(True)
    if row:
        bx, by, bw, bh = box
        vertical = bw >= bh
        s = sum(v for _, v in row)
        off = 0.0
        for i, v in row:
            frac = v / s if s else 0
            if vertical:
                h = bh * frac
                out.append((i, bx, by + off, bw, h))
                off += h
            else:
                w = bw * frac
                out.append((i, bx + off, by, w, bh))
                off += w
        row = []
    return out


def render_heatmap(board: Board) -> bytes:
    im, d = _card(board.ranker, board.listed, board.captured_at)
    box = _map_box()
    _well(d, box)
    x0, y0, x1, y1 = box
    mw, mh = x1 - x0, y1 - y0
    by_coin = {p.coin: p for p in board.rows}
    rects = squarify([(p.coin, p.hold_pct) for p in board.rows], mw, mh)
    for coin, x, y, w, h in rects:
        if w < 2 or h < 2:
            continue
        pair = by_coin.get(coin)
        if pair is None:
            continue
        rx0, ry0 = x0 + x, y0 + y
        d.rectangle([rx0, ry0, rx0 + w, ry0 + h], fill=_tile_fill(pair), outline=(255, 255, 255, 28))
        if w < 56 or h < 28:
            continue
        fs = max(10, min(18, int(min(w / 6, h / 3))))
        _text(d, (rx0 + 8, ry0 + 8), pair.label, _font(fs, True), INK, "lt")
        if h > 44:
            meta = f"{pair.side.upper()} {pair.hold_pct * 100:.1f}%"
            _text(d, (rx0 + 8, ry0 + 8 + fs + 4), meta, _font(max(9, fs - 4)), MUTED, "lt")
    _mark(d, box)
    return _png(im)


def _nice_max(raw: float) -> float:
    pct = max(0.08, raw * 1.08)
    step = 0.1 if pct > 0.4 else 0.05 if pct > 0.2 else 0.02
    return (int(pct / step) + 1) * step


def render_hold(board: Board, series: list[Series], focus: str | None) -> bytes:
    im, d = _card(board.ranker, board.listed, board.captured_at)
    box = _map_box()
    _well(d, box)
    x0, y0, x1, y1 = box
    pad_l, pad_r, pad_t, pad_b = 18, 86, 28, 32
    px0, py0 = x0 + pad_l, y0 + pad_t
    px1, py1 = x1 - pad_r, y1 - pad_b
    plot_w, plot_h = max(1, px1 - px0), max(1, py1 - py0)

    hours = board.hours
    if not hours:
        hours = sorted({p.ts for s in series for p in s.points})
    y_max = 0.08
    for s in series:
        for p in s.points:
            y_max = max(y_max, p.hold_pct)
    y_max = _nice_max(y_max)

    def x_at(i: int) -> float:
        if len(hours) <= 1:
            return px1
        return px0 + (i / (len(hours) - 1)) * plot_w

    def y_at(pct: float) -> float:
        return py0 + (1 - pct / y_max) * plot_h

    f11 = _font(11)
    ticks = [0.0, y_max / 2, y_max]
    for tick in ticks:
        yy = y_at(tick)
        d.line([(px0, yy), (px1, yy)], fill=(255, 255, 255, 22), width=1)
        _text(d, (px1 + 8, yy), f"{int(round(tick * 100))}%", f11, MUTED, "lm")

    if hours:
        labels = [0, len(hours) // 2, len(hours) - 1] if len(hours) > 2 else list(range(len(hours)))
        seen = set()
        for i in labels:
            i = max(0, min(len(hours) - 1, i))
            if i in seen:
                continue
            seen.add(i)
            ts = hours[i]
            if isinstance(ts, datetime):
                h = ts.astimezone(timezone.utc).hour
                hour12 = h % 12 or 12
                am = "am" if h < 12 else "pm"
                hh = f"{hour12}{am}"
            else:
                hh = ""
            anchor = "lt" if i == 0 else "rt" if i == len(hours) - 1 else "mt"
            _text(d, (x_at(i), y1 - 10), hh, f11, MUTED, anchor)

    hour_index = {int(h.timestamp() // 3600): i for i, h in enumerate(hours)}
    for si, s in enumerate(series[:5]):
        color = CHART_LINE[si % len(CHART_LINE)]
        pts: list[tuple[float, float]] = []
        last_p = None
        for p in s.points:
            idx = hour_index.get(int(p.ts.timestamp() // 3600))
            if idx is None:
                continue
            pts.append((x_at(idx), y_at(p.hold_pct)))
            last_p = p
        if len(pts) >= 2:
            width = 4 if s.coin == focus else 2
            d.line(pts, fill=color + (255,), width=width, joint="curve")
        if pts and last_p:
            x, y = pts[-1]
            d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=color)
            tag = f"{s.label} {last_p.hold_pct * 100:.1f}%"
            _text(d, (x + 8, y), tag, _font(12, True), color, "lm")
    _mark(d, box)
    return _png(im)


def render_movers(board: Board) -> bytes:
    im, d = _card(board.ranker, board.listed, board.captured_at)
    box = _map_box()
    _well(d, box)
    x0, y0, x1, y1 = box
    mid = (x0 + x1) / 2
    d.line([(mid, y0 + 16), (mid, y1 - 16)], fill=LINE, width=1)
    movers = [p for p in board.rows if p.hold_delta is not None]
    ins = sorted((p for p in movers if (p.hold_delta or 0) > 0.002), key=lambda p: -(p.hold_delta or 0))[:6]
    outs = sorted((p for p in movers if (p.hold_delta or 0) < -0.002), key=lambda p: (p.hold_delta or 0))[:6]
    max_abs = max(
        [0.01]
        + [abs(p.hold_delta or 0) for p in ins]
        + [abs(p.hold_delta or 0) for p in outs]
    )
    f16 = _font(16, True)
    f13 = _font(13, True)
    f12 = _font(12)
    _text(d, (x0 + 28, y0 + 28), "IN THIS HOUR", f16, LONG, "lt")
    _text(d, (mid + 28, y0 + 28), "OUT THIS HOUR", f16, SHORT, "lt")

    def col(rows: list[Pair], left: float, color: tuple[int, int, int]) -> None:
        y = y0 + 64
        for p in rows:
            delta = p.hold_delta or 0
            _text(d, (left, y), p.label, f13, INK, "lt")
            if p.dex:
                box = d.textbbox((left, y), p.label, font=f13)
                _text(d, (box[2] + 8, y), p.dex, f12, MUTED, "lt")
            sign = "+" if delta > 0 else ""
            _text(
                d,
                (left + 430, y),
                f"{sign}{delta * 100:.1f}",
                f13,
                color,
                "rt",
            )
            bar_w = 420 * (abs(delta) / max_abs)
            d.rounded_rectangle(
                [left, y + 22, left + bar_w, y + 30],
                radius=3,
                fill=_blend(color, 0.55 if p.side == "long" else 0.7),
            )
            y += 72

    col(ins, x0 + 28, LONG)
    col(outs, mid + 28, SHORT)
    _mark(d, box)
    return _png(im)


def _png(im: Image.Image) -> bytes:
    buf = BytesIO()
    im.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_story(board: Board, story: Story) -> bytes:
    if story.chart == "hold":
        return render_hold(board, story.chart_series or board.series[:5], story.focus_coin)
    if story.chart == "movers":
        return render_movers(board)
    return render_heatmap(board)
