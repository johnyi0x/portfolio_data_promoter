from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("promoter")


def _atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, separators=(",", ":"), default=str)
    fd, tmp = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class Store:
    """Posted-story memory. File cache plus Neon so Railway restarts don't double-post."""

    def __init__(self, data_dir: Path, neon_dsn: str = "") -> None:
        self.path = data_dir / "promoter_state.json"
        self.neon_dsn = neon_dsn
        self.data: dict[str, Any] = {
            "last_post_at": 0.0,
            "last_interval_s": 0.0,
            "posts": [],
            "claude_day": "",
            "claude_count": 0,
            "post_day": "",
            "post_count": 0,
            "promo_since_quote": 0,
            "quote_fail_streak": 0,
            "quotes_paused_until": 0.0,
            "quoted": [],
            "last_pairs": [],
        }
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self.data.update(raw)
            except (json.JSONDecodeError, OSError):
                log.warning("Could not read %s", self.path)
        if self.neon_dsn:
            from .neon import load_promoter_state

            remote = load_promoter_state(self.neon_dsn)
            if remote:
                # Neon wins — Railway disk is ephemeral.
                remote.pop("_neon_updated", None)
                self.data.update(remote)
                log.info("Loaded promoter state from Neon")

    def save(self) -> None:
        _atomic_write(self.path, self.data)
        if self.neon_dsn:
            from .neon import save_promoter_state

            save_promoter_state(self.neon_dsn, self.data)

    def utc_day(self, now: datetime | None = None) -> str:
        now = now or datetime.now(timezone.utc)
        return now.strftime("%Y-%m-%d")

    def _roll_day(self, now: datetime) -> None:
        day = self.utc_day(now)
        if self.data.get("post_day") != day:
            self.data["post_day"] = day
            self.data["post_count"] = 0
        if self.data.get("claude_day") != day:
            self.data["claude_day"] = day
            self.data["claude_count"] = 0

    def posts_today(self, now: datetime) -> int:
        self._roll_day(now)
        return int(self.data.get("post_count") or 0)

    def claude_today(self, now: datetime) -> int:
        self._roll_day(now)
        return int(self.data.get("claude_count") or 0)

    def last_post_at(self) -> float:
        return float(self.data.get("last_post_at") or 0)

    def promo_since_quote(self) -> int:
        return int(self.data.get("promo_since_quote") or 0)

    def quote_fail_streak(self) -> int:
        return int(self.data.get("quote_fail_streak") or 0)

    def quotes_paused(self) -> bool:
        return time.time() < float(self.data.get("quotes_paused_until") or 0)

    def pause_quotes(self, hours: float) -> None:
        self.data["quotes_paused_until"] = time.time() + hours * 3600
        self.save()

    def want_quote(self, promo_before: int) -> bool:
        if self.quotes_paused():
            return False
        return self.promo_since_quote() >= promo_before

    def recent_keys(self, *, hours: float = 36.0) -> set[str]:
        cutoff = time.time() - hours * 3600
        out: set[str] = set()
        for row in self.data.get("posts") or []:
            if not isinstance(row, dict):
                continue
            if float(row.get("at") or 0) < cutoff:
                continue
            key = str(row.get("key") or "")
            if key:
                out.add(key)
        return out

    def recent_texts(self, n: int = 12) -> list[str]:
        posts = list(self.data.get("posts") or [])
        out: list[str] = []
        for row in reversed(posts[-n:]):
            if isinstance(row, dict) and row.get("text"):
                out.append(str(row["text"]))
        return out

    def last_ranker(self) -> str:
        posts = list(self.data.get("posts") or [])
        for row in reversed(posts):
            if isinstance(row, dict) and row.get("kind") != "quote":
                return str(row.get("ranker") or "")
        return ""

    def last_pairs(self) -> list[dict[str, Any]]:
        raw = self.data.get("last_pairs") or []
        return [row for row in raw if isinstance(row, dict)]

    def set_last_pairs(self, pairs: list[dict[str, Any]], *, persist: bool = False) -> None:
        self.data["last_pairs"] = pairs[:8]
        if persist:
            self.save()

    def quoted_ids(self) -> set[str]:
        out: set[str] = set()
        cutoff = time.time() - 14 * 86400
        for row in self.data.get("quoted") or []:
            if isinstance(row, dict) and float(row.get("at") or 0) >= cutoff:
                tid = str(row.get("tweet_id") or "")
                if tid:
                    out.add(tid)
        return out

    def quoted_authors(self, *, hours: float = 72.0) -> set[str]:
        cutoff = time.time() - hours * 3600
        out: set[str] = set()
        for row in self.data.get("quoted") or []:
            if not isinstance(row, dict):
                continue
            if float(row.get("at") or 0) < cutoff:
                continue
            aid = str(row.get("author_id") or "")
            if aid:
                out.add(aid)
        return out

    def mark_claude(self, now: datetime) -> None:
        self._roll_day(now)
        self.data["claude_count"] = int(self.data.get("claude_count") or 0) + 1
        self.save()

    def mark_quote_fail(self) -> None:
        self.data["quote_fail_streak"] = self.quote_fail_streak() + 1
        if self.quote_fail_streak() >= 2:
            # Don't stall the account if search is empty/blocked.
            self.data["promo_since_quote"] = 0
            self.data["quote_fail_streak"] = 0
            log.info("Quote failed twice — back to board posts")
        self.save()

    def mark_post(
        self,
        *,
        now: datetime,
        key: str,
        ranker: str,
        kind: str,
        text: str,
        used_claude: bool,
        tweet_id: str | None,
        interval_s: float,
        quote_tweet_id: str | None = None,
        quote_author_id: str | None = None,
    ) -> None:
        self._roll_day(now)
        self.data["last_post_at"] = now.timestamp()
        self.data["last_interval_s"] = interval_s
        self.data["post_count"] = int(self.data.get("post_count") or 0) + 1
        if kind == "quote":
            self.data["promo_since_quote"] = 0
            self.data["quote_fail_streak"] = 0
            quoted = list(self.data.get("quoted") or [])
            quoted.append(
                {
                    "at": now.timestamp(),
                    "tweet_id": quote_tweet_id,
                    "author_id": quote_author_id,
                }
            )
            self.data["quoted"] = quoted[-80:]
        else:
            self.data["promo_since_quote"] = self.promo_since_quote() + 1
        posts = list(self.data.get("posts") or [])
        posts.append(
            {
                "at": now.timestamp(),
                "key": key,
                "ranker": ranker,
                "kind": kind,
                "text": text,
                "claude": used_claude,
                "tweet_id": tweet_id,
            }
        )
        self.data["posts"] = posts[-40:]
        self.save()
