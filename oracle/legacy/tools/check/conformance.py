"""Conformance suite for the static checker.

Loads every `examples/refusal/<name>.expect.json` sidecar, runs the
checker against the corresponding `.chw` file, and asserts that:

- Every expected diagnostic (by `code`) is emitted by the checker.
- The `subject` of the emitted diagnostic matches (kind + fields).
- The `message` of the emitted diagnostic contains the substring
  named in `message_contains`.

A diagnostic that the checker emits but is not in the sidecar is
reported as an unexpected diagnostic — it might be a true positive
that the sidecar didn't anticipate, or a false positive that the
sidecar should be updated to cover. Both are reported.

Usage:

    python3 oracle/legacy/tools/check/conformance.py
    # exits 0 on full pass, 1 on any mismatch.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "oracle" / "legacy" / "tools" / "check"))

from checker import check_file  # noqa: E402
from diagnostic import Diagnostic  # noqa: E402


EXAMPLES = ROOT / "examples"
MANIFEST = json.loads((EXAMPLES / "MANIFEST.json").read_text())


def _subject_to_tuple(d: Diagnostic) -> tuple:
    if d.subject is None:
        return ("<none>",)
    # `Ir` subjects carry the source path (and possibly a JSON pointer
    # from the schema validator), both of which depend on how the user
    # invoked the checker. Match the other fields and ignore those for
    # that subject kind.
    if d.subject.kind == "Ir":
        fields = {k: v for k, v in d.subject.fields.items() if k not in ("path", "pointer")}
        return (d.subject.kind,) + tuple(sorted(fields.items()))
    return (d.subject.kind,) + tuple(sorted(d.subject.fields.items()))


def _normalize_subject(expected: dict) -> tuple:
    """A sidecar's subject is a plain dict with `kind` and other fields.

    For `Ir` subjects, `path` and `pointer` are dropped from the
    comparison: the path depends on how the user invoked the checker,
    and a sidecar should not have to repeat the absolute path the
    user used.
    """
    kind = expected.get("kind", "<none>")
    fields = {k: v for k, v in expected.items() if k != "kind"}
    if kind == "Ir":
        fields = {k: v for k, v in fields.items() if k not in ("path", "pointer")}
    return (kind,) + tuple(sorted(fields.items()))


def _check_one(chw_path: pathlib.Path) -> tuple[bool, list[str]]:
    name = chw_path.stem
    sidecar = chw_path.with_suffix(".expect.json")
    notes: list[str] = []

    if not sidecar.exists():
        notes.append(f"  WARN  {name}: no .expect.json sidecar; skipping")
        return True, notes

    expected_list = json.loads(sidecar.read_text())["expect"]
    emitted = check_file(str(chw_path))

    # For each expected diagnostic, find at least one emitted one that matches.
    matched: list[int] = []
    for exp in expected_list:
        exp_code = exp["code"]
        exp_subject = _normalize_subject(exp["subject"])
        exp_msg_substr = exp.get("message_contains", "")

        found = False
        for i, d in enumerate(emitted):
            if d.code != exp_code:
                continue
            if _subject_to_tuple(d) != exp_subject:
                continue
            if exp_msg_substr and exp_msg_substr not in d.message:
                continue
            matched.append(i)
            found = True
            break
        if not found:
            notes.append(
                f"  FAIL  {name}: expected diagnostic {exp_code} subject={exp_subject} "
                f"msg~={exp_msg_substr!r} not found. Emitted: "
                + ", ".join(
                    f"{d.code}/{d.subject.kind if d.subject else '<none>'}"
                    for d in emitted
                )
            )
            return False, notes

    # Diagnostics the checker emitted that no sidecar entry anticipates.
    extra = [d for i, d in enumerate(emitted) if i not in matched]
    if extra:
        for d in extra:
            notes.append(
                f"  FAIL  {name}: unexpected diagnostic {d.code} subject="
                f"{_subject_to_tuple(d)} msg={d.message!r}"
            )
        return False, notes

    notes.append(f"  PASS  {name}: {len(expected_list)} diagnostic(s) matched, 0 unexpected")
    return True, notes


def _check_valid(chw_path: pathlib.Path) -> tuple[bool, list[str]]:
    """A valid example must produce zero Error-severity diagnostics."""
    diags = check_file(str(chw_path))
    errors = [d for d in diags if d.severity == "Error"]
    if errors:
        notes = [
            f"  FAIL  {chw_path.name}: valid example emitted {len(errors)} error(s):"
        ]
        for d in errors:
            notes.append(f"          {d.code}: {d.message}")
        return False, notes
    return True, [f"  PASS  {chw_path.name}: valid, 0 errors"]


def main() -> int:
    print("== static checker conformance ==")
    failures: list[str] = []

    # Valid examples
    print()
    print("## valid examples (must produce 0 errors) ##")
    for rel in MANIFEST["valid"] + MANIFEST.get("textual_valid", []):
        ok, notes = _check_valid(ROOT / rel)
        for n in notes:
            print(n)
        if not ok:
            failures.extend(notes)

    # Refusal examples
    print()
    print("## refusal examples (must emit named diagnostics) ##")
    refusal_dir = ROOT / MANIFEST["refusal_dir"]
    for chw in sorted(refusal_dir.glob(MANIFEST["refusal_glob"])):
        ok, notes = _check_one(chw)
        for n in notes:
            print(n)
        if not ok:
            failures.extend(notes)

    print()
    if failures:
        print(f"== {len(failures)} mismatch(es) ==")
        return 1
    print("== all checks matched ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())