from __future__ import annotations
import hashlib
from datetime import datetime, timezone
from typing import Any


TOMBSTONE_BODIES = {"[deleted]", "[removed]"}


def _ts(epoch: float | None) -> datetime | None:
    if not epoch:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


def _hash(*parts: str | int | float | None) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(str(p).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def normalize_post(api_obj: dict[str, Any]) -> dict[str, Any]:
    """Convert a Reddit `t3` Listing child .data into our `posts` row shape."""
    d = api_obj
    deleted = (d.get("selftext") in TOMBSTONE_BODIES) or d.get("author") == "[deleted]"
    return {
        "id": d.get("name") or f"t3_{d['id']}",
        "subreddit": (d.get("subreddit") or "").lower(),
        "author_id": d.get("author_fullname"),
        "author_username": d.get("author"),
        "title": d.get("title") or "",
        "selftext": d.get("selftext") or "",
        "url": d.get("url"),
        "permalink": d.get("permalink"),
        "domain": d.get("domain"),
        "is_self": d.get("is_self"),
        "over18": d.get("over_18"),
        "spoiler": d.get("spoiler"),
        "stickied": d.get("stickied"),
        "locked": d.get("locked"),
        "removed": bool(d.get("removed_by_category")) or deleted,
        "score": d.get("score"),
        "upvote_ratio": d.get("upvote_ratio"),
        "num_comments": d.get("num_comments"),
        "created_utc": _ts(d.get("created_utc")),
        "edited_utc": _ts(d.get("edited")) if isinstance(d.get("edited"), (int, float)) else None,
        "deleted_at": datetime.now(tz=timezone.utc) if deleted else None,
        "content_hash": _hash(d.get("title"), d.get("selftext"), d.get("url"), d.get("score")),
    }


def normalize_comment(api_obj: dict[str, Any], depth: int = 0) -> dict[str, Any]:
    d = api_obj
    deleted = (d.get("body") in TOMBSTONE_BODIES) or d.get("author") == "[deleted]"
    return {
        "id": d.get("name") or f"t1_{d['id']}",
        "post_id": d.get("link_id"),
        "parent_id": d.get("parent_id"),
        "subreddit": (d.get("subreddit") or "").lower(),
        "author_id": d.get("author_fullname"),
        "author_username": d.get("author"),
        "body": d.get("body") or "",
        "score": d.get("score"),
        "depth": d.get("depth", depth),
        "removed": bool(d.get("removed")) or deleted,
        "created_utc": _ts(d.get("created_utc")),
        "edited_utc": _ts(d.get("edited")) if isinstance(d.get("edited"), (int, float)) else None,
        "deleted_at": datetime.now(tz=timezone.utc) if deleted else None,
        "content_hash": _hash(d.get("body"), d.get("score")),
    }


def flatten_comment_tree(listing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Walk a Reddit comment listing (already JSON) into a flat list of normalized rows.

    Reddit returns:  [post_listing, comments_listing]
                     comments_listing.data.children = [{kind: 't1', data: {... replies: ...}}, ...]
    `replies` is either "" or another listing.
    """
    out: list[dict[str, Any]] = []

    def walk(children: list[dict[str, Any]], depth: int) -> None:
        for c in children:
            kind = c.get("kind")
            if kind == "more":
                # 'more' nodes signal omitted comments; fetch separately via /api/morechildren
                # if you need them. We skip silently here and surface a metric upstream.
                continue
            if kind != "t1":
                continue
            data = c.get("data") or {}
            row = normalize_comment(data, depth=depth)
            out.append(row)
            replies = data.get("replies")
            if isinstance(replies, dict):
                walk((replies.get("data") or {}).get("children", []), depth + 1)

    if len(listing) >= 2:
        walk(((listing[1].get("data") or {}).get("children") or []), 0)
    return out
