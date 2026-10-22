"""Run every Phase-0 scenario against the reference model.

Usage:
    python3 oracle/legacy/tools/sim/run_scenarios.py
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import scenarios.uart_basic as uart
import scenarios.dma_basic as dma
import test_refusal_runtime as refusal


def main() -> int:
    rc = 0
    rc |= uart.main()
    rc |= dma.main()
    rc |= refusal.main()
    return rc


if __name__ == "__main__":
    sys.exit(main())