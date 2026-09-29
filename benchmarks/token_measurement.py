"""Deterministic wire-text token accounting for the browser benchmark.

Counts serialized UTF-8 text with tiktoken's o200k_base encoding.  These are
not provider-billed tokens: model prompts, reasoning, screenshots, and any
transport bytes outside the recorded JSON/text are excluded.
"""
from __future__ import annotations

import json
import re
from typing import Any

import tiktoken

ENCODING = "o200k_base"
_encoder = tiktoken.get_encoding(ENCODING)


def tokens(text: str) -> int:
    return len(_encoder.encode(text))


def compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def sample(request: str, response: str) -> dict[str, Any]:
    # Fixture ports, run identifiers, and JSON-RPC ids are transport-local
    # variation. Replace them before counting and publishing while retaining a
    # fixed-shape representative wire message.
    def canonical(text: str) -> str:
        text = re.sub(r"127\.0\.0\.1:\d{1,5}", "127.0.0.1:00000", text)
        text = re.sub(r"matched-opencli-\d+-\d+", "matched-opencli-N-0000000000000", text)
        text = re.sub(r"matched-(?:mcp-)?\d+", "matched-N", text)
        text = re.sub(r'("id"\s*:\s*)\d+', r'\g<1>0', text)
        return text
    request, response = canonical(request), canonical(response)
    return {
        "request_text": request,
        "response_text": response,
        "request_tokens": tokens(request),
        "response_tokens": tokens(response),
        "total_tokens": tokens(request) + tokens(response),
    }
