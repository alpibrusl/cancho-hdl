"""cancho-hdl static checker.

Implements the rules in `spec/diagnostics/README.md` §3 at the Static
tier. The schema in `spec/contract-schema/` catches the structural
violations; this checker catches the semantic ones — register and
field overlap, reset-value fit, interrupt linkage, DMA ownership and
alignment.

Every diagnostic carries a stable `code` (kebab-case), a tier, a
subject, and a one-line message. The shape is locked at
`spec/diagnostics/README.md` §2; the rule codes are the catalog at
§3. This checker does not add a rule that is not in §3.

Usage:

    from checker import check
    diagnostics = check(ir_dict, source_path="examples/uart-contract/uart.chw")
    for d in diagnostics:
        print(d.to_dict())
"""

from __future__ import annotations

import json
import pathlib
import sys
from typing import Any

# Shared diagnostic shape
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from diagnostic import Diagnostic, Subject, Span, file_span, Remediation  # noqa: E402
from text_format import format_diagnostics  # noqa: E402

# The textual `.chw` parser (Phase 1). `load_contract` sniffs the file
# format: a file whose first non-whitespace character is `{` is the
# JSON wire format, anything else is the textual syntax. Both land in
# this pipeline, so a contract can be checked no matter which form it
# arrived in.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "parse"))
from parser import load_contract  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_hex(s: Any) -> int | None:
    """Parse a 0x... literal. Returns None if not parseable."""
    if not isinstance(s, str) or not s.startswith("0x"):
        return None
    try:
        return int(s, 16)
    except ValueError:
        return None


def _bus_mask(bus_width: int) -> int:
    return (1 << bus_width) - 1


# ---------------------------------------------------------------------------
# Schema / version checks
# ---------------------------------------------------------------------------


def _check_schema_version(ir: dict[str, Any], file: str) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    version = ir.get("version")
    if not isinstance(version, str):
        diags.append(Diagnostic(
            code="schema-invalid",
            tier="Static",
            subject=Subject("Ir", {"path": file}),
            span=file_span(file),
            message=f"contract is missing required 'version' field (string in MAJOR.MINOR.PATCH form).",
        ))
        return diags
    parts = version.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        diags.append(Diagnostic(
            code="schema-invalid",
            tier="Static",
            subject=Subject("Ir", {"path": file}),
            span=file_span(file),
            message=f"version {version!r} is not in MAJOR.MINOR.PATCH form.",
        ))
        return diags
    # The Phase 0 wire format is 0.1.0. 0.2.0 lands when contract-design.md §5 questions are closed.
    major, minor, _patch = (int(p) for p in parts)
    if (major, minor) != (0, 1):
        diags.append(Diagnostic(
            code="schema-version-unsupported",
            tier="Runtime",  # per spec/diagnostics/README.md §3.1
            subject=Subject("Ir", {"path": file}),
            span=file_span(file),
            message=f"schema version {version} is not supported by this toolchain (expected 0.1.x).",
        ))
    return diags


# ---------------------------------------------------------------------------
# Block-level checks
# ---------------------------------------------------------------------------


def _check_block(block: dict[str, Any], file: str) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    name = block.get("name")
    if not isinstance(name, str) or not name:
        diags.append(Diagnostic(
            code="block-name-missing",
            tier="Static",
            subject=Subject("RegisterBlock", {"name": "<missing>"}),
            span=file_span(file),
            message="block is missing required 'name' (non-empty string).",
        ))
        return diags  # Subsequent checks need a name; bail.

    if not _parse_hex(block.get("base_address", "")):
        diags.append(Diagnostic(
            code="block-base-address-missing",
            tier="Static",
            subject=Subject("RegisterBlock", {"name": name}),
            span=file_span(file),
            message=f"block {name!r} has no valid hex 'base_address' (expected '0x...').",
        ))

    bus_width = block.get("bus_width")
    # Schema already constrains bus_width to {8, 16, 32}, but the checker
    # also reports the code at the Static tier for cases where the schema
    # is bypassed (e.g. .chw files written before the schema was tightened).
    if bus_width not in (8, 16, 32):
        diags.append(Diagnostic(
            code="block-bus-width-invalid",
            tier="Static",
            subject=Subject("RegisterBlock", {"name": name}),
            span=file_span(file),
            message=f"block {name} has bus_width {bus_width} must be 8, 16, or 32.",
            expected="8, 16, or 32",
            actual=bus_width,
        ))

    endianness = block.get("endianness")
    if endianness not in ("little", "big"):
        diags.append(Diagnostic(
            code="block-endianness-unknown",
            tier="Static",
            subject=Subject("RegisterBlock", {"name": name}),
            span=file_span(file),
            message=f"block {name!r} has endianness={endianness!r}; must be 'little' or 'big'.",
            expected="'little' or 'big'",
            actual=endianness,
        ))

    return diags


# ---------------------------------------------------------------------------
# Register-level checks
# ---------------------------------------------------------------------------


_KNOWN_KINDS = {"RO", "WO", "RW", "RC", "W1C", "W0C", "W1S", "W0S"}


def _check_registers(registers: list[dict[str, Any]], block_name: str, bus_width: int, file: str) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    by_offset: dict[int, str] = {}
    for reg in registers:
        name = reg.get("name")
        offset = _parse_hex(reg.get("offset", ""))
        kind = reg.get("kind")

        if not isinstance(name, str) or not name:
            diags.append(Diagnostic(
                code="register-name-missing",
                tier="Static",
                subject=Subject("Register", {"block": block_name, "name": "<missing>"}),
                span=file_span(file),
                message="register is missing required 'name' (non-empty string).",
            ))
            continue

        if offset is None:
            diags.append(Diagnostic(
                code="register-offset-missing",
                tier="Static",
                subject=Subject("Register", {"block": block_name, "name": name}),
                span=file_span(file),
                message=f"register {name!r} is missing a valid hex 'offset' (expected '0x...').",
            ))
            continue

        # A register's offset must be aligned to the register's natural
        # size, which is bus_width / 8 bytes. For a 32-bit bus, that's 4.
        reg_size_bytes = bus_width // 8
        if offset % reg_size_bytes != 0:
            diags.append(Diagnostic(
                code="register-offset-non-aligned",
                tier="Static",
                subject=Subject("Register", {"block": block_name, "name": name}),
                span=file_span(file),
                message=(
                    f"register {name!r} offset {reg.get('offset')} is not a multiple of "
                    f"register size {reg_size_bytes} bytes (bus_width {bus_width})."
                ),
                expected=f"offset % {reg_size_bytes} == 0",
                actual=f"offset {reg.get('offset')}",
            ))

        # The block's address space is conventionally sized 2**bus_width bytes wide
        # for the purposes of overflow checks. (Real systems have an explicit
        # addressable range; the schema does not require one. The 2**bus_width
        # bound is a generous sanity check.)
        if offset + reg_size_bytes > (1 << bus_width):
            diags.append(Diagnostic(
                code="register-offset-overflow",
                tier="Static",
                subject=Subject("Register", {"block": block_name, "name": name}),
                span=file_span(file),
                message=(
                    f"register {name!r} offset {reg.get('offset')} pushes the register "
                    f"past the block's addressable range."
                ),
            ))

        if offset in by_offset:
            other = by_offset[offset]
            diags.append(Diagnostic(
                code="register-offset-duplicate",
                tier="Static",
                subject=Subject("Register", {"block": block_name, "name": other}),
                span=file_span(file),
                message=(
                    f"registers {other} and {name} share offset {reg.get('offset')} "
                    f"in block {block_name}."
                ),
                expected="unique offset within block",
                actual=f"offset shared with {name}",
                related=[Diagnostic(
                    code="register-offset-duplicate",
                    subject=Subject("Register", {"block": block_name, "name": name}),
                    span=file_span(file),
                    message=f"register {name} is also at offset {reg.get('offset')}.",
                )],
            ))
        else:
            by_offset[offset] = name

        if kind not in _KNOWN_KINDS:
            diags.append(Diagnostic(
                code="register-kind-unknown",
                tier="Static",
                subject=Subject("Register", {"block": block_name, "name": name}),
                span=file_span(file),
                message=(
                    f"register {name} has kind '{kind}'; kind '{kind}' is not a known access kind. "
                    f"Known kinds: {', '.join(sorted(_KNOWN_KINDS))}."
                ),
                expected=sorted(_KNOWN_KINDS),
                actual=kind,
            ))
            continue  # subsequent checks need a known kind

        # Reset value
        if "reset" in reg:
            reset_val = _parse_hex(reg["reset"])
            if reset_val is None or reset_val > _bus_mask(bus_width):
                diags.append(Diagnostic(
                    code="reset-overflow",
                    tier="Static",
                    subject=Subject("Register", {"block": block_name, "name": name}),
                    span=file_span(file),
                    message=(
                        f"register {name} reset {reg.get('reset')} does not fit in bus_width {bus_width}."
                    ),
                    expected=f"0 <= reset <= 0x{_bus_mask(bus_width):x}",
                    actual=reg.get("reset"),
                ))
            elif kind == "WO" and reset_val != 0:
                diags.append(Diagnostic(
                    code="reset-wo-nonzero",
                    severity="Warning",
                    tier="Static",
                    subject=Subject("Register", {"block": block_name, "name": name}),
                    span=file_span(file),
                    message=(
                        f"register {name!r} is WO with non-zero reset {reg.get('reset')!r}; "
                        f"this is unusual (WO registers are typically ignored at reset)."
                    ),
                ))

        # Fields
        diags.extend(_check_fields(reg, block_name, bus_width, file))

    return diags


def _check_fields(reg: dict[str, Any], block_name: str, bus_width: int, file: str) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    reg_name = reg.get("name", "<missing>")
    fields = reg.get("fields", [])
    if not isinstance(fields, list):
        return diags  # schema catches this

    occupied: list[tuple[int, int, str]] = []  # (lsb, msb, name)

    for f in fields:
        name = f.get("name")
        lsb = f.get("lsb")
        msb = f.get("msb")

        if not isinstance(name, str) or not name:
            diags.append(Diagnostic(
                code="field-name-missing",
                tier="Static",
                subject=Subject("Field", {"block": block_name, "register": reg_name, "name": "<missing>"}),
                span=file_span(file),
                message=f"field in register {reg_name!r} is missing required 'name'.",
            ))
            continue

        if not isinstance(lsb, int) or not isinstance(msb, int):
            diags.append(Diagnostic(
                code="field-bounds-missing",
                tier="Static",
                subject=Subject("Field", {"block": block_name, "register": reg_name, "name": name}),
                span=file_span(file),
                message=f"field {name!r} is missing required 'lsb' / 'msb' (integers).",
            ))
            continue

        if msb < lsb:
            diags.append(Diagnostic(
                code="field-bounds-inverted",
                tier="Static",
                subject=Subject("Field", {"block": block_name, "register": reg_name, "name": name}),
                span=file_span(file),
                message=f"field {name!r} has msb={msb} < lsb={lsb}.",
            ))
            continue

        # Schema already constrains lsb/msb to [0, 31]; the checker
        # also reports field-bounds-overflow for cases where the
        # schema is bypassed.
        if msb >= bus_width:
            diags.append(Diagnostic(
                code="field-bounds-overflow",
                tier="Static",
                subject=Subject("Field", {"block": block_name, "register": reg_name, "name": name}),
                span=file_span(file),
                message=(
                    f"field {name} has msb {msb} >= bus_width {bus_width}; "
                    f"field extends past the register."
                ),
                expected=f"msb < {bus_width}",
                actual=f"msb={msb}",
            ))
            continue  # overlap check is meaningless past the register

        # Overlap
        for (olsb, omsb, oname) in occupied:
            if not (msb < olsb or lsb > omsb):
                # Remediation is mechanical (a tool-derived hint, not an
                # LLM explanation, per spec §2.3): shifting this field
                # to start just after the other one is a placement the
                # toolchain can compute and re-check. It is stated as
                # "Low" confidence because the toolchain cannot know
                # which side holds the hardware semantics.
                width = msb - lsb + 1
                new_lsb = omsb + 1
                new_msb = new_lsb + width - 1
                diags.append(Diagnostic(
                    code="field-overlap",
                    tier="Static",
                    subject=Subject("Field", {"block": block_name, "register": reg_name, "name": name}),
                    span=file_span(file),
                    message=(
                        f"field {name!r} bits [{lsb}..{msb}] overlap with {oname} "
                        f"bits [{olsb}..{omsb}] in register {reg_name!r}."
                    ),
                    remediation=Remediation(
                        description=(
                            f"start {name} at bits [{new_lsb}..{new_msb}] (just after "
                            f"{oname}, bits [{olsb}..{omsb}]), or shrink / move either "
                            f"field — the toolchain cannot say which side the "
                            f"hardware semantics live on"
                        ),
                        confidence="Low",
                    ),
                    related=[Diagnostic(
                        code="field-overlap",
                        subject=Subject("Field", {"block": block_name, "register": reg_name, "name": oname}),
                        span=file_span(file),
                        message=f"field {oname!r} occupies bits [{olsb}..{omsb}] in register {reg_name!r}.",
                    )],
                ))
        occupied.append((lsb, msb, name))

        # Enum fit
        if "enum" in f and isinstance(f["enum"], dict):
            width = msb - lsb + 1
            field_mask = (1 << width) - 1
            for label, val in f["enum"].items():
                if not isinstance(val, int) or val < 0 or val > field_mask:
                    diags.append(Diagnostic(
                        code="field-enum-overflow",
                        tier="Static",
                        subject=Subject("Field", {"block": block_name, "register": reg_name, "name": name}),
                        span=file_span(file),
                        message=(
                            f"field {name}: enum value {val} does not fit in {width} bits "
                            f"(declared as {label}={val})."
                        ),
                        expected=f"0 <= value <= {field_mask}",
                        actual=val,
                    ))

        # Constraint text: warning that the checker does not parse it
        if "constraint" in f and isinstance(f["constraint"], str):
            diags.append(Diagnostic(
                code="field-constraint-ignored",
                severity="Warning",
                tier="Static",
                subject=Subject("Field", {"block": block_name, "register": reg_name, "name": name}),
                span=file_span(file),
                message=(
                    f"field {name!r} declares constraint {f['constraint']!r}; "
                    f"the Phase 0 checker does not parse constraint semantics "
                    f"(see docs/contract-design.md §5 question 3)."
                ),
                notes=[
                    "constraints are documented but not enforced until 0.2.0",
                ],
            ))

    return diags


# ---------------------------------------------------------------------------
# Interrupt checks
# ---------------------------------------------------------------------------


_VALID_CLEAR_KINDS = {"W1C", "W0C", "RC"}


def _check_interrupts(interrupts: list[dict[str, Any]], block: dict[str, Any], file: str) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    block_name = block.get("name", "<missing>")
    registers_by_name = {r.get("name"): r for r in block.get("registers", []) if r.get("name")}
    seen_names: set[str] = set()

    for intr in interrupts:
        name = intr.get("name")
        if not isinstance(name, str) or not name:
            diags.append(Diagnostic(
                code="interrupt-name-missing",
                tier="Static",
                subject=Subject("Interrupt", {"block": block_name, "name": "<missing>"}),
                span=file_span(file),
                message="interrupt is missing required 'name' (non-empty string).",
            ))
            continue

        if name in seen_names:
            diags.append(Diagnostic(
                code="interrupt-duplicate-name",
                tier="Static",
                subject=Subject("Interrupt", {"block": block_name, "name": name}),
                span=file_span(file),
                message=f"interrupt {name!r} is declared twice in block {block_name!r}.",
            ))
        seen_names.add(name)

        for role in ("source", "enable", "status"):
            ref = intr.get(role)
            if ref is None:
                continue
            diag = _check_ref(ref, registers_by_name, role, intr, block_name, file)
            if diag is not None:
                diag.code = f"interrupt-{role}-unresolved"
            if diag is not None:
                diags.append(diag)

        clear = intr.get("clear")
        if clear is not None:
            diag = _check_ref(clear, registers_by_name, "clear", intr, block_name, file)
            if diag is not None:
                diag.code = "interrupt-clear-unresolved"
                diags.append(diag)
            kind = clear.get("kind", "W1C")
            if kind not in _VALID_CLEAR_KINDS:
                diags.append(Diagnostic(
                    code="interrupt-clear-kind-invalid",
                    tier="Static",
                    subject=Subject("InterruptLinkage", {
                        "block": block_name, "interrupt": name, "role": "clear",
                    }),
                    span=file_span(file),
                    message=(
                        f"interrupt {name!r} clear.kind={kind!r}; must be one of "
                        f"{', '.join(sorted(_VALID_CLEAR_KINDS))}."
                    ),
                    expected=sorted(_VALID_CLEAR_KINDS),
                    actual=kind,
                ))

    return diags


def _check_ref(
    ref: dict[str, Any],
    registers_by_name: dict[str, dict[str, Any]],
    role: str,
    intr: dict[str, Any],
    block_name: str,
    file: str,
) -> Diagnostic | None:
    """Validate that a `{register, field}` reference resolves. Returns a
    Diagnostic with code prefix `interrupt-*-unresolved` if not."""
    reg_name = ref.get("register")
    field_name = ref.get("field")
    intr_name = intr.get("name", "<missing>")

    reg = registers_by_name.get(reg_name) if reg_name else None
    if reg is None:
        return Diagnostic(
            code="interrupt-unresolved",  # will be rewritten to role-specific code
            tier="Static",
            subject=Subject("InterruptLinkage", {
                "block": block_name, "interrupt": intr_name, "role": role,
            }),
            span=file_span(file),
            message=(
                f"interrupt {intr_name} {role} references {reg_name}.{field_name} "
                f"does not exist: register {reg_name} is not declared in block {block_name}."
            ),
            expected=f"an existing register name on block {block_name}",
            actual=f"{reg_name}.{field_name}",
        )

    field_names = {f.get("name") for f in reg.get("fields", []) if f.get("name")}
    if field_name not in field_names:
        return Diagnostic(
            code="interrupt-unresolved",
            tier="Static",
            subject=Subject("InterruptLinkage", {
                "block": block_name, "interrupt": intr_name, "role": role,
            }),
            span=file_span(file),
            message=(
                f"interrupt {intr_name} {role} references {reg_name}.{field_name} does not exist: "
                f"field {field_name} is not declared on register {reg_name}."
            ),
            expected="an existing field name on the referenced register",
            actual=f"{reg_name}.{field_name}",
        )

    return None


# ---------------------------------------------------------------------------
# DMA checks
# ---------------------------------------------------------------------------


def _check_dma(buffers: list[dict[str, Any]], block_name: str, file: str) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    for buf in buffers:
        name = buf.get("name")
        if not isinstance(name, str) or not name:
            diags.append(Diagnostic(
                code="dma-name-missing",
                tier="Static",
                subject=Subject("DmaBuffer", {"block": block_name, "name": "<missing>"}),
                span=file_span(file),
                message="DMA buffer is missing required 'name' (non-empty string).",
            ))
            continue

        # Sort fields by offset, check for overlap.
        fields = buf.get("fields", [])
        occupied: list[tuple[int, int, str]] = []  # (offset_start, offset_end_exclusive, name)
        for f in fields:
            fname = f.get("name")
            offset = _parse_hex(f.get("offset", ""))
            if not isinstance(fname, str) or not fname:
                diags.append(Diagnostic(
                    code="dma-field-name-missing",
                    tier="Static",
                    subject=Subject("DmaField", {"block": block_name, "buffer": name, "name": "<missing>"}),
                    span=file_span(file),
                    message=f"DMA buffer {name!r} has a field without a name.",
                ))
                continue
            if offset is None:
                # Schema catches this; we don't need a separate diagnostic.
                continue

            # Owner must be CPU or DEVICE. The schema catches this too,
            # but the static diagnostic carries more useful information
            # (the field name and the bad value) than the schema's
            # generic "is not one of" message.
            owner = f.get("owner")
            if owner not in ("CPU", "DEVICE"):
                diags.append(Diagnostic(
                    code="dma-owner-unknown",
                    tier="Static",
                    subject=Subject("DmaField", {"block": block_name, "buffer": name, "name": fname}),
                    span=file_span(file),
                    message=(
                        f"DMA field {fname} has owner '{owner}'; "
                        f"owner '{owner}' is not CPU or DEVICE."
                    ),
                    expected="'CPU' or 'DEVICE'",
                    actual=owner,
                ))
                # Don't continue — let other checks run too, e.g. alignment.

            # Convention: each DMA field is 4 bytes unless `size` is declared.
            # Phase 0 schema has no `size`; we use 4 bytes for overlap purposes.
            # Phase 1 should add an explicit `size` to the schema.
            size = f.get("size", 4)
            start = offset
            end = offset + size

            for (os, oe, oname) in occupied:
                if not (end <= os or start >= oe):
                    diags.append(Diagnostic(
                        code="dma-overlap",
                        tier="Static",
                        subject=Subject("DmaField", {"block": block_name, "buffer": name, "name": fname}),
                        span=file_span(file),
                        message=(
                            f"DMA field {fname} at offset 0x{start:02x}..0x{end:02x} "
                            f"overlaps {oname} at 0x{os:02x}..0x{oe:02x} in buffer {name}."
                        ),
                        related=[Diagnostic(
                            code="dma-overlap",
                            subject=Subject("DmaField", {"block": block_name, "buffer": name, "name": oname}),
                            span=file_span(file),
                            message=f"DMA field {oname} occupies 0x{os:02x}..0x{oe:02x} in buffer {name}.",
                        )],
                    ))
            occupied.append((start, end, fname))

            # Alignment
            align = f.get("align")
            if align is not None:
                if not isinstance(align, int) or align < 1 or align > 4096 or (align & (align - 1)) != 0:
                    diags.append(Diagnostic(
                        code="dma-align-illegal",
                        tier="Static",
                        subject=Subject("DmaField", {"block": block_name, "buffer": name, "name": fname}),
                        span=file_span(file),
                        message=(
                            f"DMA field {fname!r} has align={align!r}; must be a power of two "
                            f"in [1, 4096]."
                        ),
                        expected="power of two in [1, 4096]",
                        actual=align,
                    ))
                elif offset % align != 0:
                    diags.append(Diagnostic(
                        code="dma-align-unsatisfied",
                        tier="Static",
                        subject=Subject("DmaField", {"block": block_name, "buffer": name, "name": fname}),
                        span=file_span(file),
                        message=(
                            f"DMA field {fname}: offset 0x{offset:02x} not divisible by align {align}."
                        ),
                        expected=f"offset % {align} == 0",
                        actual=f"0x{offset:02x} % {align} = {offset % align}",
                    ))

    return diags


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def check(ir: dict[str, Any], source_path: str = "<memory>",
          ran: set[str] | None = None) -> list[Diagnostic]:
    """Run every static rule in spec/diagnostics/README.md §3 against `ir`.

    Returns a list of `Diagnostic` objects. The list is empty if the
    contract is valid by every rule the checker implements.

    The checker is total: it never raises on a malformed input. Schema
    validation is a separate pass (`_validate_schema`, below); this
    function assumes `ir` is a Python dict of the right shape.

    `ran` (optional) is mutated in place with the names of the rule
    groups that actually executed: "schema-version", "block",
    "registers", "interrupts", "dma". This is the evidence the report
    generator (tools/report/) uses to distinguish "the check ran and
    found nothing" from "the check did not run" — an absent group goes
    into the report's `unknown.static_checks_not_run`, never into
    `static_checks_run` (spec §6.1, docs/guarantees.md §3).
    """
    diags: list[Diagnostic] = []

    diags.extend(_check_schema_version(ir, source_path))
    if ran is not None:
        ran.add("schema-version")

    block = ir.get("block")
    if not isinstance(block, dict):
        diags.append(Diagnostic(
            code="schema-invalid",
            tier="Static",
            subject=Subject("Ir", {"path": source_path}),
            span=file_span(source_path),
            message="contract is missing required 'block' object.",
        ))
        return diags

    diags.extend(_check_block(block, source_path))
    if ran is not None:
        ran.add("block")

    block_name = block.get("name", "<missing>")
    bus_width = block.get("bus_width", 32)
    if not isinstance(bus_width, int) or bus_width not in (8, 16, 32):
        # We still want to run other checks; the bus-width-invalid diag
        # is already in diags. Use a safe default.
        bus_width = 32

    registers = block.get("registers", []) or []
    if registers:
        diags.extend(_check_registers(registers, block_name, bus_width, source_path))
        if ran is not None:
            ran.add("registers")
    interrupts = block.get("interrupts", []) or []
    if interrupts:
        diags.extend(_check_interrupts(interrupts, block, source_path))
        if ran is not None:
            ran.add("interrupts")
    dma = ir.get("dma_buffers", []) or []
    if dma:
        diags.extend(_check_dma(dma, block_name, source_path))
        if ran is not None:
            ran.add("dma")

    return diags


# ---------------------------------------------------------------------------
# Schema validation (uses jsonschema if available, else a no-op)
# ---------------------------------------------------------------------------


def _validate_schema(ir: dict[str, Any], source_path: str) -> list[Diagnostic]:
    """Validate `ir` against the JSON Schema. Emits `schema-invalid` on
    failure. Returns [] if the schema validates."""
    try:
        import jsonschema  # type: ignore
    except ImportError:
        # The checker must work without jsonschema installed; the schema
        # validation is a defence-in-depth pass. The semantic checks
        # below still run.
        return []

    schema_path = (
        pathlib.Path(__file__).resolve().parents[2]
        / "spec" / "contract-schema" / "cancho-hdl-contract.schema.json"
    )
    if not schema_path.exists():
        return []

    schema = json.loads(schema_path.read_text())
    validator = jsonschema.Draft202012Validator(schema)
    errors = list(validator.iter_errors(ir))
    out: list[Diagnostic] = []
    for e in errors:
        out.append(Diagnostic(
            code="schema-invalid",
            tier="Static",
            subject=Subject("Ir", {"path": source_path, "pointer": list(e.absolute_path)}),
            span=file_span(source_path),
            message=f"schema validation failed: {e.message}",
            expected="valid against cancho-hdl-contract.schema.json",
            actual=str(e.message),
        ))
    return out


def check_file(path: str) -> list[Diagnostic]:
    """Load a `.chw` file (JSON wire format or textual contract
    syntax — `load_contract` sniffs which), validate against the
    schema, run every static rule, return the combined list of
    diagnostics."""
    ir, load_diags = load_contract(path)
    if ir is None:
        # A syntax level refusal (parse-error for textual, schema-invalid
        # for a malformed JSON file). The checks below cannot run without
        # an IR; return the load diagnostics unchanged.
        return load_diags

    diags = _validate_schema(ir, path)
    # Always run semantic checks too — schema-invalid IR still gets
    # reported through whatever rules the checker can apply.
    diags.extend(check(ir, source_path=path))
    return diags


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="cancho-hdl check",
        description="Parse and check a .chw contract file against spec/diagnostics/README.md §3.",
    )
    parser.add_argument("files", nargs="+", help="One or more .chw files.")
    parser.add_argument("--output", choices=["text", "json"], default="text")
    args = parser.parse_args()

    total_errors = 0
    for f in args.files:
        diags = check_file(f)
        if args.output == "json":
            for d in diags:
                print(d.to_json())
        else:
            # The text form is derived from the JSON form
            # (spec/diagnostics/README.md §5): one block per
            # diagnostic, rendered by tools/check/text_format.py.
            blocks = [format_diagnostics([d]) for d in diags]
            sys.stdout.write("".join(blocks))
        total_errors += sum(1 for d in diags if d.severity == "Error")

    # Exit codes per spec/diagnostics/README.md and the tools/check README.
    # 0: no errors. 1: at least one error. 2: usage error (caught by argparse).
    sys.exit(0 if total_errors == 0 else 1)