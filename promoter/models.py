from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

Ranker = Literal["pnl", "roi", "both"]
Side = Literal["long", "short"]
StoryKind = Literal[
    "load",
    "dump",
    "inflow",
    "outflow",
    "dominate",
    "flip",
    "ranks",
    "digest",
]


@dataclass
class Pair:
    rank: int
    coin: str
    label: str
    dex: str
    side: Side
    wallets: int
    on_coin: int
    long_n: int
    short_n: int
    hold_pct: float
    agreement: float
    leverage: int
    rank_delta: int | None
    prev_hold_pct: float | None
    prev_long_n: int | None
    prev_short_n: int | None
    hold_delta: float | None
    price: float | None
    change_pct: float | None


@dataclass
class HistPoint:
    ts: datetime
    stamp: str
    rank: int
    side: Side
    hold_pct: float
    wallets: int
    snapped_ok: int = 0


@dataclass
class Series:
    coin: str
    label: str
    dex: str
    latest_rank: int
    points: list[HistPoint]


@dataclass
class Board:
    ranker: Ranker
    configured: bool
    error: str | None
    cycle_ts: datetime | None
    cycle_stamp: str | None
    captured_at: str | None
    listed: int
    snapped_ok: int
    prev_snapped_ok: int | None
    status: str | None
    coverage: float | None
    rank_window: str
    rows: list[Pair]
    hours: list[datetime]
    series: list[Series]


@dataclass
class Story:
    kind: StoryKind
    ranker: Ranker
    score: float
    key: str
    chart: Literal["hold", "heatmap", "movers"]
    focus_coin: str | None
    pair: Pair | None
    facts: dict
    include_source: bool
    source_line: str
    listed: int
    captured_at: str | None
    cycle_stamp: str | None
    top_rows: list[Pair] = field(default_factory=list)
    chart_series: list[Series] = field(default_factory=list)
    hours: list[datetime] = field(default_factory=list)
