"""Read the same Neon tables the website uses. Two queries per ranker, then close."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .models import Board, HistPoint, Pair, Ranker, Series, Side

log = logging.getLogger("promoter")

VENUE_DEFAULT = "hyperliquid"

BOARD_SQL = """
WITH latest AS (
    SELECT cycle_ts, listed, snapped_ok, status, finished_at, coverage
    FROM collector_runs
    WHERE venue = %(venue)s
      AND status IN ('ok', 'partial')
    ORDER BY cycle_ts DESC
    LIMIT 1
),
prev_cycle AS (
    SELECT cycle_ts
    FROM collector_runs
    WHERE venue = %(venue)s
      AND status IN ('ok', 'partial')
      AND cycle_ts < (SELECT cycle_ts FROM latest)
    ORDER BY cycle_ts DESC
    LIMIT 1
)
SELECT
    l.cycle_ts,
    l.listed,
    l.snapped_ok,
    l.status,
    l.finished_at,
    l.coverage,
    m.coin,
    m.side,
    m.wallets,
    m.hold_pct,
    m.agreement,
    m.long_n,
    m.short_n,
    m.median_leverage,
    m.rank,
    p.rank AS prev_rank,
    p.hold_pct AS prev_hold_pct,
    p.long_n AS prev_long_n,
    p.short_n AS prev_short_n,
    (SELECT snapped_ok FROM collector_runs
      WHERE venue = %(venue)s
        AND cycle_ts = (SELECT cycle_ts FROM prev_cycle)
      LIMIT 1) AS prev_snapped_ok,
    cp.mark_px,
    cp.ohlc_close,
    cp.ohlc_open,
    cpp.mark_px AS prev_mark_px,
    cpp.ohlc_close AS prev_ohlc_close
FROM latest l
LEFT JOIN meta_index m
  ON m.cycle_ts = l.cycle_ts
 AND m.venue = %(venue)s
LEFT JOIN meta_index p
  ON p.cycle_ts = (SELECT cycle_ts FROM prev_cycle)
 AND p.venue = %(venue)s
 AND p.coin = m.coin
LEFT JOIN coin_prices cp
  ON cp.cycle_ts = l.cycle_ts
 AND cp.venue = %(venue)s
 AND cp.coin = m.coin
LEFT JOIN coin_prices cpp
  ON cpp.cycle_ts = (SELECT cycle_ts FROM prev_cycle)
 AND cpp.venue = %(venue)s
 AND cpp.coin = m.coin
ORDER BY m.rank ASC NULLS LAST
"""

# Latest top-15 coins across last 24 hours — enough for load/dump + chart.
HIST_SQL = """
WITH hours AS (
    SELECT cycle_ts, snapped_ok
    FROM collector_runs
    WHERE venue = %(venue)s
      AND status IN ('ok', 'partial')
    ORDER BY cycle_ts DESC
    LIMIT 24
),
latest AS (
    SELECT MAX(cycle_ts) AS cycle_ts FROM hours
),
watch AS (
    SELECT coin
    FROM meta_index
    WHERE venue = %(venue)s
      AND cycle_ts = (SELECT cycle_ts FROM latest)
      AND rank <= 15
)
SELECT
    h.cycle_ts,
    h.snapped_ok,
    m.coin,
    m.side,
    m.rank,
    m.hold_pct,
    m.wallets,
    m.long_n,
    m.short_n
FROM hours h
INNER JOIN meta_index m
  ON m.cycle_ts = h.cycle_ts
 AND m.venue = %(venue)s
INNER JOIN watch w ON w.coin = m.coin
ORDER BY h.cycle_ts ASC, m.rank ASC
"""


def _n(value: Any, fallback: float = 0.0) -> float:
    if value is None or value == "":
        return fallback
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _n_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if n == n else None


def _i_or_none(value: Any) -> int | None:
    n = _n_or_none(value)
    return None if n is None else int(round(n))


def _ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return None


def stamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def split_coin(coin: str) -> tuple[str, str]:
    if ":" in coin:
        dex, label = coin.split(":", 1)
        return label, dex
    return coin, ""


def connect(dsn: str) -> psycopg.Connection:
    return psycopg.connect(dsn, row_factory=dict_row, autocommit=True)


def fetch_board_rows(conn: psycopg.Connection, venue: str) -> list[dict[str, Any]]:
    return list(conn.execute(BOARD_SQL, {"venue": venue}))


def fetch_hist_rows(conn: psycopg.Connection, venue: str) -> list[dict[str, Any]]:
    return list(conn.execute(HIST_SQL, {"venue": venue}))


def _px(row: dict[str, Any]) -> float | None:
    mark = _n_or_none(row.get("mark_px"))
    close = _n_or_none(row.get("ohlc_close"))
    if mark is not None and mark > 0:
        return mark
    if close is not None and close > 0:
        return close
    return None


def _chg(price: float | None, prev: float | None, open_px: float | None) -> float | None:
    if price is None:
        return None
    if prev is not None and prev > 0:
        return (price - prev) / prev
    if open_px is not None and open_px > 0:
        return (price - open_px) / open_px
    return None


def pair_from_row(row: dict[str, Any]) -> Pair | None:
    coin = str(row.get("coin") or "").strip()
    side_raw = str(row.get("side") or "")
    if not coin or side_raw not in {"long", "short"}:
        return None
    label, dex = split_coin(coin)
    hold = _n(row.get("hold_pct"))
    prev_hold = _n_or_none(row.get("prev_hold_pct"))
    long_n = int(round(_n(row.get("long_n"))))
    short_n = int(round(_n(row.get("short_n"))))
    price = _px(row)
    prev_price = None
    prev_mark = _n_or_none(row.get("prev_mark_px"))
    prev_close = _n_or_none(row.get("prev_ohlc_close"))
    if prev_mark is not None and prev_mark > 0:
        prev_price = prev_mark
    elif prev_close is not None and prev_close > 0:
        prev_price = prev_close
    prev_rank = row.get("prev_rank")
    rank = int(round(_n(row.get("rank"))))
    return Pair(
        rank=rank,
        coin=coin,
        label=label,
        dex=dex,
        side=side_raw,  # type: ignore[arg-type]
        wallets=int(round(_n(row.get("wallets")))),
        on_coin=long_n + short_n,
        long_n=long_n,
        short_n=short_n,
        hold_pct=hold,
        agreement=_n(row.get("agreement")),
        leverage=max(1, int(round(_n(row.get("median_leverage"), 1)))),
        rank_delta=None if prev_rank is None else int(round(_n(prev_rank))) - rank,
        prev_hold_pct=prev_hold,
        prev_long_n=_i_or_none(row.get("prev_long_n")),
        prev_short_n=_i_or_none(row.get("prev_short_n")),
        hold_delta=None if prev_hold is None else hold - prev_hold,
        price=price,
        change_pct=_chg(price, prev_price, _n_or_none(row.get("ohlc_open"))),
    )


def series_from_hist(rows: list[dict[str, Any]]) -> tuple[list[datetime], list[Series]]:
    hour_map: dict[float, datetime] = {}
    by_coin: dict[str, list[HistPoint]] = {}
    for row in rows:
        ts = _ts(row.get("cycle_ts"))
        if ts is None:
            continue
        coin = str(row.get("coin") or "")
        if not coin:
            continue
        hour_map[ts.timestamp()] = ts
        side_raw = str(row.get("side") or "long")
        side: Side = "short" if side_raw == "short" else "long"
        by_coin.setdefault(coin, []).append(
            HistPoint(
                ts=ts,
                stamp=stamp(ts) or "",
                rank=max(1, int(round(_n(row.get("rank"), 99)))),
                side=side,
                hold_pct=_n(row.get("hold_pct")),
                wallets=int(round(_n(row.get("wallets")))),
                snapped_ok=max(0, int(round(_n(row.get("snapped_ok"))))),
            )
        )
    hours = [hour_map[k] for k in sorted(hour_map)]
    last_ts = hours[-1] if hours else None
    series: list[Series] = []
    for coin, points in by_coin.items():
        ordered = sorted(points, key=lambda p: p.ts)
        last = ordered[-1]
        if last_ts is not None:
            for p in reversed(ordered):
                if p.ts == last_ts:
                    last = p
                    break
        label, dex = split_coin(coin)
        series.append(
            Series(
                coin=coin,
                label=label,
                dex=dex,
                latest_rank=last.rank,
                points=ordered,
            )
        )
    series.sort(key=lambda s: s.latest_rank)
    return hours, series


def board_from_rows(ranker: Ranker, rows: list[dict[str, Any]], hist: list[dict[str, Any]]) -> Board:
    if not rows:
        return Board(
            ranker=ranker,
            configured=True,
            error="No snapshot in Neon yet",
            cycle_ts=None,
            cycle_stamp=None,
            captured_at=None,
            listed=200,
            snapped_ok=0,
            prev_snapped_ok=None,
            status=None,
            coverage=None,
            rank_window="7-day PnL" if ranker == "pnl" else "7-day ROI",
            rows=[],
            hours=[],
            series=[],
        )
    head = rows[0]
    pairs = [p for p in (pair_from_row(r) for r in rows) if p]
    hours, series = series_from_hist(hist)
    cycle = _ts(head.get("cycle_ts"))
    finished = _ts(head.get("finished_at"))
    cov = _n_or_none(head.get("coverage"))
    window = {
        "pnl": "7-day PnL",
        "roi": "7-day ROI",
        "both": "7-day PnL + ROI",
    }[ranker]
    return Board(
        ranker=ranker,
        configured=True,
        error=None,
        cycle_ts=cycle,
        cycle_stamp=stamp(cycle),
        captured_at=stamp(finished) or stamp(cycle),
        listed=max(1, int(round(_n(head.get("listed"), 200)))),
        snapped_ok=max(0, int(round(_n(head.get("snapped_ok"))))),
        prev_snapped_ok=_i_or_none(head.get("prev_snapped_ok")),
        status=str(head.get("status") or "") or None,
        coverage=cov,
        rank_window=window,
        rows=pairs,
        hours=hours,
        series=series,
    )


def load_ranker(dsn: str, ranker: Ranker, venue: str) -> Board:
    with connect(dsn) as conn:
        board_rows = fetch_board_rows(conn, venue)
        hist_rows = fetch_hist_rows(conn, venue)
    log.info(
        "Neon %s board_rows=%s hist_rows=%s",
        ranker,
        len(board_rows),
        len(hist_rows),
    )
    return board_from_rows(ranker, board_rows, hist_rows)


def _votes(n: int | None) -> int:
    return 0 if n is None else max(0, n)


def _majority(long_n: int, short_n: int) -> tuple[Side, int]:
    if short_n > long_n:
        return "short", short_n
    return "long", max(0, long_n)


def _add_pair(pnl: Pair | None, roi: Pair | None, denom: int, prev_denom: int) -> Pair | None:
    src = pnl or roi
    if src is None:
        return None
    long_n = _votes(pnl.long_n if pnl else 0) + _votes(roi.long_n if roi else 0)
    short_n = _votes(pnl.short_n if pnl else 0) + _votes(roi.short_n if roi else 0)
    if long_n + short_n <= 0:
        return None
    side, wallets = _majority(long_n, short_n)
    on_coin = long_n + short_n
    hold = wallets / denom if denom > 0 else 0.0
    had_prev = any(
        x is not None
        for x in (
            None if pnl is None else pnl.prev_long_n,
            None if pnl is None else pnl.prev_short_n,
            None if roi is None else roi.prev_long_n,
            None if roi is None else roi.prev_short_n,
        )
    )
    prev_long = _votes(None if pnl is None else pnl.prev_long_n) + _votes(
        None if roi is None else roi.prev_long_n
    )
    prev_short = _votes(None if pnl is None else pnl.prev_short_n) + _votes(
        None if roi is None else roi.prev_short_n
    )
    prev_hold = (
        _majority(prev_long, prev_short)[1] / prev_denom
        if had_prev and prev_denom > 0
        else None
    )
    pnl_w = _votes(None if pnl is None else pnl.on_coin)
    roi_w = _votes(None if roi is None else roi.on_coin)
    lev_w = pnl_w + roi_w
    leverage = src.leverage
    if lev_w > 0:
        leverage = max(
            1,
            round(
                ((pnl.leverage if pnl else 0) * pnl_w + (roi.leverage if roi else 0) * roi_w)
                / lev_w
            ),
        )
    priced = pnl if pnl_w >= roi_w else roi
    if priced is None:
        priced = src
    return Pair(
        rank=0,
        coin=src.coin,
        label=src.label,
        dex=src.dex,
        side=side,
        wallets=wallets,
        on_coin=on_coin,
        long_n=long_n,
        short_n=short_n,
        hold_pct=hold,
        agreement=wallets / on_coin if on_coin else 0.0,
        leverage=leverage,
        rank_delta=None,
        prev_hold_pct=prev_hold,
        prev_long_n=prev_long if had_prev else None,
        prev_short_n=prev_short if had_prev else None,
        hold_delta=None if prev_hold is None else hold - prev_hold,
        price=priced.price,
        change_pct=priced.change_pct,
    )


def _hour_bucket(ts: datetime) -> int:
    return int(ts.timestamp() // 3600)


def combine_boards(pnl: Board, roi: Board) -> Board:
    if pnl.error and not pnl.rows:
        return Board(
            ranker="both",
            configured=pnl.configured,
            error=f"PnL: {pnl.error}",
            cycle_ts=None,
            cycle_stamp=None,
            captured_at=None,
            listed=400,
            snapped_ok=0,
            prev_snapped_ok=None,
            status=None,
            coverage=None,
            rank_window="7-day PnL + ROI",
            rows=[],
            hours=[],
            series=[],
        )
    if roi.error and not roi.rows:
        return Board(
            ranker="both",
            configured=roi.configured,
            error=f"ROI: {roi.error}",
            cycle_ts=None,
            cycle_stamp=None,
            captured_at=None,
            listed=400,
            snapped_ok=0,
            prev_snapped_ok=None,
            status=None,
            coverage=None,
            rank_window="7-day PnL + ROI",
            rows=[],
            hours=[],
            series=[],
        )
    denom = max(0, pnl.snapped_ok) + max(0, roi.snapped_ok)
    prev_denom = (pnl.prev_snapped_ok or 0) + (roi.prev_snapped_ok or 0)
    pnl_by = {p.coin: p for p in pnl.rows}
    roi_by = {p.coin: p for p in roi.rows}
    merged: list[Pair] = []
    for coin in set(pnl_by) | set(roi_by):
        row = _add_pair(pnl_by.get(coin), roi_by.get(coin), denom, prev_denom)
        if row:
            merged.append(row)
    merged.sort(key=lambda r: (-r.wallets, -r.hold_pct, r.coin))
    prev_order = [r for r in merged if r.prev_hold_pct is not None]
    prev_order.sort(key=lambda r: (-(r.prev_hold_pct or 0), r.coin))
    prev_rank = {r.coin: i + 1 for i, r in enumerate(prev_order)}
    for i, row in enumerate(merged, start=1):
        row.rank = i
        prev = prev_rank.get(row.coin)
        row.rank_delta = None if prev is None else prev - row.rank

    # Combine 24h series for the merged top 5 — in memory, no extra SQL.
    top_coins = [r.coin for r in merged[:5]]
    pnl_s = {s.coin: s for s in pnl.series}
    roi_s = {s.coin: s for s in roi.series}

    def by_bucket(series: Series | None) -> dict[int, HistPoint]:
        if series is None:
            return {}
        return {_hour_bucket(p.ts): p for p in series.points}

    def snapped_map(board: Board) -> dict[int, int]:
        out: dict[int, int] = {}
        for s in board.series:
            for p in s.points:
                b = _hour_bucket(p.ts)
                if p.snapped_ok:
                    out[b] = max(out.get(b, 0), p.snapped_ok)
        return out

    pnl_snap = snapped_map(pnl)
    roi_snap = snapped_map(roi)
    buckets = sorted(set(pnl_snap) | set(roi_snap))
    hours_out: list[datetime] = []
    points_by: dict[str, list[HistPoint]] = {c: [] for c in top_coins}
    pnl_idx = {c: by_bucket(pnl_s.get(c)) for c in top_coins}
    roi_idx = {c: by_bucket(roi_s.get(c)) for c in top_coins}

    for b in buckets:
        denom_h = pnl_snap.get(b, 0) + roi_snap.get(b, 0)
        if denom_h <= 0:
            continue
        hour_pts: list[tuple[str, HistPoint]] = []
        ts = None
        stamp_s = ""
        for coin in top_coins:
            long_n = 0
            short_n = 0
            for idx in (pnl_idx[coin], roi_idx[coin]):
                pt = idx.get(b)
                if pt is None:
                    continue
                ts = pt.ts if ts is None or pt.ts > ts else ts
                stamp_s = pt.stamp or stamp_s
                if pt.side == "short":
                    short_n += pt.wallets
                else:
                    long_n += pt.wallets
            if long_n + short_n <= 0:
                continue
            side, wallets = _majority(long_n, short_n)
            hour_pts.append(
                (
                    coin,
                    HistPoint(
                        ts=ts or datetime.fromtimestamp(b * 3600, tz=timezone.utc),
                        stamp=stamp_s or stamp(ts) or "",
                        rank=0,
                        side=side,
                        hold_pct=wallets / denom_h,
                        wallets=wallets,
                        snapped_ok=denom_h,
                    ),
                )
            )
        if not hour_pts or ts is None:
            continue
        hours_out.append(ts)
        hour_pts.sort(key=lambda x: -x[1].wallets)
        for i, (coin, pt) in enumerate(hour_pts, start=1):
            pt.rank = i
            points_by.setdefault(coin, []).append(pt)

    series_out: list[Series] = []
    for i, coin in enumerate(top_coins, start=1):
        pts = points_by.get(coin) or []
        if not pts:
            continue
        label, dex = split_coin(coin)
        series_out.append(
            Series(coin=coin, label=label, dex=dex, latest_rank=i, points=pts)
        )

    captured = sorted(
        t for t in (pnl.captured_at, roi.captured_at) if t
    )
    coverage = None
    if pnl.coverage is not None and roi.coverage is not None and denom > 0:
        coverage = (pnl.coverage * pnl.snapped_ok + roi.coverage * roi.snapped_ok) / denom
    else:
        coverage = pnl.coverage if pnl.coverage is not None else roi.coverage

    status = "ok" if pnl.status == "ok" and roi.status == "ok" else (pnl.status or roi.status)
    return Board(
        ranker="both",
        configured=True,
        error=None if merged else "No pairs on the PnL or ROI board this hour",
        cycle_ts=pnl.cycle_ts or roi.cycle_ts,
        cycle_stamp=pnl.cycle_stamp or roi.cycle_stamp,
        captured_at=captured[-1] if captured else None,
        listed=max(1, pnl.listed) + max(1, roi.listed),
        snapped_ok=denom,
        prev_snapped_ok=prev_denom if prev_denom > 0 else None,
        status=status,
        coverage=coverage,
        rank_window="7-day PnL + ROI",
        rows=merged,
        hours=hours_out,
        series=series_out,
    )


def load_board(pnl_url: str, roi_url: str, ranker: Ranker, venue: str) -> Board:
    if ranker == "both":
        if not roi_url:
            raise RuntimeError("ROI database URL is required for PnL+ROI posts")
        pnl = load_ranker(pnl_url, "pnl", venue)
        roi = load_ranker(roi_url, "roi", venue)
        return combine_boards(pnl, roi)
    url = roi_url if ranker == "roi" else pnl_url
    if not url:
        raise RuntimeError(f"No database URL for {ranker}")
    return load_ranker(url, ranker, venue)


STATE_DDL = """
CREATE TABLE IF NOT EXISTS bagrank_promoter_state (
    id integer PRIMARY KEY CHECK (id = 1),
    payload jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
)
"""


def load_promoter_state(dsn: str) -> dict[str, Any] | None:
    try:
        with connect(dsn) as conn:
            conn.execute(STATE_DDL)
            row = conn.execute(
                "SELECT payload, updated_at FROM bagrank_promoter_state WHERE id = 1"
            ).fetchone()
    except Exception:
        log.exception("Could not read promoter state from Neon")
        return None
    if not row:
        return None
    payload = row.get("payload")
    if isinstance(payload, str):
        import json

        payload = json.loads(payload)
    if not isinstance(payload, dict):
        return None
    payload["_neon_updated"] = stamp(row.get("updated_at"))
    return payload


def save_promoter_state(dsn: str, payload: dict[str, Any]) -> None:
    import json

    blob = json.dumps(payload, default=str)
    try:
        with connect(dsn) as conn:
            conn.execute(STATE_DDL)
            conn.execute(
                """
                INSERT INTO bagrank_promoter_state (id, payload, updated_at)
                VALUES (1, %s::jsonb, now())
                ON CONFLICT (id) DO UPDATE SET
                    payload = EXCLUDED.payload,
                    updated_at = now()
                """,
                (blob,),
            )
    except Exception:
        log.exception("Could not save promoter state to Neon")

