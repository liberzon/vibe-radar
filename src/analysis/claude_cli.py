"""Run extraction by shelling out to the Claude Code CLI.

Why: the user already pays for Claude Code, so CLI calls have no marginal API
cost (they bill against the subscription). Latency is higher than direct SDK
calls (~5-10s/call) and there's a one-time cache-creation cost per ~5min
window, but throughput-wise this is fine for 1000 docs/day.

The CLI's `--json-schema` flag does the structured-output coercion for us;
results land in the `structured_output` field of the top-level JSON envelope.
"""
from __future__ import annotations
import asyncio
import json
import shutil
from dataclasses import dataclass
from typing import Any

CLAUDE_BIN = shutil.which("claude") or "claude"

# Default model: haiku for extraction (fast, cheap, sufficient quality).
DEFAULT_MODEL = "haiku"

# Tight system prompt — replaces (not appends to) Claude Code's default,
# which keeps the prompt cache small and predictable.
EXTRACTION_SYSTEM_PROMPT = (
    "You extract structured data from a single text document. "
    "Output exactly one JSON object matching the supplied schema. "
    "No commentary, no markdown."
)

EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "products": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "homepage": {"type": "string"},
                    "role": {"type": "string", "enum": ["discussed", "built", "recommended"]},
                    "evidence_quote": {"type": "string"},
                },
                "required": ["name"],
            },
        },
        "revenue_claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "metric": {"type": "string", "enum": ["mrr", "arr", "users", "revenue_total", "profit", "other"]},
                    "amount_usd": {"type": "number"},
                    "claim_type": {"type": "string", "enum": ["self-reported", "inferred", "third-party"]},
                    "evidence_quote": {"type": "string"},
                },
                "required": ["metric", "amount_usd", "evidence_quote"],
            },
        },
        "problems": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "problem_quote": {"type": "string"},
                    "severity_1_5": {"type": "integer", "minimum": 1, "maximum": 5},
                },
                "required": ["problem_quote"],
            },
        },
        "ideas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "idea_quote": {"type": "string"},
                    "complexity_1_5": {"type": "integer", "minimum": 1, "maximum": 5},
                },
                "required": ["idea_quote"],
            },
        },
    },
    "required": ["products", "revenue_claims", "problems", "ideas"],
}


@dataclass
class CLIResult:
    structured_output: dict[str, Any] | None
    is_error: bool
    cost_usd: float
    duration_ms: int
    cache_read_tokens: int
    cache_creation_tokens: int
    raw_envelope: dict[str, Any]


async def run_extraction(
    document_text: str,
    *,
    model: str = DEFAULT_MODEL,
    system_prompt: str = EXTRACTION_SYSTEM_PROMPT,
    schema: dict[str, Any] | None = None,
    timeout_sec: float = 120.0,
) -> CLIResult:
    """Run a single extraction. Streams the doc to `claude -p` over stdin."""
    schema_str = json.dumps(schema or EXTRACTION_SCHEMA)
    args = [
        CLAUDE_BIN, "-p",
        "--output-format", "json",
        "--json-schema", schema_str,
        "--system-prompt", system_prompt,
        "--model", model,
        "--disable-slash-commands",
    ]
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=document_text.encode("utf-8")),
            timeout=timeout_sec,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise

    if proc.returncode != 0:
        raise RuntimeError(f"claude CLI exited {proc.returncode}: {stderr.decode('utf-8', errors='replace')[:500]}")

    text = stdout.decode("utf-8", errors="replace").strip()
    # `claude -p --output-format json` outputs one JSON object on the last line.
    last = text.splitlines()[-1] if text else "{}"
    env = json.loads(last)
    return CLIResult(
        structured_output=env.get("structured_output"),
        is_error=bool(env.get("is_error")),
        cost_usd=float(env.get("total_cost_usd") or 0.0),
        duration_ms=int(env.get("duration_ms") or 0),
        cache_read_tokens=int((env.get("usage") or {}).get("cache_read_input_tokens") or 0),
        cache_creation_tokens=int((env.get("usage") or {}).get("cache_creation_input_tokens") or 0),
        raw_envelope=env,
    )


async def run_batch(
    documents: list[tuple[str, str]],
    *,
    concurrency: int = 2,
    **kwargs: Any,
) -> list[tuple[str, CLIResult | Exception]]:
    """Run extraction over (id, text) pairs with bounded concurrency.

    Concurrency=2 by default — the CLI is heavyweight per process and prompt
    caching benefits from sequential reuse within a 5-minute window. Don't
    crank this high; you'll pay more in cache misses than you save in latency.
    """
    sem = asyncio.Semaphore(concurrency)
    results: list[tuple[str, CLIResult | Exception]] = []

    async def one(doc_id: str, text: str) -> None:
        async with sem:
            try:
                r = await run_extraction(text, **kwargs)
                results.append((doc_id, r))
            except Exception as e:
                results.append((doc_id, e))

    await asyncio.gather(*(one(i, t) for i, t in documents))
    return results
