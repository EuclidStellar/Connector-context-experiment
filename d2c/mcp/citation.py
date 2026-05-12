"""Citation validator — structural defense against hallucinated numbers.

Contract:
1. Every MCP tool returns a ToolResult: {value, citations: [...]}.
2. Before passing results to the LLM, session.bind(result) registers each one
   and returns a short cite token (t1, t2, ...) for the LLM to use inline.
3. The LLM writes prose with [cite:tN] after every numeric claim.
4. validate(response, session) verifies every numeric claim is bound to a known token.

Edge cases (refine as they surface):
- URL fragments / hash IDs / identifiers excluded from numeric-claim regex.
- Qualitative claims ("many", "a few") trigger no requirement.
- Derived numbers must come from a tool call; LLM cannot do inline arithmetic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_NUMERIC_CLAIM_RE = re.compile(
    r"""
    (?<![\/\#\-_a-zA-Z])                 # not part of URL, hash ID, or identifier
    (?:[₹$€£]\s?)?                       # optional currency prefix
    (?<!\d)
    (?:
      \d{1,3}(?:[,_]\d{3})+(?:\.\d+)?    # thousand-separated number
      |
      \d+(?:\.\d+)?                      # plain number
    )
    \s?%?                                # optional percent
    """,
    re.VERBOSE,
)

_CITE_RE = re.compile(r"\[cite:([a-zA-Z0-9_-]+)\]")


@dataclass(frozen=True)
class Citation:
    envelope_id: str
    source: str
    ref: str


@dataclass(frozen=True)
class ToolResult:
    value: Any
    citations: list[Citation] = field(default_factory=list)


@dataclass
class CitationSession:
    """Holds token → ToolResult bindings for one agent loop invocation.

    Tokens are session-scoped: cite references in the LLM's output must resolve
    to tokens issued during this session.
    """

    tokens: dict[str, ToolResult] = field(default_factory=dict)
    _counter: int = 0

    def bind(self, result: ToolResult) -> str:
        self._counter += 1
        token = f"t{self._counter}"
        self.tokens[token] = result
        return token


@dataclass(frozen=True)
class ValidationOutcome:
    is_valid: bool
    unbound_claims: list[str]
    unknown_tokens: list[str]


def validate(
    response: str,
    session: CitationSession,
    max_distance: int = 40,
) -> ValidationOutcome:
    """Verify every numeric claim is bound to a known cite token.

    A claim is bound if [cite:TOKEN] appears within `max_distance` characters
    after the number AND the token exists in session.tokens.
    """
    unbound: list[str] = []
    unknown_tokens: list[str] = []

    for cite in _CITE_RE.finditer(response):
        token = cite.group(1)
        if token not in session.tokens:
            unknown_tokens.append(token)

    for m in _NUMERIC_CLAIM_RE.finditer(response):
        claim = m.group(0).strip()
        if not claim:
            continue
        window = response[m.end() : m.end() + max_distance]
        if not _CITE_RE.search(window):
            unbound.append(claim)

    return ValidationOutcome(
        is_valid=(not unbound and not unknown_tokens),
        unbound_claims=unbound,
        unknown_tokens=unknown_tokens,
    )
