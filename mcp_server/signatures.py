"""Custom DSPy signature builder and pre-built signatures."""

from __future__ import annotations

import re
from typing import Any

import dspy


# -- Pre-built signatures --

SEARCH_SIGNATURE = "context, query -> answer: str"
EXTRACT_SIGNATURE = "document, fields -> extracted: dict"
CLASSIFY_SIGNATURE = "text, categories -> category: str, confidence: float"
SUMMARIZE_SIGNATURE = "document -> summary: str"


# -- Deep reasoning signatures --

_DEEP_REASONING_INSTRUCTIONS = """\
Use a 3-phase reasoning strategy to answer the query from the provided context.

Phase 1 — Recon: Read the full context. Note its size and format. Identify
chunk boundaries (e.g. paragraph breaks, section headers, numbered items).
Determine which sections are likely relevant to the query.

Phase 2 — Filter: Split the context along the boundaries identified in Phase 1.
For each chunk, apply a keyword or regex check against the query terms. For
chunks that pass the filter, call llm_query() to extract relevant information.
Discard chunks that clearly don't relate to the query.

Phase 3 — Aggregate: Collect the llm_query() results from Phase 2. Call
llm_query() once more to synthesize them into a single coherent answer.
Return that synthesized answer as the output.
"""

_DEEP_REASONING_MULTI_INSTRUCTIONS = """\
Use a 3-phase reasoning strategy to answer the query across multiple documents.

Phase 1 — Recon: Read all documents. Note each document's size, format, and
chunk boundaries (paragraph breaks, section headers, numbered items). Identify
which documents and sections are likely relevant to the query.

Phase 2 — Filter: For each document, split along its boundaries. Apply a
keyword or regex check against query terms. For chunks that pass, call
llm_query() to extract relevant information. Discard irrelevant chunks.

Phase 3 — Aggregate: Collect all llm_query() results from Phase 2 across all
documents. Call llm_query() once more to synthesize them into a single
coherent answer. Return that synthesized answer as the output.
"""


# -- Signature validation --

# Valid Python identifier (no leading digit, no dunder)
_IDENT_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# String signature format: "input1, input2 -> output1: type, output2: type"
_SIG_RE = re.compile(
    r"^"
    r"[a-zA-Z_]\w*(?:\s*:\s*\w+)?(?:\s*,\s*[a-zA-Z_]\w*(?:\s*:\s*\w+)?)*"
    r"\s*->\s*"
    r"[a-zA-Z_]\w*(?:\s*:\s*\w+)?(?:\s*,\s*[a-zA-Z_]\w*(?:\s*:\s*\w+)?)*"
    r"$"
)


def validate_signature(signature: str | type) -> bool:
    """Check if a signature string or class is valid for RLM use."""
    if isinstance(signature, type):
        return issubclass(signature, dspy.Signature)

    if not isinstance(signature, str):
        return False

    # Named signatures are valid without needing regex match
    if signature in NAMED_SIGNATURES:
        return True

    sig = signature.strip()
    if not sig or "->" not in sig:
        return False

    return bool(_SIG_RE.match(sig))


# -- Dynamic signature builder --


def build_custom_signature(
    name: str,
    input_fields: dict[str, str],
    output_fields: dict[str, str],
    instructions: str = "",
) -> type:
    """Build a DSPy Signature class dynamically from field definitions.

    Args:
        name: Class name for the signature.
        input_fields: {field_name: description} for inputs.
        output_fields: {field_name: description} for outputs.
        instructions: Docstring / task description for the signature.

    Returns:
        A new dspy.Signature subclass.

    Raises:
        ValueError: If field names are invalid or no fields provided.
    """
    if not input_fields:
        raise ValueError("At least one input field required")
    if not output_fields:
        raise ValueError("At least one output field required")

    # Validate field names
    all_fields = list(input_fields) + list(output_fields)
    for field_name in all_fields:
        if not _IDENT_RE.match(field_name):
            raise ValueError(f"Invalid field name: {field_name!r}")

    # Check for overlap
    overlap = set(input_fields) & set(output_fields)
    if overlap:
        raise ValueError(f"Fields appear in both input and output: {overlap}")

    # Build class attributes
    attrs: dict[str, Any] = {}
    if instructions:
        attrs["__doc__"] = instructions

    for field_name, desc in input_fields.items():
        attrs[field_name] = dspy.InputField(desc=desc)

    for field_name, desc in output_fields.items():
        attrs[field_name] = dspy.OutputField(desc=desc)

    # Create the Signature subclass
    return type(name, (dspy.Signature,), attrs)


# -- Deep reasoning signature instances --
# Built after build_custom_signature is defined.

DEEP_REASONING_SIGNATURE: type = build_custom_signature(
    "DeepReasoning",
    {"context": "source text to reason over", "query": "the question to answer"},
    {"answer": "synthesized answer from phased reasoning"},
    instructions=_DEEP_REASONING_INSTRUCTIONS,
)

DEEP_REASONING_MULTI_SIGNATURE: type = build_custom_signature(
    "DeepReasoningMulti",
    {"documents": "newline-separated documents to reason over", "query": "the question to answer"},
    {"answer": "synthesized answer from phased reasoning across all documents"},
    instructions=_DEEP_REASONING_MULTI_INSTRUCTIONS,
)


# -- Named signature lookup --

NAMED_SIGNATURES: dict[str, type] = {
    "deep_reasoning": DEEP_REASONING_SIGNATURE,
    "deep_reasoning_multi": DEEP_REASONING_MULTI_SIGNATURE,
}


def resolve_signature(signature: str | type) -> str | type:
    """Resolve a short name to a Signature class, or return the input unchanged."""
    if isinstance(signature, str) and signature in NAMED_SIGNATURES:
        return NAMED_SIGNATURES[signature]
    return signature
