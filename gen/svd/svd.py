"""The `svd` generator (gen/svd/) — CMSIS-SVD XML.

Output contract: `spec/generators/README.md` §6. One `<peripheral>`
per contract block inside a single-`<device>` document, fed to the
ARM tooling surface (cortex-debug, svd2rust, keil-mdk).

What it emits:

- The block name verbatim as the peripheral `<name>` (decision
  recorded in §6.1: the IR has no short-name field, so the
  generator does not invent one; the `chw:` stable-ID comment
  carries the trace to the contract).
- Full SVD-native access mapping (§6.1): `RO` → read-only,
  `WO` → write-only, `RW` → read-write, `W1C`/`W0C`/`W1S`/`W0S`
  → read-write + `modifiedWriteValues`, `RC` → read-write +
  `readAction="clear"` — the same write/read semantics the
  reference simulator enforces (tools/tier judgment in
  §6.3 non-guarantees: CMSIS tools interpret the elements, the
  generator does not verify them).
- `<enumeratedValues>` per enum field, in declaration order.
- `<resetValue>` for every register; an undefined reset becomes
  `0x0` plus a comment naming the absence (§6.2).
- Interrupts and DMA buffers as **comments naming their stable
  IDs**, never as `<interrupt>` / register elements (§6.3: CMSIS-SVD
  interrupts are board-level; DMA descriptors are not part of a
  peripheral register map).
- An undefined-reescape/DMA presence is documented, not degraded:
  a zero-register block is refused (`generator-unimplemented`),
  same as the devicetree generator.

Deterministic: same IR → byte-identical output. Names are
XML-escaped; a name containing `--` is refused (it cannot appear
inside an XML comment) — the roundtrip XSD would reject most such
names anyway; the generator refuses first so the artifact never
ships half-escaped.

Validates against the vendored `spec/generators/CMSIS-SVD.xsd`
(schema 1.3, ARM license header) in
`tests/roundtrip/svd_validates.py` when lxml is available; the
structural checks run everywhere.
"""

from __future__ import annotations

import pathlib as _pathlib
import sys as _sys
from typing import Any

# Module loaded by path (no package); gen/ must be importable for
# the shared refusal class (same discipline as the other generators).
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[1]))
from common import GeneratorUnimplemented


_IN = "  "          # two-space XML indent, per the §6.1 sketch
_ATTR = "xmlns:xs=\"http://www.w3.org/2001/XMLSchema-instance\""

# §6.1 access mapping. (access, modifiedWriteValues, readAction):
# exactly the semantics the reference model enforces at runtime.
_ACCESS_MAP: dict[str, tuple[str, str | None, str | None]] = {
    "RO":  ("read-only",   None,          None),
    "WO":  ("write-only",  None,          None),
    "RW":  ("read-write",  None,          None),
    "RC":  ("read-write",  None,          "clear"),
    "W0C": ("read-write",  "zeroToClear", None),
    "W0S": ("read-write",  "zeroToSet",   None),
    "W1C": ("read-write",  "oneToClear",  None),
    "W1S": ("read-write",  "oneToSet",    None),
}


def _xml(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _xml_attr(s: str) -> str:
    return _xml(s).replace('"', "&quot;")


def _comment_safe(s: str) -> str:
    if "--" in s:
        raise GeneratorUnimplemented(
            f"stable-ID component {s!r} contains '--', which a legal XML "
            "comment cannot carry; refusing, not substituting")
    return s


def _sid(*parts: str) -> str:
    """Stable ID: _sid('UartRegs','register','CTRL') → 'chw:UartRegs.register.CTRL'."""
    return _comment_safe("chw:" + ".".join(parts))


def _hex(value: int) -> str:
    return f"0x{value:X}"


def _reset_hex(value: int, bus_width: int) -> str:
    return f"0x{value:0{bus_width // 4}X}"


def _register_access(kind: str) -> tuple[str, str, str]:
    """The access-mapping XML lines for a register: the `<access>`
    line (which must appear before `<resetValue>` inside the
    registerPropertiesGroup sequence), and the optional
    `<modifiedWriteValues>` / `<readAction>` lines (which must
    appear after it). Raises on a kind with no CMSIS-SVD mapping."""
    if kind not in _ACCESS_MAP:
        raise GeneratorUnimplemented(
            f"access kind {kind!r} has no CMSIS-SVD mapping")
    access, mwv, ra = _ACCESS_MAP[kind]
    access_line = f"<access>{access}</access>"
    mwv_line = f"<modifiedWriteValues>{mwv}</modifiedWriteValues>" if mwv else None
    ra_line = f"<readAction>{ra}</readAction>" if ra else None
    return access_line, mwv_line, ra_line


def _field_access(kind: str) -> str:
    """The field-level `<access>` value (plain; the register-level
    modifiedWriteValues/readAction cover the write semantics)."""
    return _ACCESS_MAP[kind][0]


def generate(ir: dict[str, Any], source_path: str = "<memory>") -> str:
    block = ir["block"]
    block_name: str = _comment_safe(str(block["name"]))
    bus_width: int = int(block.get("bus_width", 32))
    base: int = int(str(block["base_address"]), 16)
    version: str = str(ir.get("version", "0.1.0"))
    registers = block.get("registers", []) or []
    if not registers:
        raise GeneratorUnimplemented(
            "SVD peripheral with zero registers: <registers> requires at "
            "least one register; declare at least one")

    src = _comment_safe(str(source_path))
    banner = _comment_safe(f"Generated by cancho-hdl from {src}. Do not edit.")

    o: list[str] = []
    o.append('<?xml version="1.0" encoding="utf-8"?>')
    o.append(f"<!-- {banner} -->")
    o.append(
        f'<device schemaVersion="1.0" {_ATTR} '
        f'xs:noNamespaceSchemaLocation="CMSIS-SVD.xsd">')

    # -- device ------------------------------------------------------
    ind = _IN
    o.append(f"{ind}<!-- {_sid(block_name)} -->")
    o.append(f"{ind}<name>{_xml(block_name)}</name>")
    o.append(f"{ind}<version>{_xml(version)}</version>")
    o.append(
        f"{ind}<description>Register map generated by cancho-hdl "
        f"from {src}.</description>")
    o.append(f"{ind}<addressUnitBits>8</addressUnitBits>")
    o.append(f"{ind}<width>{bus_width}</width>")

    # -- peripherals / peripheral ------------------------------------
    o.append(f"{ind}<peripherals>")
    pin = _IN * 2
    o.append(f"{pin}<peripheral>")
    rin = _IN * 3
    o.append(f"{rin}<!-- {_sid(block_name)} -->")
    o.append(f"{rin}<name>{_xml(block_name)}</name>")
    o.append(f"{rin}<baseAddress>{_hex(base)}</baseAddress>")
    o.append(f"{rin}<size>{bus_width}</size>")

    # §6.3: no <interrupt> elements — board-level here. Comments name IDs.
    interrupts = block.get("interrupts", []) or []
    # §6 lane: DMA descriptors are not register-map content; name them.
    dma_buffers = ir.get("dma_buffers", []) or []
    if interrupts:
        o.append(f"{rin}<!-- interrupts are board-level in CMSIS-SVD and are "
                 "not emitted as <interrupt> elements (spec/generators README §6.3) -->")
        for intr in interrupts:
            sid = _sid(block_name, "interrupt", str(intr["name"]))
            o.append(f"{rin}<!-- {sid}, IRQ {intr['number']} -->")
    if dma_buffers:
        o.append(f"{rin}<!-- DMA buffers are not part of the peripheral "
                 "register map; named by stable ID -->")
        for buf in dma_buffers:
            o.append(f"{rin}<!-- {_sid(block_name, 'dma', buf['name'])} -->")

    o.append(f"{rin}<registers>")

    # -- registers ---------------------------------------------------
    for reg in sorted(registers, key=lambda r: int(str(r["offset"]), 16)):
        rname = _comment_safe(str(reg["name"]))
        kind = str(reg["kind"])
        offset = int(str(reg["offset"]), 16)
        fields = reg.get("fields", []) or []
        rin2 = _IN * 4
        fin = _IN * 5
        o.append(f"{rin2}<register>")
        o.append(f"{rin2}  <name>{_xml(rname)}</name>  "
                 f"<!-- {_sid(block_name, 'register', rname)} -->")
        o.append(f"{rin2}  <addressOffset>{_hex(offset)}</addressOffset>")
        access_line, mwv_line, ra_line = _register_access(kind)
        o.append(f"{rin2}  {access_line}")
        if "reset" in reg:
            reset = int(str(reg["reset"]), 16)
            o.append(f"{rin2}  <resetValue>{_reset_hex(reset, bus_width)}</resetValue>")
        else:
            # §6.2: undefined reset is emitted, not omitted — 0x0 plus
            # a comment naming the absence so the artifact stays loud.
            o.append(f"{rin2}  <!-- reset undefined in the contract; emitting 0x0 per §6.2 -->")
            o.append(f"{rin2}  <resetValue>0x0</resetValue>")
        # modifiedWriteValues / readAction are AFTER the registerPropertiesGroup.
        if mwv_line is not None:
            o.append(f"{rin2}  {mwv_line}")
        if ra_line is not None:
            o.append(f"{rin2}  {ra_line}")
        if fields:
            o.append(f"{rin2}  <fields>")
            for f in fields:
                fname = _comment_safe(str(f["name"]))
                lsb, msb = int(f["lsb"]), int(f["msb"])
                o.append(f"{fin}<field>")
                o.append(f"{fin}  <name>{_xml(fname)}</name>  "
                         f"<!-- {_sid(block_name, 'register', rname, 'field', fname)} -->")
                o.append(f"{fin}  <lsb>{lsb}</lsb><msb>{msb}</msb>")
                access = _ACCESS_MAP[kind][0]
                o.append(f"{fin}  <access>{access}</access>")
                if "enum" in f:
                    o.append(f"{fin}  <enumeratedValues>")
                    for label, value in f["enum"].items():
                        label = _comment_safe(label)
                        o.append(f"{fin}    <enumeratedValue>")
                        o.append(f"{fin}      <name>{_xml(label)}</name>")
                        o.append(f"{fin}      <value>{int(value)}</value>")
                        o.append(f"{fin}    </enumeratedValue>")
                    o.append(f"{fin}  </enumeratedValues>")
                o.append(f"{fin}</field>")
            o.append(f"{rin2}  </fields>")
        o.append(f"{rin2}</register>")
    o.append(f"{rin}</registers>")
    o.append(f"{pin}</peripheral>")
    o.append(f"{ind}</peripherals>")
    o.append("</device>")
    return "\n".join(o) + "\n"


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(
        prog="cancho-hdl generate --target svd",
        description="Generate a CMSIS-SVD XML file from a .chw contract.",
    )
    ap.add_argument("file", help="A .chw file (JSON wire format).")
    args = ap.parse_args()

    p = _pathlib.Path(args.file)
    ir = json.loads(p.read_text())
    _sys.stdout.write(generate(ir, source_path=str(p)))
