"""Scenario helpers for the reference-model simulator.

Each scenario is a function that drives the model and asserts
expected behaviour. The runner in `run_scenarios.py` exits 0
on full success and 1 on the first failure.
"""

from __future__ import annotations

import sys
import traceback
from typing import Any, Callable

from reference_model import AccessError, ReferenceModel


class ScenarioFailure(AssertionError):
    pass


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise ScenarioFailure(message)


def expect_access_error(
    fn: Callable[[], Any], expected_code: str | None, context: str
) -> AccessError | None:
    """Run `fn` and assert it raises an AccessError with the given code.

    If `expected_code` is None, asserts that the call succeeds.
    Returns the captured error on failure for inspection.
    """
    try:
        result = fn()
    except AccessError as e:
        if expected_code is None:
            raise ScenarioFailure(
                f"{context}: unexpected access refusal: code={e.code} message={e.message}"
            ) from e
        if e.code != expected_code:
            raise ScenarioFailure(
                f"{context}: wrong refusal code. expected={expected_code} got={e.code} ({e.message})"
            ) from e
        return e
    if expected_code is not None:
        raise ScenarioFailure(
            f"{context}: expected refusal {expected_code} but call succeeded with {result!r}"
        )
    return None


def run(name: str, body: Callable[[], None]) -> bool:
    """Run a scenario body. Returns True on success, False on failure."""
    try:
        body()
        print(f"  PASS  {name}")
        return True
    except Exception:
        print(f"  FAIL  {name}")
        traceback.print_exc()
        return False


def main(scenarios: list[tuple[str, Callable[[], None]]]) -> int:
    print(f"== running {len(scenarios)} scenarios ==")
    results = [run(name, body) for name, body in scenarios]
    failures = sum(1 for r in results if not r)
    print(f"== {len(results) - failures} passed, {failures} failed ==")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main([]))