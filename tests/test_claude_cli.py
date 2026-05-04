"""Smoke tests for the claude CLI wrapper.

These tests actually invoke the `claude` binary, so they're slow and require
the user to be logged in. Skipped by default; run with:
    RUN_LIVE_CLAUDE_TESTS=1 pytest tests/test_claude_cli.py -v
"""
import asyncio
import os
import pytest

from analysis.claude_cli import run_extraction


pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_LIVE_CLAUDE_TESTS"),
    reason="live claude CLI test (set RUN_LIVE_CLAUDE_TESTS=1)",
)


def test_extracts_revenue_and_product():
    text = "Just hit $4.2k MRR with my AI summary tool at summify.app! 600 paying users."
    result = asyncio.run(run_extraction(text, model="haiku"))
    assert not result.is_error
    so = result.structured_output
    assert so is not None
    # Should find at least one product and one revenue claim.
    assert any("summify" in (p.get("name") or "").lower() or "summify" in (p.get("homepage") or "")
               for p in so.get("products") or [])
    metrics = {(c.get("metric") or "").lower() for c in so.get("revenue_claims") or []}
    assert "mrr" in metrics or "users" in metrics
