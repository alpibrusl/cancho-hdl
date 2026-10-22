"""cancho-hdl reference model.

A behavioural oracle for the contract IR defined in
spec/contract-schema/README.md. Consumes a `.chw` file and
behaves as a memory-mapped peripheral would, enforcing:

- register access kinds (RO / WO / RW / RC / W1C / W0C / W1S / W0S)
- field bit-range decoding
- field enum storage and retrieval
- DMA buffer field ownership (CPU vs DEVICE)
- interrupt lifecycle (source / enable / status / clear)
- reset values

Tier: Runtime. See oracle/legacy/tools/sim/README.md.

Usage:

    from reference_model import ReferenceModel, AccessError

    model = ReferenceModel.from_chw_file("examples/uart-contract/uart.chw")
    model.write_field("CTRL", "ENABLE", 1)
    assert model.read_field("CTRL", "ENABLE") == 1
"""

from __future__ import annotations

import json
import pathlib
import sys
from dataclasses import dataclass, field
from typing import Any

# Make the shared diagnostic module importable when this file is
# imported from oracle/legacy/tools/sim/run_scenarios.py or from the conformance suite.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from check.diagnostic import Diagnostic, Subject  # noqa: E402


# ---------------------------------------------------------------------------
# Exceptions raised by the model. Each maps to a diagnostic code so the
# scenarios can assert behaviour without parsing strings.
# ---------------------------------------------------------------------------


class AccessError(Exception):
    """Raised when the contract's access semantics are violated at runtime."""

    def __init__(self, code: str, message: str, subject: Subject | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.subject = subject
        self.diagnostic = Diagnostic(
            code=code, tier="Runtime", subject=subject, message=message
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_hex(s: str) -> int:
    """Parse a 0x... literal. The Phase 0 schema mandates the '0x' prefix."""
    if not isinstance(s, str) or not s.startswith("0x"):
        raise ValueError(f"expected 0x hex literal, got {s!r}")
    return int(s, 16)


def _mask(bus_width: int) -> int:
    return (1 << bus_width) - 1


def _field_mask(lsb: int, msb: int) -> int:
    width = msb - lsb + 1
    return ((1 << width) - 1) << lsb


# ---------------------------------------------------------------------------
# In-memory model
# ---------------------------------------------------------------------------


class ReferenceModel:
    """Behavioural reference model for one register block + DMA buffers."""

    def __init__(self, ir: dict[str, Any]):
        self.ir = ir
        block = ir["block"]
        self.block_name: str = block["name"]
        self.bus_width: int = block["bus_width"]
        self.endianness: str = block["endianness"]

        # Indexed views
        self.registers: dict[str, dict[str, Any]] = {
            r["name"]: r for r in block["registers"]
        }
        self.interrupts: dict[str, dict[str, Any]] = {
            i["name"]: i for i in block.get("interrupts", [])
        }
        self.dma_buffers: dict[str, dict[str, Any]] = {
            b["name"]: b for b in ir.get("dma_buffers", [])
        }

        # Index fields by register
        self._fields_by_register: dict[str, dict[str, dict[str, Any]]] = {}
        for reg_name, reg in self.registers.items():
            self._fields_by_register[reg_name] = {
                f["name"]: f for f in reg.get("fields", [])
            }

        # Live state
        self._reg_state: dict[str, int] = {}
        self._dma_state: dict[tuple[str, str], int] = {}

        # Apply reset
        self.reset()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_chw_file(cls, path: str | pathlib.Path) -> "ReferenceModel":
        with open(path, "r", encoding="utf-8") as f:
            return cls(json.load(f))

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Apply reset values to all registers. DMA buffers are zeroed."""
        self._reg_state = {}
        for reg_name, reg in self.registers.items():
            if "reset" in reg:
                self._reg_state[reg_name] = _parse_hex(reg["reset"]) & _mask(self.bus_width)
            else:
                self._reg_state[reg_name] = 0
        self._dma_state = {}
        for buf_name, buf in self.dma_buffers.items():
            for f in buf["fields"]:
                self._dma_state[(buf_name, f["name"])] = 0

    # ------------------------------------------------------------------
    # Field helpers
    # ------------------------------------------------------------------

    def _check_field(self, register_name: str, field_name: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if register_name not in self.registers:
            raise AccessError(
                "runtime-register-unknown",
                f"register {register_name!r} does not exist in block {self.block_name!r}",
                subject=Subject("Register", {"block": self.block_name, "name": register_name}),
            )
        fields = self._fields_by_register[register_name]
        if field_name not in fields:
            raise AccessError(
                "runtime-field-unknown",
                f"field {field_name!r} does not exist in register {register_name!r}",
                subject=Subject(
                    "Field",
                    {
                        "block": self.block_name,
                        "register": register_name,
                        "name": field_name,
                    },
                ),
            )
        return self.registers[register_name], fields[field_name]

    def _encode_field(self, fdef: dict[str, Any], value: int) -> int:
        width = fdef["msb"] - fdef["lsb"] + 1
        if value < 0 or value >= (1 << width):
            raise AccessError(
                "runtime-field-value-overflow",
                f"value {value} does not fit in field {fdef['name']!r} (width {width})",
                subject=Subject(
                    "Field",
                    {
                        "block": self.block_name,
                        "register": "<encode>",
                        "name": fdef["name"],
                    },
                ),
            )
        if "enum" in fdef:
            allowed = set(fdef["enum"].values())
            if value not in allowed:
                # The schema catches this statically. Runtime check is a
                # backstop; downgrade to a warning rather than refuse? For
                # Phase 0 we refuse — generators that emit enum constants
                # are the expected path.
                raise AccessError(
                    "runtime-field-enum-violation",
                    f"value {value} is not a member of enum on field {fdef['name']!r}",
                    subject=Subject(
                        "Field",
                        {
                            "block": self.block_name,
                            "register": "<encode>",
                            "name": fdef["name"],
                        },
                    ),
                )
        return value << fdef["lsb"]

    def _decode_field(self, fdef: dict[str, Any], reg_value: int) -> int:
        mask = _field_mask(fdef["lsb"], fdef["msb"])
        return (reg_value & mask) >> fdef["lsb"]

    # ------------------------------------------------------------------
    # Register read / write
    # ------------------------------------------------------------------

    def read(self, register_name: str) -> int:
        reg = self.registers.get(register_name)
        if reg is None:
            raise AccessError(
                "runtime-register-unknown",
                f"register {register_name!r} does not exist",
                subject=Subject("Register", {"block": self.block_name, "name": register_name}),
            )
        kind = reg["kind"]
        if kind == "WO":
            raise AccessError(
                "runtime-access-kind-violation",
                f"read of write-only register {register_name!r}",
                subject=Subject("Register", {"block": self.block_name, "name": register_name}),
            )
        # RC: read returns the value, then clears it (single-step model).
        value = self._reg_state[register_name]
        if kind == "RC":
            self._reg_state[register_name] = 0
        return value

    def read_field(self, register_name: str, field_name: str) -> int:
        reg, fdef = self._check_field(register_name, field_name)
        return self._decode_field(fdef, self.read(register_name))

    def write(self, register_name: str, value: int) -> None:
        value &= _mask(self.bus_width)
        reg = self.registers.get(register_name)
        if reg is None:
            raise AccessError(
                "runtime-register-unknown",
                f"register {register_name!r} does not exist",
                subject=Subject("Register", {"block": self.block_name, "name": register_name}),
            )
        kind = reg["kind"]
        if kind == "RO":
            raise AccessError(
                "runtime-access-kind-violation",
                f"write of read-only register {register_name!r}",
                subject=Subject("Register", {"block": self.block_name, "name": register_name}),
            )
        if kind == "WO":
            # Write-only: full replacement. Field decode happens on read (none).
            self._reg_state[register_name] = value
            return
        if kind in ("RW", "RC"):
            self._reg_state[register_name] = value
            return
        if kind in ("W1C", "W0C", "W1S", "W0S"):
            # Bitwise modify: write 1 clears/sets the corresponding bit.
            current = self._reg_state[register_name]
            if kind == "W1C":
                new = current & ~value
            elif kind == "W0C":
                new = current & value
            elif kind == "W1S":
                new = current | value
            else:  # W0S
                new = current & ~value
            self._reg_state[register_name] = new & _mask(self.bus_width)
            return
        raise AccessError(
            "runtime-access-kind-unknown",
            f"unknown access kind {kind!r} on register {register_name!r}",
            subject=Subject("Register", {"block": self.block_name, "name": register_name}),
        )

    def write_field(self, register_name: str, field_name: str, value: int) -> None:
        """Read-modify-write a single field. Honors read-modify-write semantics."""
        reg, fdef = self._check_field(register_name, field_name)
        kind = reg["kind"]
        if kind in ("RO",):
            raise AccessError(
                "runtime-access-kind-violation",
                f"write of field {field_name!r} in read-only register {register_name!r}",
                subject=Subject(
                    "Field",
                    {
                        "block": self.block_name,
                        "register": register_name,
                        "name": field_name,
                    },
                ),
            )
        encoded = self._encode_field(fdef, value)
        mask = _field_mask(fdef["lsb"], fdef["msb"])
        # For W1C / W0C / W1S / W0S, the contract is on the full register,
        # not on a field. We treat write_field as "write the field with the
        # given bits set as the action value in their position".
        if kind in ("W1C", "W0C", "W1S", "W0S"):
            # value is the bit pattern for the field. Encode it to its
            # position, then apply the access semantics.
            action_value = encoded  # full register value with only this field's bits set
            current = self._reg_state[register_name]
            if kind == "W1C":
                new = current & ~action_value
            elif kind == "W0C":
                new = current & action_value
            elif kind == "W1S":
                new = current | action_value
            else:  # W0S
                new = current & ~action_value
            self._reg_state[register_name] = new & _mask(self.bus_width)
            return
        # RW / RC / WO: read-modify-write the field's bits, leave the rest.
        current = self._reg_state[register_name]
        # For WO, "reading" the current state is undefined; treat as 0.
        if kind == "WO":
            current = 0
        new = (current & ~mask) | encoded
        self._reg_state[register_name] = new & _mask(self.bus_width)

    # ------------------------------------------------------------------
    # Device-side writes
    # ------------------------------------------------------------------
    # These simulate the device updating its own registers — setting
    # RO bits, raising W1C interrupt status, writing DEVICE-owned DMA
    # fields. The CPU never calls these; the testbench does. They are
    # what makes the reference model a true two-sided simulation.

    def device_write(self, register_name: str, value: int) -> None:
        """Simulate the device writing to one of its own registers.

        Bypasses CPU-side access-kind checks: the device can update RO,
        W1C, etc. The value semantics are still honored:
          RO   : full replacement (device sets the bits)
          W1C  : OR in 1-bits (device raises the interrupt)
          W1S  : OR in 1-bits (device sets the bit)
          W0C  : AND out 0-bits
          W0S  : AND out 0-bits
          RW   : full replacement
        """
        value &= _mask(self.bus_width)
        if register_name not in self.registers:
            raise AccessError(
                "runtime-register-unknown",
                f"register {register_name!r} does not exist",
                subject=Subject("Register", {"block": self.block_name, "name": register_name}),
            )
        current = self._reg_state[register_name]
        kind = self.registers[register_name]["kind"]
        if kind == "WO":
            # Device-side: WO doesn't make sense; the device shouldn't be
            # writing into a CPU write-only register. Refuse.
            raise AccessError(
                "runtime-device-write-wo",
                f"device-side write of WO register {register_name!r}",
                subject=Subject("Register", {"block": self.block_name, "name": register_name}),
            )
        if kind in ("RW", "RC", "RO"):
            self._reg_state[register_name] = value
        elif kind == "W1C":
            # Device raises: OR in 1-bits (per standard W1C convention;
            # the *CPU* write of 1 clears, the *device* write of 1 sets).
            self._reg_state[register_name] = (current | value) & _mask(self.bus_width)
        elif kind == "W1S":
            self._reg_state[register_name] = (current | value) & _mask(self.bus_width)
        elif kind == "W0C":
            self._reg_state[register_name] = (current & value) & _mask(self.bus_width)
        elif kind == "W0S":
            self._reg_state[register_name] = (current & ~value) & _mask(self.bus_width)

    def device_write_field(self, register_name: str, field_name: str, value: int) -> None:
        """Device-side RMW of a single field. Same access-kind bypass as device_write."""
        if register_name not in self.registers:
            raise AccessError(
                "runtime-register-unknown",
                f"register {register_name!r} does not exist",
                subject=Subject("Register", {"block": self.block_name, "name": register_name}),
            )
        if field_name not in self._fields_by_register[register_name]:
            raise AccessError(
                "runtime-field-unknown",
                f"field {field_name!r} does not exist in register {register_name!r}",
                subject=Subject(
                    "Field",
                    {"block": self.block_name, "register": register_name, "name": field_name},
                ),
            )
        fdef = self._fields_by_register[register_name][field_name]
        width = fdef["msb"] - fdef["lsb"] + 1
        if value < 0 or value >= (1 << width):
            raise AccessError(
                "runtime-field-value-overflow",
                f"value {value} does not fit in field {field_name!r} (width {width})",
                subject=Subject(
                    "Field",
                    {"block": self.block_name, "register": register_name, "name": field_name},
                ),
            )
        encoded = value << fdef["lsb"]
        mask = _field_mask(fdef["lsb"], fdef["msb"])
        current = self._reg_state[register_name]
        kind = self.registers[register_name]["kind"]
        if kind == "W1C":
            # Device raises the bit.
            new = current | encoded
        elif kind == "W1S":
            new = current | encoded
        elif kind == "W0C":
            new = current & ~encoded
        elif kind == "W0S":
            new = current & ~encoded
        else:
            # RW / RC / RO: full field replace.
            new = (current & ~mask) | encoded
        self._reg_state[register_name] = new & _mask(self.bus_width)

    def device_dma_write(self, buffer_name: str, field_name: str, value: int) -> None:
        """Device writes its own DMA field. Only DEVICE-owned fields accept this."""
        buf = self.dma_buffers.get(buffer_name)
        if buf is None:
            raise AccessError(
                "runtime-dma-buffer-unknown",
                f"DMA buffer {buffer_name!r} does not exist",
                subject=Subject("DmaBuffer", {"block": self.block_name, "name": buffer_name}),
            )
        for f in buf["fields"]:
            if f["name"] == field_name:
                if f["owner"] != "DEVICE":
                    raise AccessError(
                        "runtime-dma-owner-violation",
                        f"device write to CPU-owned DMA field {field_name!r}",
                        subject=Subject(
                            "DmaField",
                            {
                                "block": self.block_name,
                                "buffer": buffer_name,
                                "name": field_name,
                            },
                        ),
                    )
                self._dma_state[(buffer_name, field_name)] = value & _mask(32)
                return
        raise AccessError(
            "runtime-dma-field-unknown",
            f"DMA field {field_name!r} does not exist on buffer {buffer_name!r}",
            subject=Subject(
                "DmaField",
                {"block": self.block_name, "buffer": buffer_name, "name": field_name},
            ),
        )

    # ------------------------------------------------------------------
    # DMA access
    # ------------------------------------------------------------------

    def dma_write(self, buffer_name: str, field_name: str, value: int) -> None:
        buf = self.dma_buffers.get(buffer_name)
        if buf is None:
            raise AccessError(
                "runtime-dma-buffer-unknown",
                f"DMA buffer {buffer_name!r} does not exist",
                subject=Subject("DmaBuffer", {"block": self.block_name, "name": buffer_name}),
            )
        for f in buf["fields"]:
            if f["name"] == field_name:
                if f["owner"] != "CPU":
                    raise AccessError(
                        "runtime-dma-owner-violation",
                        f"CPU write to DEVICE-owned DMA field {field_name!r}",
                        subject=Subject(
                            "DmaField",
                            {
                                "block": self.block_name,
                                "buffer": buffer_name,
                                "name": field_name,
                            },
                        ),
                    )
                self._dma_state[(buffer_name, field_name)] = value & _mask(32)
                return
        raise AccessError(
            "runtime-dma-field-unknown",
            f"DMA field {field_name!r} does not exist on buffer {buffer_name!r}",
            subject=Subject(
                "DmaField",
                {"block": self.block_name, "buffer": buffer_name, "name": field_name},
            ),
        )

    def dma_read(self, buffer_name: str, field_name: str) -> int:
        buf = self.dma_buffers.get(buffer_name)
        if buf is None:
            raise AccessError(
                "runtime-dma-buffer-unknown",
                f"DMA buffer {buffer_name!r} does not exist",
                subject=Subject("DmaBuffer", {"block": self.block_name, "name": buffer_name}),
            )
        for f in buf["fields"]:
            if f["name"] == field_name:
                # Both owners can be read; only DEVICE-owned must not be
                # written by the CPU. The schema enforces this statically;
                # the model backstops it at runtime.
                return self._dma_state.get((buffer_name, field_name), 0)
        raise AccessError(
            "runtime-dma-field-unknown",
            f"DMA field {field_name!r} does not exist on buffer {buffer_name!r}",
            subject=Subject(
                "DmaField",
                {"block": self.block_name, "buffer": buffer_name, "name": field_name},
            ),
        )

    # ------------------------------------------------------------------
    # Interrupts
    # ------------------------------------------------------------------

    def interrupt_pending(self, interrupt_name: str) -> bool:
        """A contract interrupt is pending iff the status field is set."""
        intdef = self.interrupts.get(interrupt_name)
        if intdef is None:
            raise AccessError(
                "runtime-interrupt-unknown",
                f"interrupt {interrupt_name!r} does not exist",
                subject=Subject(
                    "Interrupt", {"block": self.block_name, "name": interrupt_name}
                ),
            )
        if "status" not in intdef:
            # An interrupt without a status register can't be observed at
            # runtime; treat as never pending. The schema does not require
            # `status`.
            return False
        return bool(self.read_field(intdef["status"]["register"], intdef["status"]["field"]))

    def interrupt_source_active(self, interrupt_name: str) -> bool:
        """The hardware source field (e.g. STATUS.RX_READY) is set."""
        intdef = self.interrupts.get(interrupt_name)
        if intdef is None:
            raise AccessError(
                "runtime-interrupt-unknown",
                f"interrupt {interrupt_name!r} does not exist",
                subject=Subject(
                    "Interrupt", {"block": self.block_name, "name": interrupt_name}
                ),
            )
        if "source" not in intdef:
            return False
        return bool(
            self.read_field(intdef["source"]["register"], intdef["source"]["field"])
        )

    def interrupt_enabled(self, interrupt_name: str) -> bool:
        """The enable bit is set."""
        intdef = self.interrupts.get(interrupt_name)
        if intdef is None:
            raise AccessError(
                "runtime-interrupt-unknown",
                f"interrupt {interrupt_name!r} does not exist",
                subject=Subject(
                    "Interrupt", {"block": self.block_name, "name": interrupt_name}
                ),
            )
        if "enable" not in intdef:
            return False
        return bool(
            self.read_field(intdef["enable"]["register"], intdef["enable"]["field"])
        )

    def interrupt_clear(self, interrupt_name: str) -> None:
        """Clear the interrupt.

        Per the contract's `clear` linkage, writing the clear register is
        the CPU's command to the interrupt controller. The model performs
        the user-visible effect of that command: the clear-register bit
        is consumed (W1C semantics) and, if a `status` linkage is
        declared, the status bit is also cleared.
        """
        intdef = self.interrupts.get(interrupt_name)
        if intdef is None:
            raise AccessError(
                "runtime-interrupt-unknown",
                f"interrupt {interrupt_name!r} does not exist",
                subject=Subject(
                    "Interrupt", {"block": self.block_name, "name": interrupt_name}
                ),
            )
        if "clear" not in intdef:
            raise AccessError(
                "runtime-interrupt-no-clear",
                f"interrupt {interrupt_name!r} has no clear linkage",
                subject=Subject(
                    "Interrupt", {"block": self.block_name, "name": interrupt_name}
                ),
            )
        clear = intdef["clear"]
        kind = clear.get("kind", "W1C")
        reg = clear["register"]
        fld = clear["field"]
        if kind == "W1C":
            self.write_field(reg, fld, 1)
        elif kind == "W0C":
            self.write_field(reg, fld, 0)
        elif kind == "RC":
            self.read(reg)
        else:
            raise AccessError(
                "runtime-interrupt-clear-kind-unknown",
                f"clear kind {kind!r} not supported",
                subject=Subject(
                    "InterruptLinkage",
                    {
                        "block": self.block_name,
                        "interrupt": interrupt_name,
                        "role": "clear",
                    },
                ),
            )
        # The clear-register write triggers the interrupt controller to
        # drop the latched status. The model performs that effect here.
        if "status" in intdef:
            status_reg = intdef["status"]["register"]
            status_fld = intdef["status"]["field"]
            # Status is typically RO; the device set it, the controller
            # clears it. Use device-side write to bypass CPU access checks.
            current = self._reg_state[status_reg]
            fdef = self._fields_by_register[status_reg][status_fld]
            mask = _field_mask(fdef["lsb"], fdef["msb"])
            self._reg_state[status_reg] = current & ~mask

    # ------------------------------------------------------------------
    # Introspection (for diagnostics)
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, int]:
        return dict(self._reg_state)

    def dma_snapshot(self) -> dict[tuple[str, str], int]:
        return dict(self._dma_state)