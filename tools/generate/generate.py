"""Generate artifacts from a contract.

Dispatches to the right per-target generator based on `--target`.
Landed targets: `c-header`, `systemverilog` (Phase 1) and
`devicetree`, `cancho-binding`, `svd` (Phase 2).

Both source forms flow through `tools/parse/parser.py`
(`load_contract` sniffs the format); a contract the checker
refuses aborts the run with its refusal diagnostics — the
generators assume a checked IR.

The dispatcher is the single source of truth for which targets
exist. `cancho-hdl generate --help` prints the supported set
and exits 1 on an unknown target with a
`generator-target-unknown` diagnostic.

Usage:

    python3 tools/generate/generate.py --target c-header <file.chw>
"""

from __future__ import annotations

from typing import Any, Callable

import argparse
import importlib.util
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "gen"))

from common import GeneratorUnimplemented  # noqa: E402


# Generators. Each entry is (module_path_relative_to_repo, function_name).
_GENERATORS: dict[str, tuple[str, str]] = {
    "c-header":      ("gen/c-header/c_header.py", "generate"),
    "systemverilog": ("gen/systemverilog/systemverilog.py", "generate"),
    "devicetree":    ("gen/devicetree/devicetree.py", "generate"),
    "cancho-binding": ("gen/cancho-binding/cancho_binding.py", "generate"),
    "svd":           ("gen/svd/svd.py", "generate"),
}


def _load_generator(target: str) -> Callable[[dict[str, Any], str], str] | None:
    """Return a `generate(ir, source_path) -> str` callable, or
    None if the target is not registered. ImportError is raised
    only if the registered module does not exist on disk yet
    (the implementation is deferred to a later phase)."""
    if target not in _GENERATORS:
        return None
    rel_path, func_name = _GENERATORS[target]
    full_path = REPO_ROOT / rel_path
    if not full_path.exists():
        raise NotImplementedError(
            f"target {target!r} is registered but no implementation is shipped yet"
        )
    spec = importlib.util.spec_from_file_location(f"cancho_hdl_gen_{target}", str(full_path))
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load spec for {full_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, func_name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cancho-hdl generate",
        description="Generate an artifact from a .chw contract.",
    )
    parser.add_argument("file", help="A .chw file (JSON wire format).")
    parser.add_argument(
        "--target", required=True,
        help="Generator target. All five MVP targets are landed: "
             "c-header, systemverilog, devicetree, cancho-binding, svd.",
    )
    args = parser.parse_args(argv)

    p = pathlib.Path(args.file)
    if not p.exists():
        print(f"error: file not found: {p}", file=sys.stderr)
        return 2

    # Both source forms flow through the same entry point as the
    # checker (tools/parse/parser.py::load_contract sniffs the
    # format). A contract that does not parse is refused, not
    # half-generated.
    sys.path.insert(0, str(REPO_ROOT / "tools" / "parse"))
    sys.path.insert(0, str(REPO_ROOT / "tools" / "check"))
    from parser import load_contract  # noqa: E402

    ir, load_diags = load_contract(str(p))
    if ir is None:
        for d in load_diags:
            print(f"error[{d.code}]: {d.message}", file=sys.stderr)
        return 1

    # The generators assume a checked IR (spec/generators §1 rule 5:
    # a malformed IR the checker should have caught is `internal`).
    # Refusing here narrows that lane to real checker escapes.
    from checker import check_file  # noqa: E402

    errors = [d for d in check_file(str(p)) if d.severity == "Error"]
    if errors:
        for d in errors:
            print(f"error[{d.code}]: {d.message}", file=sys.stderr)
        print("error: not generating from a refused contract.", file=sys.stderr)
        return 1

    try:
        gen = _load_generator(args.target)
    except NotImplementedError as e:
        print(f"error[generator-unimplemented]: target {args.target}: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"error[internal]: {e}", file=sys.stderr)
        return 3

    if gen is None:
        print(
            f"error[generator-target-unknown]: target {args.target!r} is not supported. "
            f"Known: {', '.join(sorted(_GENERATORS))}",
            file=sys.stderr,
        )
        return 1

    try:
        out = gen(ir, source_path=str(p))
    except GeneratorUnimplemented as e:
        # §1 rule 4: refuse on missing features, never degrade.
        print(f"error[generator-unimplemented]: target {args.target}: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        # §1 rule 5: the run fails, not just the artifact.
        print(f"error[internal]: {e}", file=sys.stderr)
        return 3

    sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())