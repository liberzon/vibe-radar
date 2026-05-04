"""LLM-based extraction (Claude Sonnet) over `documents`.

Run after the regex pass. Cost-aware: skip docs that the regex pass marked as
low-signal, and cache results keyed on (document_id, prompt_version).

This is a SCAFFOLD — wire to the Anthropic SDK only after confirming budget.
"""
from __future__ import annotations
import json
from dataclasses import dataclass

PROMPT_VERSION = "v1"

EXTRACTION_PROMPT = """\
You are reading a single document from an online community. The operator is
researching products, services, and businesses discussed in that community.

Extract the following as JSON:
- products: [{name, homepage_or_repo, role: "discussed"|"built"|"recommended", evidence_quote}]
- revenue_claims: [{metric: "mrr"|"arr"|"users"|"revenue_total", amount_usd, evidence_quote,
                     claim_type: "self-reported"|"inferred"|"third-party"}]
- problems: [{problem_quote, severity_1_5}]    // pain points the author wishes were solved
- ideas: [{idea_quote, complexity_1_5}]        // ideas the author wishes someone would build

Rules:
- Only include items with direct evidence in the document. Do not infer.
- Convert non-USD amounts to USD using a reasonable estimate; mark currency.
- Output ONE JSON object. No commentary.

Document:
---
{document}
---
"""


@dataclass
class ExtractionResult:
    products: list[dict]
    revenue_claims: list[dict]
    problems: list[dict]
    ideas: list[dict]


def parse_extraction(raw: str) -> ExtractionResult:
    obj = json.loads(raw)
    return ExtractionResult(
        products=obj.get("products") or [],
        revenue_claims=obj.get("revenue_claims") or [],
        problems=obj.get("problems") or [],
        ideas=obj.get("ideas") or [],
    )


# To wire up:
#
# from anthropic import AsyncAnthropic
# client = AsyncAnthropic()
#
# async def extract(document_text: str) -> ExtractionResult:
#     msg = await client.messages.create(
#         model="claude-sonnet-4-6",
#         max_tokens=2000,
#         system="You extract structured data. Output only JSON.",
#         messages=[{"role": "user", "content": EXTRACTION_PROMPT.format(document=document_text)}],
#     )
#     return parse_extraction(msg.content[0].text)
#
# Pair with prompt caching: put EXTRACTION_PROMPT (the static part) in a
# cache_control block so we pay full price only on the first call per ~5min window.
