from __future__ import annotations

import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from .config import Settings
from .copy import strip_urls

log = logging.getLogger("promoter")


def make_client(cfg: Settings):
    import tweepy

    return tweepy.Client(
        consumer_key=cfg.x_api_key,
        consumer_secret=cfg.x_api_secret,
        access_token=cfg.x_access_token,
        access_token_secret=cfg.x_access_token_secret,
        wait_on_rate_limit=False,
    )


def make_search_client(cfg: Settings):
    """Recent search is app-only. User-context OAuth 1.0a can post and still 401 on search."""
    import tweepy

    if cfg.x_bearer:
        return tweepy.Client(bearer_token=cfg.x_bearer, wait_on_rate_limit=False)
    return make_client(cfg)


def make_api(cfg: Settings):
    import tweepy

    auth = tweepy.OAuth1UserHandler(
        cfg.x_api_key,
        cfg.x_api_secret,
        cfg.x_access_token,
        cfg.x_access_token_secret,
    )
    return tweepy.API(auth, timeout=30)


def search_recent(client, query: str) -> tuple[list[Any], dict[str, Any]]:
    resp = client.search_recent_tweets(
        query=query,
        max_results=10,
        tweet_fields=["created_at", "public_metrics", "lang", "entities", "author_id"],
        expansions=["author_id"],
        user_fields=[
            "created_at",
            "username",
            "name",
            "description",
            "public_metrics",
            "verified",
            "protected",
        ],
    )
    tweets = list(getattr(resp, "data", None) or [])
    users: dict[str, Any] = {}
    includes = getattr(resp, "includes", None) or {}
    raw_users = includes.get("users") if hasattr(includes, "get") else None
    if raw_users is None and isinstance(includes, dict):
        raw_users = includes.get("users")
    for user in raw_users or []:
        if getattr(user, "protected", False):
            continue
        users[str(user.id)] = user
    return tweets, users


def post_tweet(cfg: Settings, text: str, png: bytes, alt: str) -> str | None:
    """One upload and one post. A retry would be another paid X call."""
    if cfg.dry_run or not cfg.has_x():
        return None
    api = make_api(cfg)
    client = make_client(cfg)
    path = None
    try:
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        Path(path).write_bytes(png)
        media = api.media_upload(filename=path)
        resp = client.create_tweet(text=strip_urls(text), media_ids=[str(media.media_id)])
        data = getattr(resp, "data", None) or {}
        tweet_id = str(data.get("id") or "")
        if not tweet_id:
            raise RuntimeError(f"X create_tweet returned no id: {resp!r}")
        return tweet_id
    except Exception as exc:
        msg = str(exc).lower()
        if "duplicate" in msg:
            log.warning("X rejected duplicate text")
            return None
        raise
    finally:
        if path:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass


def quote_tweet(cfg: Settings, text: str, tweet_id: str) -> str | None:
    if cfg.dry_run or not cfg.has_x():
        return None
    client = make_client(cfg)
    try:
        resp = client.create_tweet(text=strip_urls(text), quote_tweet_id=str(tweet_id))
        data = getattr(resp, "data", None) or {}
        new_id = str(data.get("id") or "")
        if not new_id:
            raise RuntimeError(f"X quote returned no id: {resp!r}")
        return new_id
    except Exception as exc:
        if "duplicate" in str(exc).lower():
            log.warning("X rejected duplicate quote")
            return None
        raise
