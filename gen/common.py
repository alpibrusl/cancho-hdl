"""Shared behavior for the generators, once two exist to share it.

The generators are loaded by module path (no package), so this
file is imported by adding `gen/` to `sys.path` — see
tools/generate/generate.py, which resolves the same class by
type when it catches refusals.

Contract reference for the refusal: spec/generators/README.md
§1 rule 4 — a generator refuses on missing features, never
silently degrades; rule 5 — a malformed IR the checker should
have caught is plain `internal`, not this refusal.
"""


class GeneratorUnimplemented(ValueError):
    """A declared feature the generator cannot emit.

    The dispatcher renders this as `generator-unimplemented`
    (exit 1), not `internal`. Subclassing ValueError keeps the
    generators usable as libraries: a ValueError is still a
    refusal to emit an artifact.
    """
