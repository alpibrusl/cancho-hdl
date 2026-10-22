"""The C-side behavioral roundtrip: generated header vs reference model.

For each valid example contract used by the corpus
(`tests/behavioral/scenarios.json`, mirroring the 11 Python scenarios
step for step):

1. Generate the c-header into a temp dir with the PRODUCT (`chw generate FILE --target c-header`, the binary named on the
   command line; the artifact under test).
2. Emit `<block>_wiring.h` from the same IR: semantic tables (access
   kinds, field ranges, enum membership, DMA owners/sizes, interrupt
   linkages), the storage instances binding the header's member names,
   the reset-macro switch, the bitfield-member accessors, and — as
   `_Static_assert` lines — one per register and one per DMA field
   pinning the header's `offsetof` to the contract's offsets. The
   wiring carries names and semantics only; any mismatch with the
   generated header is a compile error, never a wrong trace.
3. Compile `tests/behavioral/c_device.c` with gcc and clang
   (`-Wall -Wextra -Werror -std=c11`), the same discipline the
   c-header roundtrip uses.
4. Run the harness with the scenario's op lines on stdin; run the
   same ops through the reference model (`oracle/legacy/tools/sim/op_runner.py`);
   the traces must be identical line by line — refusals included.

What this pins (and what it does not): the generated header's
*encoding* — offsets via static asserts, field layout and reset
macros via the accessor ops, DMA field layout via asserts and the
packed structs — behaves identically to the reference model on the
corpus. The engine's semantics port is a fixture, not generated;
the SystemVerilog behavioral roundtrip (Verilator or cocotb)
remains the generated-RTL half of the same criterion.

Run from anywhere:
    python3 tests/behavioral/c_behavior.py /path/to/built/chw
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
for _p in (ROOT / "oracle" / "legacy" / "gen", ROOT / "oracle" / "legacy" / "tools" / "parse", ROOT / "oracle" / "legacy" / "tools" / "sim"):
    sys.path.insert(0, str(_p))

from parser import load_contract  # noqa: E402
from reference_model import ReferenceModel  # noqa: E402
from op_runner import run_script  # noqa: E402

# Only the two name helpers of the oracle generator are used below (the C names the wiring must spell); the header
# under test is the product's. oracle/legacy/gen/c-header/c_header.py loads by spec (its directory has a dash,
# so a plain sys.path import cannot name it) — the same discipline
# as the roundtrip suites.
_ch_spec = importlib.util.spec_from_file_location(
    "cancho_hdl_beh_c_header", ROOT / "oracle" / "legacy" / "gen" / "c-header" / "c_header.py")
_ch_mod = importlib.util.module_from_spec(_ch_spec)
_ch_spec.loader.exec_module(_ch_mod)
_to_lower_snake = _ch_mod._to_lower_snake
_to_c_name = _ch_mod._to_c_name

_FAILS: list[str] = []
_KINDS = {"RO": 0, "WO": 1, "RW": 2, "RC": 3, "W1C": 4, "W0C": 5, "W1S": 6, "W0S": 7}


def expect(cond: bool, label: str, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {label}")
    if not cond:
        if detail:
            print(detail)
        _FAILS.append(label)


def _role_lines(intdef: dict, reg_ids: dict[str, int],
                fld_of: dict[tuple[str, str], int],
                role: str, comment: str, emit_line) -> None:
    obj = intdef.get(role)
    if obj is None:
        emit_line(f"      -1, -1,  /* {comment}: not declared */")
        return
    emit_line(f"      {reg_ids[obj['register']]}, "
              f"{fld_of[(obj['register'], obj['field'])]},  /* {comment} */")


def emit_wiring(ir: dict, header_name: str) -> str:
    """Emit `<block>_wiring.h` oxide-friendly: semantic tables from the
    IR plus the storage binding to the generated header's members."""
    block = ir["block"]
    bname = block["name"]
    bsnk = _to_lower_snake(bname)
    wcname = _to_c_name(bname)
    bus = int(block.get("bus_width", 32))
    regs = sorted(block["registers"], key=lambda r: int(str(r["offset"]), 16))
    dma_bufs = ir.get("dma_buffers", []) or []
    ints = block.get("interrupts", []) or []

    reg_ids = {r["name"]: i for i, r in enumerate(regs)}
    fld_of: dict[tuple[str, str], int] = {}
    for r in regs:
        for fi, f in enumerate(r.get("fields", []) or []):
            fld_of[(r["name"], f["name"])] = fi

    o: list[str] = []
    a = o.append
    a(f"/* {bsnk}_wiring.h — emitted by tests/behavioral/c_behavior.py from")
    a("   the SAME IR that produced the c-header included below.")
    a("   Tables (kinds/ranges/enums/owners/linkages) are IR semantics;")
    a("   every storage member reference must resolve against the ")
    a("   generated header — a mismatch is a compile error, never a")
    a("   silently-wrong trace. Static asserts pin header offsets to")
    a("   contract offsets. */")
    a(f"#define BUS_WIDTH {bus}")
    a(f"#define WBLOCK_T {bsnk}_t")
    a(f'#include "{header_name}"')
    a("#include <stdint.h>")
    a("#include <stddef.h>")
    a("#include <string.h>")
    a("")
    a("enum { K_RO=0, K_WO=1, K_RW=2, K_RC=3, K_W1C=4, K_W0C=5, K_W1S=6, K_W0S=7 };")
    a("enum { OWN_CPU=0, OWN_DEVICE=1 };")
    a("typedef struct { const char *name; int lsb; int msb; int enum_n;")
    a("                 const uint32_t *enumv; } FDesc;")
    a("typedef struct { const char *name; int owner; int size; } DmaFDesc;")
    a("typedef struct { int st_reg, st_fld, en_reg, en_fld,")
    a("                  src_reg, src_fld, clr_reg, clr_fld, clr_kind; } IntrDesc;")
    a("")
    # register ids + names + kinds
    a("enum {")
    for i, r in enumerate(regs):
        a(f"    R_{r['name'].upper()} = {i},")
    a(f"    N_REGS = {len(regs)}")
    a("};")
    a("")
    a("static const char *const REG_NAMES[] = {")
    for r in regs:
        a(f'    "{r["name"]}",')
    a("};")
    a("")
    a("static const uint8_t REG_KIND[] = {")
    for r in regs:
        a(f"    {_KINDS[r['kind']]},  /* {r['name']}: {r['kind']} */")
    a("};")
    a("")
    # storage (generated header's block struct) + word table
    a(f"static {bsnk}_t reg_file;")
    a("")
    a("static volatile uint32_t *const REG_WORD_TABLE[] = {")
    for r in regs:
        a(f"    &reg_file.{r['name'].lower()},")
    a("};")
    a("")
    # resets from the generated header's macros (0 where undefined in IR)
    a("static uint32_t reg_reset(int r) {")
    a("    switch (r) {")
    for i, r in enumerate(regs):
        rv = r.get("reset")
        if rv is not None:
            a(f"    case {i}: return {wcname}_{_to_c_name(r['name'])}_RESET;")
        else:
            a(f"    case {i}: return 0;  /* reset undefined in the contract */")
    a("    default: return 0;")
    a("    }")
    a("}")
    # field tables
    for i, r in enumerate(regs):
        fields = r.get("fields", []) or []
        for f in fields:
            if "enum" in f:
                vals = ", ".join(str(int(v)) for v in f["enum"].values())
                a(f"static const uint32_t ENUMV_{i}_{f['name'].upper()}[] "
                  f"= {{ {vals} }};")
        a(f"static const FDesc FIELDS_{i}[] = {{")
        for f in fields:
            if "enum" in f:
                en = f"ENUMV_{i}_{f['name'].upper()}"
                n = str(len(f["enum"]))
            else:
                en, n = "0", "0"
            a(f'    {{ "{f["name"]}", {f["lsb"]}, {f["msb"]}, {n}, {en} }},')
        a("};")
    a("")
    a("static const FDesc *const FIELD_TABLES[] = {")
    for i in range(len(regs)):
        a(f"    FIELDS_{i},")
    a("};")
    a("")
    a("static const int FIELD_COUNTS[] = {")
    for r in regs:
        a(f"    {len(r.get('fields', []) or [])},")
    a("};")
    a("")
    # static asserts: header offsets == contract offsets
    a("/* Offsets: the generated layout cannot drift from the contract. */")
    for r in regs:
        off = int(str(r["offset"]), 16)
        a(f'_Static_assert(offsetof(WBLOCK_T, {r["name"].lower()}) == {off},')
        a(f'               "register {r["name"]} offset drift");')
    # DMA buffers
    for buf in dma_bufs:
        dsnk = _to_lower_snake(buf["name"])
        fields = buf.get("fields", []) or []
        a("")
        a(f"static {dsnk}_t {dsnk.lower()};")
        for f in fields:
            off = int(str(f["offset"]), 16)
            a(f"_Static_assert(offsetof({dsnk}_t, {f['name'].lower()}) == {off},")
            a(f'               "DMA field {buf["name"]}.{f["name"]} offset drift");')
        a(f"static const DmaFDesc DMAF_{buf['name'].upper()}[] = {{")
        for f in fields:
            owner = "OWN_DEVICE" if f.get("owner") == "DEVICE" else "OWN_CPU"
            a(f'    {{ "{f["name"]}", {owner}, {int(f.get("size", 4))} }},')
        a("};")
        a(f"static volatile void *const DMAFP_{buf['name'].upper()}[] = {{")
        for f in fields:
            a(f"    &{dsnk.lower()}.{f['name'].lower()},")
        a("};")
    a("")
    a(f"enum {{ N_DMA = {len(dma_bufs)} }};")
    a("")
    a("static const char *const DMA_NAMES[] = {")
    for b in dma_bufs:
        a(f'    "{b["name"]}",')
    a("};")
    a("")
    a("static const DmaFDesc *const DMA_FIELD_DESCS[] = {")
    for b in dma_bufs:
        a(f"    DMAF_{b['name'].upper()},")
    a("};")
    a("")
    a("static volatile void *const *const DMA_FIELD_PTRS[] = {")
    for b in dma_bufs:
        a(f"    DMAFP_{b['name'].upper()},")
    a("};")
    a("")
    a("static const int DMA_FIELD_COUNTS[] = {")
    for b in dma_bufs:
        a(f"    {len(b.get('fields', []) or [])},")
    a("};")
    a("")
    a("static void dma_zero(void) {")
    for b in dma_bufs:
        dsnk = _to_lower_snake(b["name"])
        a(f"    memset(&{dsnk.lower()}, 0, sizeof({dsnk.lower()}));")
    a("}")
    a("")
    # bitfield overlay: field RMW through the generated header's
    # per-register view typedef (e.g. `ctrl_t`), cast onto the block
    # struct's word member — exactly how a real driver binds the view
    # struct to its register window. The compiler's masking/positioning
    # IS the header's field layout, exercised at runtime.
    a("static void bf_write(int r, int f, uint32_t v) {")
    a("    switch (r) {")
    for i, r in enumerate(regs):
        fields = r.get("fields", []) or []
        if not fields:
            continue
        view = f"{_to_lower_snake(r['name'])}_t"
        rm = r["name"].lower()
        a(f"    case {i}: {{  /* {r['name']}, view {view} */")
        a(f"        {view} *view = ({view} *)&reg_file.{rm};")
        a("        switch (f) {")
        for fi, f in enumerate(fields):
            a(f"        case {fi}: view->{f['name'].lower()} = v; return;")
        a("        default: return;")
        a("        }")
        a("    }")
    a("    default: return;")
    a("    }")
    a("}")
    a("")
    # interrupts
    a(f"enum {{ N_INTS = {len(ints)} }};")
    a("")
    a("static const char *const INTR_NAMES[] = {")
    for i in ints:
        a(f'    "{i["name"]}",')
    a("};")
    a("")
    a("static const IntrDesc INTRS[] = {")
    for i in ints:
        a("    {")
        for role in ("status", "enable", "source", "clear"):
            _role_lines(i, reg_ids, fld_of, role, role, a)
        c = i.get("clear") or {}
        a(f"      {_KINDS[c.get('kind', 'W1C')]},  /* clear kind */")
        a("    },")
    a("};")
    return "\n".join(o) + "\n"


def main() -> int:
    print("== C-side behavioral roundtrip (generated header vs reference model) ==")
    corpus_path = ROOT / "tests" / "behavioral" / "scenarios.json"
    if not corpus_path.exists():
        expect(False, "corpus exists", str(corpus_path))
        return 1
    corpus = json.loads(corpus_path.read_text())
    scenarios = corpus["scenarios"]
    expect(bool(scenarios), "corpus non-empty")

    if len(sys.argv) < 2:
        expect(False, "the built chw binary is named on the command line")
        return 1
    chw = sys.argv[1]

    def generate_header(cpath: str) -> str:
        proc = subprocess.run([chw, "generate", cpath, "--target", "c-header"], capture_output=True, text=True,
                              cwd=str(ROOT))
        expect(proc.returncode == 0, f"{cpath}: chw generate --target c-header", proc.stderr[:400])
        return proc.stdout

    with tempfile.TemporaryDirectory(prefix="c-behavior-") as td:
        tmp = pathlib.Path(td)
        built: dict[str, str] = {}   # contract path → executable
        for s in scenarios:
            cpath = s["contract"]
            if cpath in built:
                continue
            ir, _ = load_contract(str(ROOT / cpath))
            header_src = generate_header(str(cpath))
            header_name = f"{_to_lower_snake(ir['block']['name'])}.h"
            wiring_name = f"{_to_lower_snake(ir['block']['name'])}_wiring.h"
            wiring_src = emit_wiring(ir, header_name)
            expect(emit_wiring(ir, header_name) == wiring_src,
                   f"{cpath}: wiring emitter deterministic")
            (tmp / header_name).write_text(header_src)
            (tmp / wiring_name).write_text(wiring_src)
            exe = tmp / ("c_device_" + _to_lower_snake(ir["block"]["name"]))
            built[cpath] = str(exe)
            for cc in ("gcc", "clang"):
                cmd = [cc, "-Wall", "-Wextra", "-Werror", "-std=c11",
                       f"-DWIRING=\"{wiring_name}\"",
                       "-I", str(tmp),
                       "-I", str(ROOT / "tests" / "behavioral"),
                       str(ROOT / "tests" / "behavioral" / "c_device.c"),
                       "-o", str(exe)]
                proc = subprocess.run(cmd, capture_output=True, text=True)
                expect(proc.returncode == 0,
                       f"{cpath}: compiles under {cc} (-Wall -Wextra -Werror)",
                       (proc.stdout + proc.stderr)[:1500])

        for s in scenarios:
            cpath = s["contract"]
            exe = built[cpath]
            ops = s["ops"]
            script = "\n".join(ops) + "\n"
            m = ReferenceModel.from_chw_file(str(ROOT / cpath))
            model_trace = run_script(m, ops)
            proc = subprocess.run([exe], input=script,
                                  capture_output=True, text=True)
            c_trace = proc.stdout.splitlines()
            ok = (proc.returncode == 0
                  and len(c_trace) == len(model_trace)
                  and c_trace == model_trace)
            detail = ""
            if not ok:
                lines = []
                for i, (op, mt, ct) in enumerate(zip(
                        ops, (model_trace + ["<missing>"] * len(ops)),
                        (c_trace + ["<missing>"] * len(ops)))):
                    if mt != ct:
                        lines.append(f"    op {i} {op!r}\n"
                                     f"      C:     {ct}\n"
                                     f"      model: {mt}")
                if not lines:
                    lines.append(f"    C rc={proc.returncode} "
                                 f"stderr={proc.stderr[:400]!r}")
                detail = "\n".join(lines)
            expect(ok, f"{s['name']}: C trace == model trace ({len(ops)} ops)",
                   detail)

        # --- negative lane: seeded drift MUST diverge -------------------
        # The roundtrip is only evidence if it can fail. Perturb the
        # wiring in two ways that a real spec/header mismatch would
        # take — a wrong reset value and a wrong field position — and
        # check the trace comparison flags each one. (gcc only; the
        # point is the oracle, not the compiler matrix.)
        uart_contract = next(
            s["contract"] for s in scenarios if s["name"] == "uart/rw_basic")
        ir, _ = load_contract(str(ROOT / uart_contract))
        header_name = f"{_to_lower_snake(ir['block']['name'])}.h"
        wiring_src = emit_wiring(ir, header_name)
        wcname = _to_c_name(ir["block"]["name"])
        for tag, needle, repl, probe in (
            ("reset-macro drift",
             f"return {wcname}_{_to_c_name('CTRL')}_RESET;",
             "return 0x1;",
             ["R CTRL"]),
            ("field-position drift",
             '"BAUD_DIV", 8,',
             '"BAUD_DIV", 9,',
             ["Wf CTRL BAUD_DIV 128", "Rf CTRL BAUD_DIV", "R CTRL"]),
        ):
            bad = wiring_src.replace(needle, repl, 1)
            if bad == wiring_src:
                expect(False, f"negative lane ({tag}): seed needle found",
                       f"needle {needle!r} did not match emitted wiring")
                continue
            (tmp / "uart_wiring_bad.h").write_text(bad)
            exe_bad = tmp / "c_device_bad"
            proc = subprocess.run(
                ["gcc", "-Wall", "-Wextra", "-Werror", "-std=c11",
                 '-DWIRING="uart_wiring_bad.h"',
                 "-I", str(tmp), "-I", str(ROOT / "tests" / "behavioral"),
                 str(ROOT / "tests" / "behavioral" / "c_device.c"),
                 "-o", str(exe_bad)], capture_output=True, text=True)
            mt = run_script(ReferenceModel.from_chw_file(str(ROOT / uart_contract)),
                            probe)
            ct: list[str] = []
            if proc.returncode == 0:
                pr = subprocess.run([str(exe_bad)],
                                    input="\n".join(probe) + "\n",
                                    capture_output=True, text=True)
                ct = pr.stdout.splitlines()
            caught = (proc.returncode == 0
                      and len(ct) == len(mt) and ct != mt)
            expect(caught, f"negative lane: {tag} → divergence detected",
                   f"compile: {proc.stderr[:400]!r}\n    C={ct}\n    model={mt}")

    print()
    if _FAILS:
        print(f"== C behavioral roundtrip: {len(_FAILS)} failure(s) ==")
        return 1
    print("== C behavioral roundtrip: all pass ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
