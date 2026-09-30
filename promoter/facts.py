"""Pick one postable story from a board. Numbers only — no LLM here."""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Iterable

from .models import Board, HistPoint, Pair, Ranker, Series, Story

LOAD_MIN_PP = 0.025
LOAD_MIN_HOURS = 3.0
LOAD_MAX_HOURS = 18.0
HOUR_MOVE_MIN = 0.012
DOMINATE_MIN = 0.10


def source_line(ranker: Ranker, host: str) -> str:
    if ranker == "pnl":
        return host
    if ranker == "roi":
        return f"{host}/?ranker=roi"
    return f"{host}/?ranker=both"


def pick_ranker(has_roi: bool, last: str) -> Ranker:
    if not has_roi:
        return "pnl"
    roll = random.random()
    # Prefer the live default board. Promote the new combined tab sometimes.
    if last == "pnl":
        if roll < 0.22:
            return "both"
        if roll < 0.38:
            return "roi"
        return "pnl"
    if roll < 0.62:
        return "pnl"
    if roll < 0.82:
        return "both"
    return "roi"


def _series_map(board: Board) -> dict[str, Series]:
    return {s.coin: s for s in board.series}


def _utc_hour(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%H:%M utc")


def _run(
    points: list[HistPoint],
    *,
    load: bool,
) -> tuple[HistPoint, HistPoint, float, float] | None:
    if len(points) < 4:
        return None
    last = points[-1]
    window = [
        p
        for p in points[:-1]
        if 0 < (last.ts - p.ts).total_seconds() / 3600.0 <= LOAD_MAX_HOURS
    ]
    if len(window) < 2:
        return None
    if load:
        anchor = min(window, key=lambda p: p.hold_pct)
        delta = last.hold_pct - anchor.hold_pct
    else:
        anchor = max(window, key=lambda p: p.hold_pct)
        delta = anchor.hold_pct - last.hold_pct
    hours = (last.ts - anchor.ts).total_seconds() / 3600.0
    if hours < LOAD_MIN_HOURS or delta < LOAD_MIN_PP:
        return None
    return anchor, last, delta, hours


def _story(
    *,
    kind,
    board: Board,
    score: float,
    key: str,
    chart: str,
    focus: str | None,
    pair: Pair | None,
    facts: dict,
    include_source: bool,
    host: str,
    series: list[Series] | None = None,
) -> Story:
    return Story(
        kind=kind,
        ranker=board.ranker,
        score=score,
        key=key,
        chart=chart,  # type: ignore[arg-type]
        focus_coin=focus,
        pair=pair,
        facts=facts,
        include_source=include_source,
        source_line=source_line(board.ranker, host),
        listed=board.listed,
        captured_at=board.captured_at,
        cycle_stamp=board.cycle_stamp,
        top_rows=board.rows[:5],
        chart_series=series or board.series[:3],
        hours=board.hours,
    )


def _also(board: Board, focus: str | None) -> dict:
    """A second name the single-line chart does not show. Reason to open the site."""
    for pair in board.rows:
        if focus and pair.coin == focus:
            continue
        return {
            "also_label": pair.label,
            "also_pct": round(pair.hold_pct * 100, 1),
            "also_side": pair.side,
        }
    return {}


def _chart_series(board: Board, focus: str | None) -> list[Series]:
    smap = _series_map(board)
    if focus and focus in smap:
        return [smap[focus]]
    return board.series[:1]


def collect_stories(board: Board, host: str, include_source: bool) -> list[Story]:
    if not board.rows:
        return []
    out: list[Story] = []
    smap = _series_map(board)
    cycle = board.cycle_stamp or "na"
    listed = board.listed

    for pair in board.rows[:15]:
        ser = smap.get(pair.coin)
        if ser is None or len(ser.points) < 4:
            continue
        loaded = _run(ser.points, load=True)
        if loaded:
            a, last, delta, hours = loaded
            out.append(
                _story(
                    kind="load",
                    board=board,
                    score=delta * 100 + hours,
                    key=f"load:{board.ranker}:{pair.coin}:{cycle[:13]}",
                    chart="hold",
                    focus=pair.coin,
                    pair=pair,
                    facts={
                        "label": pair.label,
                        "dex": pair.dex,
                        "side": last.side,
                        "from_pct": round(a.hold_pct * 100, 1),
                        "to_pct": round(last.hold_pct * 100, 1),
                        "pp": round(delta * 100, 1),
                        "hours": int(round(hours)),
                        "start": _utc_hour(a.ts),
                        "listed": listed,
                        "window": board.rank_window,
                        **_also(board, pair.coin),
                    },
                    include_source=include_source,
                    host=host,
                    series=_chart_series(board, pair.coin),
                )
            )
        dumped = _run(ser.points, load=False)
        if dumped:
            a, last, delta, hours = dumped
            out.append(
                _story(
                    kind="dump",
                    board=board,
                    score=delta * 90 + hours,
                    key=f"dump:{board.ranker}:{pair.coin}:{cycle[:13]}",
                    chart="hold",
                    focus=pair.coin,
                    pair=pair,
                    facts={
                        "label": pair.label,
                        "dex": pair.dex,
                        "side": last.side,
                        "from_pct": round(a.hold_pct * 100, 1),
                        "to_pct": round(last.hold_pct * 100, 1),
                        "pp": round(delta * 100, 1),
                        "hours": int(round(hours)),
                        "start": _utc_hour(a.ts),
                        "listed": listed,
                        "window": board.rank_window,
                        **_also(board, pair.coin),
                    },
                    include_source=include_source,
                    host=host,
                    series=_chart_series(board, pair.coin),
                )
            )
        last_pt = ser.points[-1]
        for prev in reversed(ser.points[:-1]):
            if prev.side == last_pt.side:
                continue
            ago = (last_pt.ts - prev.ts).total_seconds() / 3600.0
            if 0.5 <= ago <= 12:
                out.append(
                    _story(
                        kind="flip",
                        board=board,
                        score=8.0 + pair.hold_pct * 20,
                        key=f"flip:{board.ranker}:{pair.coin}:{cycle[:13]}",
                        chart="hold",
                        focus=pair.coin,
                        pair=pair,
                        facts={
                            "label": pair.label,
                            "dex": pair.dex,
                            "from_side": prev.side,
                            "to_side": last_pt.side,
                            "hold_pct": round(pair.hold_pct * 100, 1),
                            "listed": listed,
                            "window": board.rank_window,
                            "when": _utc_hour(last_pt.ts),
                        },
                        include_source=include_source,
                        host=host,
                        series=_chart_series(board, pair.coin),
                    )
                )
            break

    movers = [p for p in board.rows if p.hold_delta is not None]
    inflows = sorted(
        (p for p in movers if (p.hold_delta or 0) >= HOUR_MOVE_MIN),
        key=lambda p: -(p.hold_delta or 0),
    )
    outflows = sorted(
        (p for p in movers if (p.hold_delta or 0) <= -HOUR_MOVE_MIN),
        key=lambda p: (p.hold_delta or 0),
    )
    if inflows:
        p = inflows[0]
        out.append(
            _story(
                kind="inflow",
                board=board,
                score=abs(p.hold_delta or 0) * 80,
                key=f"in:{board.ranker}:{p.coin}:{cycle[:13]}",
                chart="movers",
                focus=p.coin,
                pair=p,
                facts={
                    "label": p.label,
                    "dex": p.dex,
                    "side": p.side,
                    "pp": round((p.hold_delta or 0) * 100, 1),
                    "hold_pct": round(p.hold_pct * 100, 1),
                    "listed": listed,
                    "window": board.rank_window,
                    "chg_pct": None if p.change_pct is None else round(p.change_pct * 100, 2),
                },
                include_source=include_source,
                host=host,
            )
        )
    if outflows:
        p = outflows[0]
        out.append(
            _story(
                kind="outflow",
                board=board,
                score=abs(p.hold_delta or 0) * 75,
                key=f"out:{board.ranker}:{p.coin}:{cycle[:13]}",
                chart="movers",
                focus=p.coin,
                pair=p,
                facts={
                    "label": p.label,
                    "dex": p.dex,
                    "side": p.side,
                    "pp": round(abs(p.hold_delta or 0) * 100, 1),
                    "hold_pct": round(p.hold_pct * 100, 1),
                    "listed": listed,
                    "window": board.rank_window,
                    "chg_pct": None if p.change_pct is None else round(p.change_pct * 100, 2),
                },
                include_source=include_source,
                host=host,
            )
        )

    top = board.rows[0]
    if top.hold_pct >= DOMINATE_MIN:
        out.append(
            _story(
                kind="dominate",
                board=board,
                score=top.hold_pct * 40,
                key=f"top:{board.ranker}:{top.coin}:{cycle[:13]}",
                chart="heatmap",
                focus=top.coin,
                pair=top,
                facts={
                    "label": top.label,
                    "dex": top.dex,
                    "side": top.side,
                    "hold_pct": round(top.hold_pct * 100, 1),
                    "wallets": top.wallets,
                    "listed": listed,
                    "window": board.rank_window,
                    "agree": round(top.agreement * 100),
                },
                include_source=include_source,
                host=host,
            )
        )

    if inflows or outflows:
        inn = inflows[0] if inflows else None
        outp = outflows[0] if outflows else None
        facts = {
            "top_label": top.label,
            "top_dex": top.dex,
            "top_side": top.side,
            "top_pct": round(top.hold_pct * 100, 1),
            "listed": listed,
            "window": board.rank_window,
            "in_label": None if inn is None else inn.label,
            "in_pp": None if inn is None else round((inn.hold_delta or 0) * 100, 1),
            "out_label": None if outp is None else outp.label,
            "out_pp": None if outp is None else round(abs(outp.hold_delta or 0) * 100, 1),
        }
        out.append(
            _story(
                kind="digest",
                board=board,
                score=6.0 + top.hold_pct * 10,
                key=f"digest:{board.ranker}:{cycle[:13]}",
                chart="heatmap" if random.random() < 0.45 else "movers",
                focus=top.coin,
                pair=top,
                facts=facts,
                include_source=include_source,
                host=host,
            )
        )

    rank_facts = {
        "listed": listed,
        "window": board.rank_window,
        "hour": None if not board.cycle_ts else _utc_hour(board.cycle_ts),
        "rows": [
            {
                "rank": p.rank,
                "label": p.label,
                "dex": p.dex,
                "side": p.side,
                "hold_pct": round(p.hold_pct * 100, 1),
                "wallets": p.wallets,
            }
            for p in board.rows[:5]
        ],
    }
    out.append(
        _story(
            kind="ranks",
            board=board,
            score=3.5,
            key=f"ranks:{board.ranker}:{cycle[:13]}",
            chart="heatmap",
            focus=top.coin,
            pair=top,
            facts=rank_facts,
            include_source=include_source,
            host=host,
        )
    )
    return out


def _kind_chart(kind: str) -> str:
    if kind in {"inflow", "outflow"}:
        return "movers"
    if kind in {"dominate", "ranks", "digest"}:
        return "heatmap"
    return "hold"


def pick_story(
    board: Board,
    host: str,
    include_source: bool,
    recent_keys: Iterable[str],
    recent_kinds: Iterable[str] = (),
) -> Story | None:
    recent = set(recent_keys)
    stories = collect_stories(board, host, include_source)
    fresh = [s for s in stories if s.key not in recent]
    pool = fresh or stories
    if not pool:
        return None
    # The biggest 18h move always outscores the map, so every post was the
    # same green area chart. Never repeat the previous chart type when
    # another type exists.
    last = next(iter(recent_kinds), "")
    last_chart = _kind_chart(last) if last else ""
    if last_chart:
        other = [s for s in pool if s.chart != last_chart]
        if other:
            pool = other
    pool.sort(key=lambda s: -s.score)
    top = pool[: min(4, len(pool))]
    weights = [max(0.2, s.score) for s in top]
    return random.choices(top, weights=weights, k=1)[0]
