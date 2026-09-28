"""PNG cards sized so labels survive X's compression."""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .models import Board, Pair, Series, Story

# 16:9. X shows ~400px wide in the mobile feed, so type here must
# still read after a ~4x shrink. 48–56px → ~12–14px on a phone.
W, H = 1600, 900
PAD = 32
HEADER_H = 84
INK = (245, 245, 247)
MUTED = (176, 180, 188)
DIM = (118, 122, 130)
LINE = (58, 60, 66)
WELL = (12, 13, 16)
PANEL = (22, 23, 26)
LONG = (48, 209, 141)
SHORT = (255, 69, 58)
FOCUS = (48, 209, 141)
OTHERS = [(100, 210, 255), (255, 159, 10)]

_FONT_DIR = Path(__file__).resolve().parent / "fonts"


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    names = [
        _FONT_DIR / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),
        Path("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        ),
    ]
    for name in names:
        if name.exists():
            try:
                return ImageFont.truetype(str(name), size)
            except OSError:
                continue
    raise RuntimeError(
        "No TTF font found. Keep promoter/fonts/DejaVuSans.ttf in the repo "
        "(X will crush Pillow's bitmap default into unreadability)."
    )


def _who(ranker: str, listed: int) -> str:
    if ranker == "roi":
        return f"7d ROI · top {listed}"
    if ranker == "both":
        return f"PnL + ROI · top {listed}"
    return f"7d PnL · top {listed}"


def _width(font: ImageFont.ImageFont, text: str) -> int:
    box = font.getbbox(text)
    return max(1, box[2] - box[0])


def _blend(rgb: tuple[int, int, int], a: float, bg: tuple[int, int, int] = WELL) -> tuple[int, int, int]:
    a = max(0.0, min(1.0, a))
    return tuple(int(c * a + b * (1 - a)) for c, b in zip(rgb, bg))  # type: ignore[return-value]


def _tile_fill(pair: Pair) -> tuple[int, int, int]:
    a = 0.28 + pair.agreement * 0.50
    return _blend(LONG if pair.side == "long" else SHORT, a)


def _text(draw: ImageDraw.ImageDraw, xy, text, font, fill=INK, anchor="lt", stroke=0):
    kwargs = {
        "font": font,
        "fill": fill,
        "anchor": anchor,
    }
    if stroke:
        kwargs["stroke_width"] = stroke
        kwargs["stroke_fill"] = (8, 9, 12)
    draw.text(xy, text, **kwargs)


def _card(board: Board) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    im = Image.new("RGBA", (W, H), PANEL + (255,))
    d = ImageDraw.Draw(im, "RGBA")
    _text(d, (PAD, PAD + 36), "bagrank.xyz", _font(52, True), INK, "lm")
    _text(d, (W - PAD, PAD + 36), _who(board.ranker, board.listed), _font(26, True), MUTED, "rm")
    return im, d


def _map_box() -> tuple[int, int, int, int]:
    x0, y0 = PAD, PAD + HEADER_H + 10
    x1, y1 = W - PAD, H - PAD
    return x0, y0, x1, y1


def _well(d: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    d.rounded_rectangle(box, radius=18, fill=WELL)


def _cash(label: str) -> str:
    return "$" + label.strip().lstrip("$").upper()


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


def render_heatmap(board: Board, story: Story | None = None) -> bytes:
    im, d = _card(board)
    box = _map_box()
    _well(d, box)
    x0, y0, x1, y1 = box
    title = "Where the top wallets sit right now"
    if story and story.kind == "dominate" and story.pair:
        title = f"{_cash(story.pair.label)} is the biggest tile"
    elif story and story.kind == "ranks":
        title = "Hold map · largest names first"
    _text(d, (x0 + 28, y0 + 24), title, _font(42, True), INK, "lt")
    _text(
        d,
        (x0 + 28, y0 + 76),
        "Tile size = share of wallets in that name · green long / red short",
        _font(24),
        MUTED,
        "lt",
    )
    mx0, my0 = x0 + 16, y0 + 118
    mx1, my1 = x1 - 16, y1 - 16
    mw, mh = mx1 - mx0, my1 - my0
    by_coin = {p.coin: p for p in board.rows}
    rects = squarify([(p.coin, p.hold_pct) for p in board.rows], mw, mh)
    for coin, x, y, w, h in rects:
        if w < 4 or h < 4:
            continue
        pair = by_coin.get(coin)
        if pair is None:
            continue
        rx0, ry0 = mx0 + x, my0 + y
        d.rectangle(
            [rx0, ry0, rx0 + w, ry0 + h],
            fill=_tile_fill(pair),
            outline=(255, 255, 255, 40),
        )
        if w < 130 or h < 64:
            continue
        fs = max(24, min(42, int(min(w / 4.8, h / 2.4))))
        label = _cash(pair.label)
        _text(d, (rx0 + 14, ry0 + 12), label, _font(fs, True), INK, "lt", stroke=1)
        if h > 88:
            meta = f"{pair.side.upper()}  {pair.hold_pct * 100:.1f}%"
            _text(d, (rx0 + 14, ry0 + 16 + fs), meta, _font(max(20, fs - 8), True), INK, "lt")
    return _png(im)


def _nice_max(raw: float) -> float:
    pct = max(0.08, raw * 1.12)
    step = 0.1 if pct > 0.4 else 0.05 if pct > 0.2 else 0.02
    return (int(pct / step) + 1) * step


def _hold_title(story: Story | None, series: list[Series], focus: str | None) -> tuple[str, str]:
    focus_s = next((s for s in series if s.coin == focus), series[0] if series else None)
    label = _cash(focus_s.label) if focus_s else "Hold share"
    f = story.facts if story else {}
    hours = f.get("hours")
    from_pct = f.get("from_pct")
    to_pct = f.get("to_pct")
    if from_pct is not None and to_pct is not None:
        title = f"{label}   {from_pct}%  →  {to_pct}%"
    elif story and story.kind == "dump":
        title = f"{label} is being cut"
    elif story and story.kind == "flip":
        title = f"{label} flipped sides"
    else:
        title = f"{label} hold share"
    if hours:
        sub = f"Last {hours}h among top wallets · one vote each · not size-weighted"
    else:
        sub = "Last 24h among top wallets · one vote each · not size-weighted"
    return title, sub


def render_hold(board: Board, series: list[Series], story: Story | None, focus: str | None) -> bytes:
    im, d = _card(board)
    box = _map_box()
    _well(d, box)
    x0, y0, x1, y1 = box

    series = series[:3]
    title, sub = _hold_title(story, series, focus)
    _text(d, (x0 + 28, y0 + 22), title, _font(46, True), INK, "lt")
    _text(d, (x0 + 28, y0 + 76), sub, _font(24), MUTED, "lt")

    legend_y = y0 + 118
    lx = x0 + 28
    f_leg = _font(30, True)
    others = [x for x in series if x.coin != focus]
    for s in series:
        last = s.points[-1] if s.points else None
        if s.coin == focus:
            color = FOCUS
        else:
            color = OTHERS[others.index(s) % len(OTHERS)]
        pct = f"{last.hold_pct * 100:.1f}%" if last else ""
        tag = f"{_cash(s.label)}  {pct}".rstrip()
        d.rounded_rectangle([lx, legend_y + 4, lx + 26, legend_y + 20], radius=4, fill=color)
        _text(d, (lx + 36, legend_y + 12), tag, f_leg, INK, "lm")
        lx += 36 + _width(f_leg, tag) + 36

    pad_l, pad_r, pad_t, pad_b = 80, 170, 218, 58
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

    f_axis = _font(24, True)
    ticks = [0.0, y_max / 2, y_max]
    for tick in ticks:
        yy = y_at(tick)
        d.line([(px0, yy), (px1, yy)], fill=(255, 255, 255, 28), width=2)
        _text(d, (px0 - 14, yy), f"{int(round(tick * 100))}%", f_axis, MUTED, "rm")

    if hours:
        labels = [0, len(hours) // 2, len(hours) - 1] if len(hours) > 2 else list(range(len(hours)))
        seen: set[int] = set()
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
            _text(d, (x_at(i), y1 - 18), hh, f_axis, MUTED, anchor)

    hour_index = {int(h.timestamp() // 3600): i for i, h in enumerate(hours)}

    def color_for(s: Series) -> tuple[int, int, int]:
        if s.coin == focus:
            return FOCUS
        others = [x for x in series if x.coin != focus]
        try:
            return OTHERS[others.index(s) % len(OTHERS)]
        except ValueError:
            return OTHERS[0]

    def draw_series(s: Series, *, thick: bool) -> None:
        color = color_for(s)
        pts: list[tuple[float, float]] = []
        last_p = None
        for p in s.points:
            idx = hour_index.get(int(p.ts.timestamp() // 3600))
            if idx is None:
                continue
            pts.append((x_at(idx), y_at(p.hold_pct)))
            last_p = p
        if thick and len(pts) >= 2:
            floor = [(pts[0][0], py1)] + pts + [(pts[-1][0], py1)]
            d.polygon(floor, fill=_blend(color, 0.24))
        if len(pts) >= 2:
            d.line(pts, fill=color + (255,), width=8 if thick else 3, joint="curve")
        if pts and last_p:
            x, y = pts[-1]
            r = 8 if thick else 5
            d.ellipse([x - r, y - r, x + r, y + r], fill=color)
            if thick:
                start_p = s.points[0] if s.points else None
                if start_p and pts:
                    sx, sy = pts[0]
                    _text(
                        d,
                        (sx, sy - 18),
                        f"{start_p.hold_pct * 100:.1f}%",
                        _font(26, True),
                        MUTED,
                        "mb",
                    )
                tag = f"{_cash(s.label)}  {last_p.hold_pct * 100:.1f}%"
                _text(d, (x + 16, y), tag, _font(34, True), color, "lm", stroke=1)

    for s in series:
        if s.coin != focus:
            draw_series(s, thick=False)
    for s in series:
        if s.coin == focus:
            draw_series(s, thick=True)
            break
    else:
        if series:
            draw_series(series[0], thick=True)

    return _png(im)


def render_movers(board: Board, story: Story | None = None) -> bytes:
    im, d = _card(board)
    box = _map_box()
    _well(d, box)
    x0, y0, x1, y1 = box
    mid = (x0 + x1) / 2
    d.line([(mid, y0 + 28), (mid, y1 - 28)], fill=LINE, width=2)
    _text(d, (x0 + 32, y0 + 28), "Added this hour", _font(38, True), LONG, "lt")
    _text(d, (mid + 32, y0 + 28), "Cut this hour", _font(38, True), SHORT, "lt")
    _text(
        d,
        (x0 + 32, y0 + 76),
        "Change in share of top wallets vs the previous hour",
        _font(22),
        MUTED,
        "lt",
    )

    movers = [p for p in board.rows if p.hold_delta is not None]
    ins = sorted((p for p in movers if (p.hold_delta or 0) > 0.002), key=lambda p: -(p.hold_delta or 0))[:5]
    outs = sorted((p for p in movers if (p.hold_delta or 0) < -0.002), key=lambda p: (p.hold_delta or 0))[:5]
    max_abs = max(
        [0.01]
        + [abs(p.hold_delta or 0) for p in ins]
        + [abs(p.hold_delta or 0) for p in outs]
    )
    f_name = _font(32, True)
    f_meta = _font(22)
    f_pp = _font(32, True)
    bar_max = (mid - x0) - 80

    def col(rows: list[Pair], left: float, color: tuple[int, int, int], focus: str | None) -> None:
        y = y0 + 118
        for p in rows:
            delta = p.hold_delta or 0
            name = _cash(p.label)
            if p.coin == focus:
                d.rounded_rectangle(
                    [left - 12, y - 8, left + bar_max + 24, y + 70],
                    radius=10,
                    fill=_blend(color, 0.16),
                )
            _text(d, (left, y), name, f_name, INK, "lt")
            meta = f"{p.side} · now {p.hold_pct * 100:.1f}%"
            if p.dex:
                meta = f"{p.dex} · {meta}"
            _text(d, (left, y + 32), meta, f_meta, MUTED, "lt")
            sign = "+" if delta > 0 else "−"
            _text(
                d,
                (left + bar_max, y),
                f"{sign}{abs(delta) * 100:.1f} pp",
                f_pp,
                color,
                "rt",
            )
            bar_w = (bar_max - 8) * (abs(delta) / max_abs)
            d.rounded_rectangle(
                [left, y + 56, left + bar_w, y + 66],
                radius=4,
                fill=color,
            )
            y += 100

    focus = None if story is None else story.focus_coin
    col(ins, x0 + 32, LONG, focus)
    col(outs, mid + 32, SHORT, focus)
    return _png(im)


def _png(im: Image.Image) -> bytes:
    buf = BytesIO()
    im.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_story(board: Board, story: Story) -> bytes:
    if story.chart == "hold":
        series = story.chart_series or board.series[:3]
        return render_hold(board, series, story, story.focus_coin)
    if story.chart == "movers":
        return render_movers(board, story)
    return render_heatmap(board, story)
