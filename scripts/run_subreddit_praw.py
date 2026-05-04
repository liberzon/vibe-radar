"""Synchronous PRAW alternative — simpler, less control.

PRAW handles OAuth and rate-limit waiting for you. It honors the same
100 QPM limit and respects User-Agent. It does NOT bypass anything.

Usage:
    python -m scripts.run_subreddit_praw --subreddit <name> --limit 25
"""
from __future__ import annotations
import argparse
import os
import praw  # type: ignore[import-untyped]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--subreddit", required=True)
    p.add_argument("--limit", type=int, default=25)
    args = p.parse_args()

    reddit = praw.Reddit(
        client_id=os.environ["REDDIT_CLIENT_ID"],
        client_secret=os.environ["REDDIT_CLIENT_SECRET"],
        user_agent=os.environ["REDDIT_USER_AGENT"],
        username=os.environ.get("REDDIT_USERNAME"),
        password=os.environ.get("REDDIT_PASSWORD"),
        check_for_updates=False,
        ratelimit_seconds=300,        # PRAW will sleep up to 5 min for ratelimit
    )
    reddit.read_only = not (os.environ.get("REDDIT_USERNAME") and os.environ.get("REDDIT_PASSWORD"))

    sub = reddit.subreddit(args.subreddit)
    for post in sub.new(limit=args.limit):
        print(f"{post.fullname}\t{post.score}\t{post.title[:80]}")
        # post.comments.replace_more(limit=0) drops 'more' nodes; do NOT call with limit=None on huge threads.
        post.comments.replace_more(limit=0)
        for c in post.comments.list()[:10]:
            print(f"  {c.fullname}\t{c.score}\t{(c.body or '')[:80]}")


if __name__ == "__main__":
    main()
