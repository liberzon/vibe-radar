"""Unified CLI for vibe-radar.

Usage:
    vibe-radar collect              # one tick of every source in config/sources.yaml
    vibe-radar collect --reddit-only
    vibe-radar collect --hn-only
    vibe-radar extract              # run claude-CLI extraction on unprocessed docs
    vibe-radar cluster              # rebuild themes from current corpus
    vibe-radar status               # quick health/volume summary
"""
from __future__ import annotations
import argparse
import asyncio
import logging
import os
import sys
import structlog


def _logging() -> None:
    level = os.environ.get("LOG_LEVEL", "INFO")
    logging.basicConfig(level=level, format="%(message)s", stream=sys.stdout)
    structlog.configure(processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ])


def _collect(args: argparse.Namespace) -> int:
    from .commands import collect
    _logging()
    asyncio.run(collect.run(
        config_path=args.config or "config/sources.yaml",
        reddit_only=args.reddit_only,
        hn_only=args.hn_only,
    ))
    return 0


def _extract(args: argparse.Namespace) -> int:
    from .commands import extract
    _logging()
    asyncio.run(extract.run(
        limit=args.limit, source=args.source, since=args.since,
        model=args.model, concurrency=args.concurrency,
    ))
    return 0


def _cluster(args: argparse.Namespace) -> int:
    from .commands import cluster
    _logging()
    asyncio.run(cluster.run(
        days=args.days, min_cluster_size=args.min_cluster_size,
        max_clusters=args.max_clusters, label=not args.no_label,
        label_model=args.label_model,
    ))
    return 0


def _status(args: argparse.Namespace) -> int:
    from .commands import status
    asyncio.run(status.run())
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="vibe-radar")
    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("collect", help="ingest one tick of every configured source")
    pc.add_argument("--config", default=None)
    pc.add_argument("--reddit-only", action="store_true")
    pc.add_argument("--hn-only", action="store_true")
    pc.set_defaults(fn=_collect)

    pe = sub.add_parser("extract", help="run claude-CLI extraction over unprocessed documents")
    pe.add_argument("--limit", type=int, default=50)
    pe.add_argument("--source", default=None)
    pe.add_argument("--since", default=None)
    pe.add_argument("--model", default="haiku")
    pe.add_argument("--concurrency", type=int, default=2)
    pe.set_defaults(fn=_extract)

    pcl = sub.add_parser("cluster", help="cluster recent documents into themes")
    pcl.add_argument("--days", type=int, default=30)
    pcl.add_argument("--min-cluster-size", type=int, default=5)
    pcl.add_argument("--max-clusters", type=int, default=40)
    pcl.add_argument("--no-label", action="store_true")
    pcl.add_argument("--label-model", default="haiku")
    pcl.set_defaults(fn=_cluster)

    ps = sub.add_parser("status", help="quick volume + health summary")
    ps.set_defaults(fn=_status)

    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
