"""Op-script runner for the reference model.

The behavioral roundtrip (tests/behavioral/) drives the *same*
operation script through two engines: this runner (Python, on top
of `reference_model.ReferenceModel` — the authoritative oracle)
and the compiled C harness (which uses the generated c-header as
its storage layout). Their traces must be identical.

The op grammar is deliberately line-oriented so the C harness can
parse it with `sscanf` — no JSON in C:

    R  <reg>              # model.read → OK 0x<hex>
    Rf <reg> <field>      # model.read_field → OK 0x<hex>
    W  <reg> <v>          # model.write → OK
    Wf <reg> <field> <v>  # model.write_field → OK
    D  <reg> <v>          # device_write → OK
    Df <reg> <field> <v>  # device_write_field → OK
    DW <buf> <field> <v>  # dma_write (CPU) → OK
    DX <buf> <field> <v>  # device_dma_write → OK
    DR <buf> <field>      # dma_read → OK 0x<hex>
    RESET                 # model.reset → OK
    IP <intr>             # interrupt_pending → OK 0|1
    PE <intr>             # interrupt_enabled → OK 0|1
    PS <intr>             # interrupt_source_active → OK 0|1
    PC <intr>             # interrupt_clear → OK

Refusals are part of the observable trace: an op the model refuses
emits `ERR <code>` exactly where the model refused. Values parse
with Python's int(s, 0) (0x… or decimal). A trace line is either
`OK` / `OK <value>` or `ERR <code>` — never both.

This runner is engine-agnostic: the future SystemVerilog behavioral
roundtrip reuses both the corpus (tests/behavioral/scenarios.json)
and this trace shape.
"""

from __future__ import annotations

import sys
from typing import Iterator

CALLBACK_OPS = {"IP", "PE", "PS"}


def parse_op(line: str) -> tuple[str, list[str]]:
    parts = line.split()
    if not parts:
        raise ValueError("empty op line")
    return parts[0], parts[1:]


def _val(s: str) -> int:
    return int(s, 0)


def _read_value(fn) -> str:
    return f"OK 0x{fn():08x}"


def run_script(model, script: str | list[str]) -> list[str]:
    """Run `script` against the model; the model is reset first, so
    each scenario starts from the contract reset values (mirrors the
    C harness, which initializes its storage the same way)."""
    model.reset()
    trace: list[str] = []

    for line in _ops(script):
        op, args = parse_op(line)
        run_first_op(op, args, model, trace)
    return trace


def _ops(script: str | list[str]) -> Iterator[str]:
    if isinstance(script, str):
        for raw in script.splitlines():
            if raw.strip():
                yield raw.strip()
    else:
        for raw in script:
            if raw.strip():
                yield raw.strip()


def run_first_op(op: str, args: list[str], model, trace: list[str]) -> None:
    # Each op appends one trace line. Wrapped so refusals surface as
    # `ERR <code>` — the harness must refuse identically.
    try:
        if op == "R":
            trace.append(_read_value(lambda: model.read(args[0])))
        elif op == "Rf":
            trace.append(_read_value(lambda: model.read_field(args[0], args[1])))
        elif op == "W":
            model.write(args[0], _val(args[1]))
            trace.append("OK")
        elif op == "Wf":
            model.write_field(args[0], args[1], _val(args[2]))
            trace.append("OK")
        elif op == "D":
            model.device_write(args[0], _val(args[1]))
            trace.append("OK")
        elif op == "Df":
            model.device_write_field(args[0], args[1], _val(args[2]))
            trace.append("OK")
        elif op == "DW":
            model.dma_write(args[0], args[1], _val(args[2]))
            trace.append("OK")
        elif op == "DX":
            model.device_dma_write(args[0], args[1], _val(args[2]))
            trace.append("OK")
        elif op == "DR":
            trace.append(_read_value(lambda: model.dma_read(args[0], args[1])))
        elif op == "RESET":
            model.reset()
            trace.append("OK")
        elif op in CALLBACK_OPS:
            results = {
                "IP": model.interrupt_pending,
                "PE": model.interrupt_enabled,
                "PS": model.interrupt_source_active,
            }
            trace.append(f"OK {int(results[op](args[0]))}")
        elif op == "PC":
            model.interrupt_clear(args[0])
            trace.append("OK")
        else:
            raise ValueError(f"unknown op {op!r}")
    except Exception as e:
        code = getattr(e, "code", None)
        trace.append(f"ERR {code}" if code else f"ERR? unclassified: {e}")


if __name__ == "__main__":
    print(__doc__)
    sys.exit(2)
