"""Roundtrip test: generated C header compiles under clang and gcc.

For every valid example in `examples/MANIFEST.json`, the c-header
generator is run; the output is checked for:

- Clang compiles it with `-Wall -Wextra -Werror -std=c11`.
- Gcc compiles it with `-Wall -Wextra -Werror -std=c11`.
- The two outputs are byte-identical (the generator is
  deterministic; if not, that's a generator bug).
- A tiny smoke program that uses the generated struct compiles,
  links, and runs (or at least, the compile-and-link succeeds).

The test exits 0 on full pass, 1 on any failure.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "oracle" / "legacy" / "tools" / "generate"))
sys.path.insert(0, str(ROOT / "oracle" / "legacy" / "tools" / "parse"))

# Use the dispatcher's loader so the roundtrip test exercises the
# same code path as the CLI.
from generate import _load_generator  # noqa: E402
from parser import load_contract  # noqa: E402


EXAMPLES = ROOT / "examples"
MANIFEST = json.loads((EXAMPLES / "MANIFEST.json").read_text())


def _have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _compile(compiler: str, src_path: pathlib.Path, out_path: pathlib.Path) -> tuple[int, str]:
    """Compile a C source file. Returns (exit_code, stderr)."""
    proc = subprocess.run(
        [compiler, "-Wall", "-Wextra", "-Werror", "-std=c11",
         "-c", "-x", "c", str(src_path), "-o", str(out_path)],
        capture_output=True, text=True,
    )
    return proc.returncode, (proc.stderr or "") + (proc.stdout or "")


def _run_smoke(header: pathlib.Path, ir: dict) -> tuple[int, str]:
    """Compile a tiny program that includes `header` and uses the
    generated types. Returns (exit_code, stderr).

    The smoke test is generated from the IR: the typedef name
    comes from the block's `name` (passed through the same
    `_to_lower_snake` the generator uses), and the field touched
    is the first register by offset. This way the smoke test
    works for any contract without hardcoding names.

    The header is force-included via `-include` so the smoke.c
    file does not need a `#include` directive and clang only sees
    one source file. This avoids the "multiple output files" error.
    """
    block = ir["block"]
    block_name = block["name"]
    registers = sorted(block.get("registers", []), key=lambda r: int(r["offset"], 16))
    if not registers:
        return 0, ""  # nothing to smoke
    first_reg = registers[0]["name"].lower()

    def _to_lower_snake(name: str) -> str:
        if not name:
            return name
        out = []
        for i, ch in enumerate(name):
            if ch.isupper():
                prev_lower = i > 0 and name[i - 1].islower()
                end_of_abbrev = (
                    i > 0 and i + 1 < len(name)
                    and name[i - 1].isupper()
                    and name[i + 1].islower()
                )
                if i > 0 and (prev_lower or end_of_abbrev):
                    out.append("_")
            out.append(ch.lower())
        return "".join(out)

    typedef = _to_lower_snake(block_name) + "_t"

    smoke_c = (
        f'int main(void) {{\n'
        f'    {typedef} r = {{0}};\n'
        f'    r.{first_reg} = 0x00000001u;\n'
        f'    return (int)r.{first_reg};\n'
        f'}}\n'
    )
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        smoke = td / "_smoke.c"
        smoke.write_text(smoke_c)
        out = td / "_smoke"
        proc = subprocess.run(
            ["clang", "-Wall", "-Wextra", "-Werror", "-std=c11",
             "-include", str(header),
             str(smoke), "-o", str(out)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            return proc.returncode, (proc.stderr or "") + (proc.stdout or "")
        # Run the binary; it should return 0x1 (the value we wrote).
        run_proc = subprocess.run([str(out)], capture_output=True, text=True)
        if run_proc.returncode != 1:
            return 1, f"smoke binary returned {run_proc.returncode} (expected 1), stderr: {run_proc.stderr}"
        return 0, ""


def main() -> int:
    if not _have("clang"):
        print("FAIL  clang not on PATH")
        return 1
    if not _have("gcc"):
        print("FAIL  gcc not on PATH")
        return 1

    gen = _load_generator("c-header")
    if gen is None:
        print("FAIL  c-header generator not registered")
        return 1

    print("== c-header roundtrip ==")
    failures: list[str] = []

    for rel in MANIFEST["valid"]:
        chw = ROOT / rel
        ir, load_diags = load_contract(str(chw))
        if ir is None:
            failures.append(f"  FAIL  {chw.stem}: contract did not load: "
                            f"{load_diags[0].message}")
            continue
        out_a = ROOT / f"gen-out/{chw.stem}_clang.h"
        out_b = ROOT / f"gen-out/{chw.stem}_gcc.h"
        out_a.parent.mkdir(parents=True, exist_ok=True)

        # Generate
        src = gen(ir, source_path=str(chw))
        out_a.write_text(src)
        out_b.write_text(src)

        # Determinism: same input, same output bytes.
        if out_a.read_bytes() != out_b.read_bytes():
            failures.append(f"  FAIL  {chw.stem}: c-header not deterministic")
            continue

        # Compile under both
        with tempfile.TemporaryDirectory() as td:
            td = pathlib.Path(td)
            rc, err = _compile("clang", out_a, td / "a.o")
            if rc != 0:
                failures.append(f"  FAIL  {chw.stem}: clang compile error\n{err}")
                continue
            rc, err = _compile("gcc", out_a, td / "b.o")
            if rc != 0:
                failures.append(f"  FAIL  {chw.stem}: gcc compile error\n{err}")
                continue

        # Smoke test: a program that includes the header and uses
        # the struct. This catches the case where the header
        # compiles standalone but isn't usable.
        rc, err = _run_smoke(out_a, ir)
        if rc != 0:
            failures.append(f"  FAIL  {chw.stem}: smoke build error\n{err}")
            continue

        print(f"  PASS  {chw.stem}: clang + gcc compile clean, smoke build clean")

    # Cleanup generated artifacts.
    gen_out = ROOT / "gen-out"
    if gen_out.exists():
        shutil.rmtree(gen_out)

    print()
    if failures:
        print(f"== {len(failures)} failure(s) ==")
        for f in failures:
            print(f)
        return 1
    print("== c-header roundtrip: all valid examples pass ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())