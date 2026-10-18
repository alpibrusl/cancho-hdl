"""Diagnostic shape for cancho-hdl.

The canonical emitter of `Diagnostic` values is the static checker
(`tools/check/checker.py`). The reference-model simulator
(`tools/sim/reference_model.py`) emits Runtime-tier diagnostics with
the same shape. Both modules import from here so the JSON form
emitted by `cancho-hdl check` and the form raised by the simulator
are byte-for-byte compatible.

The shape is locked at `spec/diagnostics/README.md` §2. Any change
to a field name is a major version bump of the diagnostic schema.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Subject:
    kind: str
    fields: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, **self.fields}


@dataclass
class Position:
    line: int
    column: int

    def to_dict(self) -> dict[str, Any]:
        return {"line": self.line, "column": self.column}


@dataclass
class Span:
    file: str
    start: Position
    end: Position

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "start": self.start.to_dict(),
            "end": self.end.to_dict(),
        }


@dataclass
class Remediation:
    """Structured remediation hint (spec §2). Purely tool-derived —
    never an LLM-generated explanation (§2.3). `suggestion` is a
    structured patch hint when the toolchain can justify one; it is
    None everywhere in Phase 1."""
    description: str
    suggestion: Any = None
    confidence: str = "Medium"  # High | Medium | Low


@dataclass
class Diagnostic:
    code: str
    severity: str = "Error"  # Error | Warning
    tier: str = "Static"     # Static | Tested | Runtime | Trust | Unknown
    subject: Subject | None = None
    span: Span | None = None
    message: str = ""
    expected: Any = None
    actual: Any = None
    remediation: Remediation | None = None
    related: list["Diagnostic"] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Stable field order: code, severity, tier, message, related,
        notes, subject, span, expected, actual, remediation. Consumers
        can rely on this for diff stability per
        `spec/diagnostics/README.md` §4.1."""
        out: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity,
            "tier": self.tier,
            "message": self.message,
            "related": [r.to_dict() for r in self.related],
            "notes": list(self.notes),
        }
        if self.subject is not None:
            out["subject"] = self.subject.to_dict()
        if self.span is not None:
            out["span"] = self.span.to_dict()
        if self.expected is not None:
            out["expected"] = self.expected
        if self.actual is not None:
            out["actual"] = self.actual
        if self.remediation is not None:
            out["remediation"] = {
                "description": self.remediation.description,
                "suggestion": self.remediation.suggestion,
                "confidence": self.remediation.confidence,
            }
        return out

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


def file_span(file: str) -> Span:
    """A whole-file span, used when the source is the JSON wire form
    (Phase 0) and the textual parser has not yet been written. Phase 1's
    parser will replace this with real line/column spans."""
    return Span(file=file, start=Position(1, 1), end=Position(1, 1))