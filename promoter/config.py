from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _f(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return float(raw)


def _i(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return int(float(raw))


def _s(name: str, default: str) -> str:
    raw = os.environ.get(name, "").strip()
    return raw if raw else default


def _b(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _url(*names: str) -> str:
    for name in names:
        raw = os.environ.get(name, "").strip()
        if raw:
            return raw
    return ""


@dataclass(frozen=True)
class Settings:
    pnl_url: str
    roi_url: str
    venue: str
    site_url: str
    data_dir: Path
    dry_run: bool
    min_interval_min: float
    max_interval_min: float
    max_posts_per_day: int
    source_rate: float
    anthropic_key: str
    claude_model: str
    claude_rate: float
    claude_max_per_day: int
    x_api_key: str
    x_api_secret: str
    x_access_token: str
    x_access_token_secret: str
    x_bearer: str
    x_user: str
    promo_before_quote: int
    quotes_enabled: bool
    skip_rate: float

    @property
    def site_host(self) -> str:
        return (
            self.site_url.replace("https://", "")
            .replace("http://", "")
            .rstrip("/")
        )

    def neon_url(self, ranker: str) -> str:
        if ranker == "roi":
            return self.roi_url
        return self.pnl_url

    def has_roi(self) -> bool:
        return bool(self.roi_url)

    def has_claude(self) -> bool:
        return bool(self.anthropic_key)

    def has_x(self) -> bool:
        return all(
            (
                self.x_api_key,
                self.x_api_secret,
                self.x_access_token,
                self.x_access_token_secret,
            )
        )


def load_settings() -> Settings:
    pnl = _url(
        "NEON_PNL",
        "DATABASE_URL_PNL",
        "BAGINDEX_DATABASE_URL_PNL",
        "DATABASE_URL",
    )
    if not pnl:
        raise RuntimeError("NEON_PNL is required (PnL Neon URL)")
    data_dir = Path(_s("DATA_DIR", "data"))
    if not data_dir.is_absolute():
        data_dir = Path(__file__).resolve().parent.parent / data_dir
    lo = max(45.0, _f("MIN_INTERVAL_MIN", 110.0))
    hi = max(lo + 10.0, _f("MAX_INTERVAL_MIN", 190.0))
    return Settings(
        pnl_url=pnl,
        roi_url=_url(
            "NEON_BAGRANK",
            "DATABASE_URL_ROI",
            "BAGINDEX_DATABASE_URL_ROI",
        ),
        venue=_s("VENUE", "hyperliquid"),
        site_url=_s("SITE_URL", "https://bagrank.xyz").rstrip("/"),
        data_dir=data_dir,
        dry_run=_b("DRY_RUN", False),
        min_interval_min=lo,
        max_interval_min=hi,
        max_posts_per_day=max(1, _i("MAX_POSTS_PER_DAY", 8)),
        source_rate=min(1.0, max(0.0, _f("SOURCE_RATE", 1.0))),
        anthropic_key=_s("ANTHROPIC_API_KEY", ""),
        claude_model=_s("CLAUDE_MODEL", "claude-haiku-4-5-20251001"),
        claude_rate=min(1.0, max(0.0, _f("CLAUDE_RATE", 0.0))),
        claude_max_per_day=max(0, _i("CLAUDE_MAX_PER_DAY", 0)),
        x_api_key=_s("X_API_KEY", ""),
        x_api_secret=_s("X_API_SECRET", ""),
        x_access_token=_s("X_ACCESS_TOKEN", ""),
        x_access_token_secret=_s("X_ACCESS_TOKEN_SECRET", ""),
        x_bearer=_s("X_BEARER_TOKEN", ""),
        x_user=_s("X_USER", "johnyi0x").lstrip("@").lower(),
        promo_before_quote=max(1, _i("PROMO_BEFORE_QUOTE", 2)),
        quotes_enabled=_b("QUOTES", False),
        skip_rate=min(0.2, max(0.0, _f("SKIP_RATE", 0.08))),
    )
