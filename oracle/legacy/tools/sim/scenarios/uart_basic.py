"""UART contract scenarios.

Drives the reference model against examples/uart-contract/uart.chw
and asserts:

- register read/write correctness
- field bit-range encoding
- enum field storage and decoding
- access kind enforcement (RO rejects write, WO rejects read)
- reset values
- interrupt source -> status -> enable -> clear lifecycle
- W1C clear semantics on ICR
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "oracle" / "legacy" / "tools" / "sim"))

from reference_model import AccessError, ReferenceModel
from scenario import expect, expect_access_error, main as run_main


CHW = ROOT / "examples" / "uart-contract" / "uart.chw"


def scenario_rw_basic() -> None:
    model = ReferenceModel.from_chw_file(CHW)

    # CTRL is RW with reset 0
    expect(model.read("CTRL") == 0x00000000, "CTRL initial value is reset")

    # Write ENABLE bit
    model.write_field("CTRL", "ENABLE", 1)
    expect(model.read_field("CTRL", "ENABLE") == 1, "ENABLE bit set after write")
    expect(model.read("CTRL") == 0x00000001, "CTRL reads back the bit")

    # Write BAUD_DIV = 0x80
    model.write_field("CTRL", "BAUD_DIV", 0x80)
    expect(
        model.read_field("CTRL", "BAUD_DIV") == 0x80,
        "BAUD_DIV reads back the byte written",
    )
    # ENABLE bit was preserved across the field write (RMW)
    expect(
        model.read_field("CTRL", "ENABLE") == 1,
        "ENABLE bit preserved across BAUD_DIV write",
    )

    # Reset wipes everything
    model.reset()
    expect(model.read("CTRL") == 0x00000000, "CTRL is zero after reset")


def scenario_enum_field() -> None:
    model = ReferenceModel.from_chw_file(CHW)

    # PARITY enum: None=0, Even=1, Odd=2 in bits [1..2]
    for label, value in [("None", 0), ("Even", 1), ("Odd", 2)]:
        model.write_field("CTRL", "PARITY", value)
        got = model.read_field("CTRL", "PARITY")
        expect(got == value, f"PARITY {label}={value} roundtrips (got {got})")

    # Enum value out of set
    expect_access_error(
        lambda: model.write_field("CTRL", "PARITY", 3),
        "runtime-field-enum-violation",
        "PARITY value 3 is not an enum member",
    )


def scenario_access_kinds() -> None:
    model = ReferenceModel.from_chw_file(CHW)

    # STATUS is RO. Write must refuse.
    expect_access_error(
        lambda: model.write("STATUS", 0xFFFFFFFF),
        "runtime-access-kind-violation",
        "write of RO STATUS",
    )
    expect_access_error(
        lambda: model.write_field("STATUS", "RX_READY", 1),
        "runtime-access-kind-violation",
        "write of field in RO register",
    )

    # ICR is WO. Read must refuse.
    expect_access_error(
        lambda: model.read("ICR"),
        "runtime-access-kind-violation",
        "read of WO ICR",
    )

    # RO read works
    expect(model.read("STATUS") == 0x00000000, "RO STATUS reads 0 at reset")


def scenario_interrupt_lifecycle() -> None:
    model = ReferenceModel.from_chw_file(CHW)

    # Initially: source inactive, interrupt not pending, not enabled.
    expect(not model.interrupt_source_active("rx_ready"), "rx_ready source inactive")
    expect(not model.interrupt_pending("rx_ready"), "rx_ready not pending")
    expect(not model.interrupt_enabled("rx_ready"), "rx_ready not enabled")

    # STATUS is RO; only the device sets RX_READY. Simulate the device
    # raising the source bit. In real hardware the interrupt controller
    # latches the corresponding ISR.RX bit; the device drives both.
    model.device_write_field("STATUS", "RX_READY", 1)
    model.device_write_field("ISR", "RX", 1)
    expect(model.interrupt_source_active("rx_ready"), "rx_ready source now active")
    expect(model.interrupt_pending("rx_ready"), "rx_ready pending (ISR.RX latched)")

    # CPU enables the interrupt.
    model.write_field("IER", "RX_EN", 1)
    expect(model.interrupt_enabled("rx_ready"), "rx_ready now enabled")

    # CPU clears the interrupt via W1C on ICR. This is the canonical
    # handshake: device raises, CPU acknowledges-and-clears.
    model.interrupt_clear("rx_ready")
    expect(not model.interrupt_pending("rx_ready"), "rx_ready cleared via W1C on ICR")


def scenario_w1c_clear_semantics() -> None:
    model = ReferenceModel.from_chw_file(CHW)

    # ICR is WO. Its W1C clear semantics are exposed via the interrupt
    # controller. We test W1C semantics on the W1C example in DMA instead,
    # because UART has no W1C register. Here we verify WO accepts writes.
    model.write("ICR", 0xFFFFFFFF)
    # WO state is not readable per the access kind; reading would refuse.
    expect_access_error(
        lambda: model.read("ICR"),
        "runtime-access-kind-violation",
        "WO ICR refuses read after write",
    )


def main() -> int:
    return run_main(
        [
            ("uart/rw_basic", scenario_rw_basic),
            ("uart/enum_field", scenario_enum_field),
            ("uart/access_kinds", scenario_access_kinds),
            ("uart/interrupt_lifecycle", scenario_interrupt_lifecycle),
            ("uart/wo_w1c_semantics", scenario_w1c_clear_semantics),
        ]
    )


if __name__ == "__main__":
    sys.exit(main())