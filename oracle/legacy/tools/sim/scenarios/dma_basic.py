"""DMA contract scenarios.

Drives the reference model against examples/simple-dma/dma.chw
and asserts:

- W1C clear semantics (write 1 to clear)
- DMA field CPU ownership (write allowed)
- DMA field DEVICE ownership (write refused at runtime)
- DMA field read access for both owners
- Reset behavior
- IRQ lifecycle for tx_complete
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "oracle" / "legacy" / "tools" / "sim"))

from reference_model import ReferenceModel
from scenario import expect, expect_access_error, main as run_main


CHW = ROOT / "examples" / "simple-dma" / "dma.chw"


def scenario_w1c_clear() -> None:
    model = ReferenceModel.from_chw_file(CHW)

    # IRQ_STATUS is W1C: the device raises bits (set), the CPU clears
    # them (write 1 to clear). The CPU cannot set them.
    # Simulate the device raising both DONE and ERR.
    model.device_write("IRQ_STATUS", 0xFFFFFFFF)
    expect(model.read("IRQ_STATUS") & 0x3 == 0x3, "IRQ_STATUS DONE|ERR set by device")

    # CPU clears DONE by writing 1 to it (W1C semantics).
    model.write("IRQ_STATUS", 0x1)
    expect(
        model.read("IRQ_STATUS") & 0x1 == 0,
        "DONE bit cleared after CPU W1C write of 1",
    )
    expect(
        model.read("IRQ_STATUS") & 0x2 == 0x2,
        "ERR bit preserved across W1C of DONE",
    )


def scenario_dma_cpu_owned() -> None:
    model = ReferenceModel.from_chw_file(CHW)

    # next_ptr is CPU-owned: CPU write is allowed.
    model.dma_write("TxDescriptor", "next_ptr", 0xDEAD_BEEF)
    expect(
        model.dma_read("TxDescriptor", "next_ptr") == 0xDEAD_BEEF,
        "CPU-owned DMA field roundtrips",
    )

    # data_ptr is CPU-owned with align=4.
    model.dma_write("TxDescriptor", "data_ptr", 0x1000)
    expect(
        model.dma_read("TxDescriptor", "data_ptr") == 0x1000,
        "data_ptr roundtrips",
    )


def scenario_dma_device_owned() -> None:
    model = ReferenceModel.from_chw_file(CHW)

    # done_flag is DEVICE-owned: CPU write must refuse.
    expect_access_error(
        lambda: model.dma_write("TxDescriptor", "done_flag", 1),
        "runtime-dma-owner-violation",
        "CPU write to DEVICE-owned done_flag",
    )

    # DEVICE-owned fields are readable (the device wrote them).
    expect(
        model.dma_read("TxDescriptor", "done_flag") == 0,
        "DEVICE-owned field is readable",
    )


def scenario_dma_rx_descriptor() -> None:
    model = ReferenceModel.from_chw_file(CHW)

    # RxDescriptor: next_ptr CPU, data_ptr DEVICE, length DEVICE, error_flag DEVICE.
    model.dma_write("RxDescriptor", "next_ptr", 0x2000)
    expect(model.dma_read("RxDescriptor", "next_ptr") == 0x2000, "Rx next_ptr CPU-writeable")

    expect_access_error(
        lambda: model.dma_write("RxDescriptor", "data_ptr", 0x3000),
        "runtime-dma-owner-violation",
        "Rx data_ptr DEVICE-owned: CPU write refused",
    )
    expect_access_error(
        lambda: model.dma_write("RxDescriptor", "length", 1024),
        "runtime-dma-owner-violation",
        "Rx length DEVICE-owned: CPU write refused",
    )

    # All DEVICE fields readable
    for f in ("data_ptr", "length", "error_flag"):
        # Reading returns 0 at reset — no refusal.
        model.dma_read("RxDescriptor", f)


def scenario_irq_tx_complete() -> None:
    model = ReferenceModel.from_chw_file(CHW)

    expect(not model.interrupt_pending("tx_complete"), "tx_complete not pending at reset")

    # Device raises DONE.
    model.device_write("IRQ_STATUS", 0x1)
    expect(model.interrupt_pending("tx_complete"), "tx_complete pending after device raised DONE")

    # CPU enables.
    model.write_field("IRQ_ENABLE", "DONE_EN", 1)
    expect(model.interrupt_enabled("tx_complete"), "tx_complete enabled")

    # CPU clears via W1C.
    model.interrupt_clear("tx_complete")
    expect(not model.interrupt_pending("tx_complete"), "tx_complete cleared via W1C")


def scenario_reset() -> None:
    model = ReferenceModel.from_chw_file(CHW)
    model.write("RING_BASE", 0x12345678)
    model.dma_write("TxDescriptor", "next_ptr", 0xCAFEBABE)
    model.write("IRQ_STATUS", 0x2)

    model.reset()

    expect(model.read("RING_BASE") == 0x00000000, "RING_BASE reset to 0")
    expect(
        model.dma_read("TxDescriptor", "next_ptr") == 0,
        "DMA field reset to 0",
    )
    expect(model.read("IRQ_STATUS") & 0x3 == 0, "IRQ_STATUS reset clears DONE/ERR")


def main() -> int:
    return run_main(
        [
            ("dma/w1c_clear", scenario_w1c_clear),
            ("dma/cpu_owned", scenario_dma_cpu_owned),
            ("dma/device_owned", scenario_dma_device_owned),
            ("dma/rx_descriptor", scenario_dma_rx_descriptor),
            ("dma/irq_tx_complete", scenario_irq_tx_complete),
            ("dma/reset", scenario_reset),
        ]
    )


if __name__ == "__main__":
    sys.exit(main())