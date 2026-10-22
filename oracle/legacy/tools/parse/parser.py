"""Textual `.chw` parser for cancho-hdl.

Turns the textual contract syntax (parent proposal §5.2, now frozen
as of Phase 1 — see `spec/contract-schema/README.md` §6) into the
same JSON wire form the checker and generators consume. After this
parser, JSON is an interchange concern, not a user-facing one: a
`register-block` is written in text and stored as JSON.

The parser is hand-written (tokenizer + recursive descent), has no
dependencies, and is deterministic. Syntax errors are `parse-error`
diagnostics with real line/column spans — the diagnostic shape is
the shared one from `oracle/legacy/tools/check/diagnostic.py`.

Grammar (frozen; deviations from the sketch become parse errors):

    file        := item* EOF
    item        := block | dma_buffer
    block       := "register-block" IDENT "@" HEX "," "width" DEC ","
                   endianness "{" item_in_block* "}"
    item_in_block := register | interrupt
    register    := "register" IDENT "@" HEX ":" KIND attr_list? "{" field* "}"
    attr        := "reset" HEX | "volatile" | "polling"
    field       := "field" IDENT ":" "bits" "[" DEC [ ".." DEC ] "]"
                   [ "enum" "{" enum_entry* "}" ] [ "constraint" text ]
    interrupt   := "interrupt" IDENT "from" REF "{" linkage* "}"
    linkage     := ("source" | "enable" | "status") "@" REF
                 | "clear" [":" ("W1C"|"W0C"|"RC")] "@" REF
                 | "number" DEC
    dma_buffer  := "dma-buffer" IDENT "{" dma_field* "}"
    dma_field   := "field" IDENT ":" "@" HEX attr_list?
    dma_attr    := "owned" "by" ("CPU"|"DEVICE") | "aligned" DEC
                 | "coherent" ("true"|"false") | "written" "as" DEC
                 | "constraint" text

    endianness  := "little-endian" | "big-endian"
    KIND        := RO | WO | RW | RC | W1C | W0C | W1S | W0S
    REF         := IDENT "." IDENT
    enum_entry  := IDENT "=" DEC
    text        := (lexed by the tokenizer) the words after the
                   `constraint` keyword up to the end of the same
                   line, stripped of a trailing `//` comment

Comments: `//` to end of line. Hex numbers may use `_` separators
(`0x4000_0000`). Whitespace is free.

Usage:

    from parser import parse_source_text, load_contract
    ir, diags = parse_source_text(src, "uart.chw")
    # or, from a path (sniffs JSON vs textual):
    ir, diags = load_contract("uart.chw")
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
from typing import Any

_ROOT = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_ROOT / "oracle" / "legacy" / "tools" / "check"))

from diagnostic import Diagnostic, Position, Span, Subject  # noqa: E402


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------


class Token:
    __slots__ = ("kind", "value", "line", "col")

    def __init__(self, kind: str, value: str, line: int, col: int) -> None:
        self.kind = kind
        self.value = value
        self.line = line
        self.col = col

    def __repr__(self) -> str:  # pragma: no cover — debug aid
        return f"Token({self.kind}, {self.value!r}, {self.line}:{self.col})"


_TOKEN_RE = re.compile(
    r"""
    (?P<comment>//[^\n]*)
  | (?P<hex>0[xX][0-9a-fA-F_]+)
  | (?P<dec>[0-9]+)
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<punct>\.\.|[,:;=@\[\]{}().\-])
  | (?P<ws>[ \t\r\n]+)
""",
    re.VERBOSE,
)


def tokenize(src: str) -> list[Token]:
    tokens: list[Token] = []
    line, col = 1, 1
    pos = 0
    n = len(src)
    while pos < n:
        m = _TOKEN_RE.match(src, pos)
        if m is None:
            # Unknown character: emit it as an error token with its exact
            # position so the parser can name it in the refusal message.
            ch = src[pos]
            tokens.append(Token("error", ch, line, col))
            if ch == "\n":
                line += 1
                col = 1
            else:
                col += 1
            pos += 1
            continue
        text = m.group(0)
        kind = m.lastgroup
        if kind == "comment" or kind == "ws":
            advance = text.count("\n")
            if advance:
                line += advance
                col = len(text) - text.rfind("\n")
            else:
                col += len(text)
        elif kind == "ident" and text == "constraint":
            # The word 'constraint' claims the rest of its line as
            # one free-text token: `constraint length <= 4096` lexes
            # as CONST_KEYWORD("constraint") + STR("length <= 4096").
            # This is why constraint text may contain characters
            # (like `<=` and `==`) that are not valid tokens elsewhere.
            # A 'constraint' inside a `//` comment already matched the
            # comment alternative above and is ignored.
            tokens.append(Token("const_keyword", "constraint", line, col))
            after = pos + len(text)
            rest = src[after:]
            cm = re.search(r"//|\n", rest)
            cut = len(rest) if cm is None else cm.start()
            value = rest[:cut].strip()
            tokens.append(Token("str", value, line, col + len(text)))
            col += len(text) + cut
            pos = after + cut
            continue
        else:
            tokens.append(Token(kind, text, line, col))
            col += len(text)
        pos += len(text)
    tokens.append(Token("eof", "<end of file>", line, col))
    return tokens


# ---------------------------------------------------------------------------
# Parse errors
# ---------------------------------------------------------------------------


def _err_diag(path: str, tok: Token, message: str) -> Diagnostic:
    return Diagnostic(
        code="parse-error",
        tier="Static",
        subject=Subject("Ir", {"path": path}),
        span=Span(
            file=path,
            start=Position(tok.line, tok.col),
            end=Position(tok.line, tok.col + max(len(tok.value), 1)),
        ),
        message=message,
    )


class _ParseAbort(Exception):
    """Raised internally to stop after the first syntax error."""


class Parser:
    def __init__(self, tokens: list[Token], path: str) -> None:
        self.toks = tokens
        self.path = path
        self.i = 0
        self.error: Diagnostic | None = None

    # -- cursor helpers -----------------------------------------------------

    def peek(self, ahead: int = 0) -> Token:
        j = min(self.i + ahead, len(self.toks) - 1)
        return self.toks[j]

    def at_composite(self, first: str, second: str) -> bool:
        """True when the cursor sits on `first-second`, e.g. the two-word
        keywords `register-block` and `dma-buffer` (lexed as three tokens
        because `-` is a standalone punctuation token)."""
        t0, t1, t2 = self.peek(0), self.peek(1), self.peek(2)
        return (
            t0.kind == "ident" and t0.value == first
            and t1.kind == "punct" and t1.value == "-"
            and t2.kind == "ident" and t2.value == second
        )

    def eat_composite(self) -> None:
        """Consume a composite keyword previously confirmed by `at_composite`."""
        self.next()
        self.next()
        self.next()

    def next(self) -> Token:
        tok = self.toks[self.i]
        if tok.kind != "eof":
            self.i += 1
        return tok

    def describe(self, tok: Token) -> str:
        if tok.kind == "eof":
            return "end of file"
        return f"'{tok.value}'"

    def fail(self, message: str, tok: Token | None = None) -> None:
        tok = tok or self.peek()
        desc = self.describe(tok)
        self.error = _err_diag(self.path, tok, f"parse error: {message}, found {desc}.")
        raise _ParseAbort()

    def expect(self, kind: str, value: str | None = None, what: str = "") -> Token:
        tok = self.peek()
        ok = tok.kind == kind and (value is None or tok.value == value)
        if not ok:
            want = what or (f"'{value}'" if value else kind)
            self.fail(f"expected {want}")
        return self.next()

    def expect_ident(self, what: str) -> Token:
        tok = self.peek()
        if tok.kind != "ident":
            self.fail(f"expected {what}")
        return self.next()

    # -- literals -----------------------------------------------------------

    @staticmethod
    def _hex(tok: Token) -> str:
        """`0x4000_0000` → `0x40000000`; widths are preserved literally."""
        return "0x" + tok.value[2:].replace("_", "").lower()

    def expect_hex(self) -> str:
        tok = self.peek()
        if tok.kind != "hex":
            self.fail("expected a hex number like 0x1c")
        self.next()
        return self._hex(tok)

    def expect_dec(self) -> int:
        tok = self.peek()
        if tok.kind != "dec":
            self.fail("expected a decimal number")
        self.next()
        return int(tok.value)

    # -- productions --------------------------------------------------------

    def parse_file(self) -> dict[str, Any] | None:
        block: dict[str, Any] | None = None
        dma_buffers: list[dict[str, Any]] = []
        while self.peek().kind != "eof":
            if self.at_composite("register", "block"):
                if block is not None:
                    self.fail("a file may contain only one register-block", self.peek())
                self.eat_composite()
                block = self.parse_block()
            elif self.at_composite("dma", "buffer"):
                self.eat_composite()
                dma_buffers.append(self.parse_dma_buffer())
            else:
                self.fail("expected a 'register-block' or 'dma-buffer' declaration")
        if block is None:
            self.fail("a contract file must contain a 'register-block'", self.peek())
        ir: dict[str, Any] = {
            "$schema":
                "https://alpibrusl/cancho-hdl/spec/contract-schema/"
                "cancho-hdl-contract.schema.json",
            "version": "0.1.0",
            "block": block,
            "dma_buffers": dma_buffers,
        }
        return ir

    def parse_block(self) -> dict[str, Any]:
        # The 'register-block' composite keyword is consumed by parse_file.
        name = self.expect_ident("a block name").value
        self.expect("punct", "@", "'@' before the base address")
        base_address = self.expect_hex()
        self.expect("punct", ",", "',' before 'width'")
        self.expect("ident", "width", "'width'")
        bus_width = self.expect_dec()
        self.expect("punct", ",", "',' before the endianness")
        tok = self.expect_ident("an endianness ('little-endian' or 'big-endian')")
        # `little-endian` / `big-endian` lex as three tokens (`little`
        # `-` `endian`) because `-` is standalone punctuation; bare
        # `little` / `big` is accepted too for convenience.
        if (
            tok.value in ("little", "big")
            and self.peek().kind == "punct" and self.peek().value == "-"
            and self.peek(1).kind == "ident" and self.peek(1).value == "endian"
        ):
            self.next()
            self.next()
        if tok.value not in ("little", "big"):
            self.fail("expected 'little-endian' or 'big-endian'", tok)
        endianness = tok.value
        self.expect("punct", "{", "'{' to open the block body")

        registers: list[dict[str, Any]] = []
        interrupts: list[dict[str, Any]] = []
        while not (self.peek().kind == "punct" and self.peek().value == "}"):
            tok = self.peek()
            if tok.kind == "eof":
                self.fail("expected '}' to close the block")
            if tok.value == "register":
                registers.append(self.parse_register())
            elif tok.value == "interrupt":
                interrupts.append(self.parse_interrupt())
            else:
                self.fail("expected 'register' or 'interrupt' inside the block")
        self.next()  # consume '}'

        out: dict[str, Any] = {
            "name": name,
            "base_address": base_address,
            "bus_width": bus_width,
            "endianness": endianness,
            "registers": registers,
        }
        if interrupts:
            out["interrupts"] = interrupts
        return out

    def parse_register(self) -> dict[str, Any]:
        self.expect("ident", "register")
        name = self.expect_ident("a register name").value
        self.expect("punct", "@", "'@' before the offset")
        offset = self.expect_hex()
        self.expect("punct", ":", "':' after the register offset (before the access kind)")
        tok = self.expect_ident("an access kind (RW, RO, WO, RC, W1C, W0C, W1S, W0S)")
        reg: dict[str, Any] = {"name": name, "offset": offset, "kind": tok.value}

        # Optional attribute list: , reset 0x… , volatile , polling …
        while self.peek().kind == "punct" and self.peek().value == ",":
            self.next()
            tok = self.expect_ident("a register attribute ('reset', 'volatile' or 'polling')")
            if tok.value == "reset":
                reg["reset"] = self.expect_hex()
            elif tok.value in ("volatile", "polling"):
                reg[tok.value] = True
            else:
                self.fail(
                    "expected a register attribute ('reset', 'volatile' or 'polling')",
                    tok,
                )

        fields: list[dict[str, Any]] = []
        self.expect("punct", "{", "'{' to open the register body")
        while not (self.peek().kind == "punct" and self.peek().value == "}"):
            tok = self.peek()
            if tok.kind == "eof":
                self.fail("expected '}' to close the register")
            if tok.value == "field":
                fields.append(self.parse_field())
            else:
                self.fail("expected 'field' inside the register")
        self.next()  # consume '}'
        if fields:
            reg["fields"] = fields
        return reg

    def parse_field(self) -> dict[str, Any]:
        self.expect("ident", "field")
        name = self.expect_ident("a field name").value
        self.expect("punct", ":", "':' after the field name")
        self.expect("ident", "bits", "'bits'")
        self.expect("punct", "[", "'[' to open the bit range")
        lsb = self.expect_dec()
        msb = lsb
        if self.peek().kind == "punct" and self.peek().value == "..":
            self.next()
            msb = self.expect_dec()
        self.expect("punct", "]", "']' to close the bit range")
        fld: dict[str, Any] = {"name": name, "lsb": lsb, "msb": msb}

        # Optional enum:  enum { None=0, Even=1, Odd=2 }
        if self.peek().kind == "ident" and self.peek().value == "enum":
            self.next()
            self.expect("punct", "{", "'{' to open the enum")
            enum: dict[str, int] = {}
            first = True
            while not (self.peek().kind == "punct" and self.peek().value == "}"):
                if not first and self.peek().kind == "punct" and self.peek().value == ",":
                    self.next()
                tok = self.expect_ident("an enum label")
                self.expect("punct", "=", "'=' after the enum label")
                val = self.expect_dec()
                if tok.value in enum:
                    self.fail(f"duplicate enum label '{tok.value}'", tok)
                enum[tok.value] = val
                first = False
            # Allow the comma that precedes '}' to be absent; consume '}'.
            if self.peek().kind == "punct" and self.peek().value == ",":
                self.next()
            self.expect("punct", "}", "'}' to close the enum")
            fld["enum"] = enum

        # Optional constraint: `constraint` + one free-text token lexed
        # from the rest of the line by the tokenizer.
        if self.peek().kind == "const_keyword":
            self.next()
            tok = self.peek()
            if tok.kind != "str":
                self.fail(
                    "expected a constraint string after 'constraint' "
                    "(free text ending at the end of the line)"
                )
            self.next()
            fld["constraint"] = tok.value
        return fld

    def parse_interrupt(self) -> dict[str, Any]:
        self.expect("ident", "interrupt")
        name = self.expect_ident("an interrupt name").value
        tok = self.expect_ident("'from' between the interrupt name and its source")
        if tok.value != "from":
            self.fail("expected 'from' after the interrupt name", tok)
        # The `from` reference has no '@': `interrupt rx_ready from
        # STATUS.RX_READY` (linkage references inside the braces do).
        reg_tok = self.expect_ident("a register name after 'from'")
        self.expect("punct", ".", "'.' between the register and the field")
        fld_tok = self.expect_ident("a field name")
        ref = {"register": reg_tok.value, "field": fld_tok.value}
        self.expect("punct", "{", "'{' to open the interrupt body")
        intr: dict[str, Any] = {"name": name}
        # The `from` reference is the interrupt's `source` unless an
        # explicit `source @ ...` linkage names something else.
        intr.setdefault("source", ref)
        while not (self.peek().kind == "punct" and self.peek().value == "}"):
            tok = self.peek()
            if tok.kind == "eof":
                self.fail("expected '}' to close the interrupt")
            if tok.value == "number":
                self.next()
                intr["number"] = self.expect_dec()
            elif tok.value in ("source", "enable", "status"):
                self.next()
                ref = self.parse_ref()
                intr[tok.value] = ref
            elif tok.value == "clear":
                self.next()
                clear: dict[str, Any] = {}
                if self.peek().kind == "punct" and self.peek().value == ":":
                    self.next()
                    tok = self.expect_ident("a clear kind (W1C, W0C or RC)")
                    clear["kind"] = tok.value
                self.expect("punct", "@", "'@' in the 'clear' linkage")
                reg_tok = self.expect_ident("a register name")
                self.expect("punct", ".", "'.' between the register and the field")
                fld_tok = self.expect_ident("a field name")
                clear["register"] = reg_tok.value
                clear["field"] = fld_tok.value
                intr["clear"] = clear
            else:
                self.fail(
                    "expected 'source', 'enable', 'status', 'clear' or 'number' "
                    "inside the interrupt"
                )
            # Optional separator between linkage items.
            if self.peek().kind == "punct" and self.peek().value in (",", ";"):
                self.next()
        self.next()  # consume '}'
        return intr

    def parse_ref(self) -> dict[str, str]:
        self.expect("punct", "@", "'@' in a linkage")
        reg_tok = self.expect_ident("a register name")
        self.expect("punct", ".", "'.' between the register and the field")
        fld_tok = self.expect_ident("a field name")
        return {"register": reg_tok.value, "field": fld_tok.value}

    def parse_dma_buffer(self) -> dict[str, Any]:
        # The 'dma-buffer' composite keyword is consumed by parse_file.
        name = self.expect_ident("a buffer name").value
        self.expect("punct", "{", "'{' to open the buffer body")
        fields: list[dict[str, Any]] = []
        while not (self.peek().kind == "punct" and self.peek().value == "}"):
            tok = self.peek()
            if tok.kind == "eof":
                self.fail("expected '}' to close the buffer")
            if tok.value != "field":
                self.fail("expected 'field' inside the buffer")
            fields.append(self.parse_dma_field())
        self.next()  # consume '}'
        return {"name": name, "fields": fields}

    def parse_dma_field(self) -> dict[str, Any]:
        self.expect("ident", "field")
        name = self.expect_ident("a field name").value
        self.expect("punct", ":", "':' after the field name")
        self.expect("punct", "@", "'@' before the offset")
        offset = self.expect_hex()
        fld: dict[str, Any] = {"name": name, "offset": offset}

        while self.peek().kind == "punct" and self.peek().value == ",":
            self.next()
            tok = self.peek()
            if tok.value == "owned":
                self.next()
                tok2 = self.expect_ident("'by' after 'owned'")
                if tok2.value != "by":
                    self.fail("expected 'by' after 'owned'", tok2)
                tok3 = self.expect_ident("an owner ('CPU' or 'DEVICE')")
                fld["owner"] = tok3.value
            elif tok.value == "aligned":
                self.next()
                fld["align"] = self.expect_dec()
            elif tok.value == "coherent":
                self.next()
                tok2 = self.expect_ident("a boolean after 'coherent'")
                if tok2.value == "true":
                    fld["coherent"] = True
                elif tok2.value == "false":
                    fld["coherent"] = False
                else:
                    self.fail("expected 'true' or 'false' after 'coherent'", tok2)
            elif tok.value == "written":
                self.next()
                tok2 = self.expect_ident("'as' after 'written'")
                if tok2.value != "as":
                    self.fail("expected 'as' after 'written'", tok2)
                fld["written_as"] = self.expect_dec()
            elif tok.value == "constraint":
                self.next()
                tok2 = self.peek()
                if tok2.kind != "str":
                    self.fail(
                        "expected a constraint string after 'constraint' "
                        "(free text ending at the end of the line)",
                        tok2,
                    )
                self.next()
                fld["constraint"] = tok2.value
            else:
                self.fail(
                    "expected a DMA attribute ('owned by', 'aligned', "
                    "'coherent', 'written as' or 'constraint')"
                )
        # Ownership is the property the whole DMA model is built on; the
        # schema requires it and the text format must carry it.
        if "owner" not in fld:
            self.fail(
                f"missing 'owned by CPU' or 'owned by DEVICE' for field "
                f"'{name}'; every DMA field must state its owner",
                self.peek(),
            )
        return fld


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_source_text(src: str, path: str) -> tuple[dict[str, Any] | None, list[Diagnostic]]:
    """Parse textual `.chw` source into the JSON wire form.

    Returns `(ir, diagnostics)`. On a syntax error, `ir` is `None`
    and `diagnostics` holds one `parse-error` diagnostic with a real
    line/column span. On success the diagnostics list may hold
    advisory items (currently empty) and `ir` is the canonical dict
    the checker and generators consume.
    """
    tokens = tokenize(src)
    parser = Parser(tokens, path)
    try:
        ir = parser.parse_file()
    except _ParseAbort:
        return None, [parser.error] if parser.error else []
    return ir, []


def load_contract(path: str) -> tuple[dict[str, Any] | None, list[Diagnostic]]:
    """Load a `.chw` contract from a path, sniffing the format.

    A file whose first non-whitespace character is `{` is the JSON
    wire format; anything else is the textual format and goes
    through `parse_source_text`. This is the single entry point the
    checker, scripts, and roundtrip tests use, so both formats flow
    through the same pipeline everywhere.
    """
    p = pathlib.Path(path)
    src = p.read_text()
    stripped = src.lstrip()
    if stripped.startswith("{"):
        try:
            ir = json.loads(src)
        except json.JSONDecodeError as e:
            return None, [Diagnostic(
                code="schema-invalid",
                tier="Static",
                subject=Subject("Ir", {"path": path}),
                span=Span(file=path, start=Position(1, 1), end=Position(1, 1)),
                message=f"file is not valid JSON: {e.msg} at line {e.lineno} column {e.colno}.",
            )]
        return ir, []
    return parse_source_text(src, path)


if __name__ == "__main__":
    # Small CLI: parse a textual file, print the IR as one-line JSON.
    # `load_contract` sniffs the format, so a JSON wire file works too.
    import argparse

    ap = argparse.ArgumentParser(
        prog="cancho-hdl parse",
        description="Parse a .chw contract file and print its canonical IR as JSON.",
    )
    ap.add_argument("files", nargs="+", help="One or more .chw files (textual or JSON form).")
    args = ap.parse_args()

    rc = 0
    for f in args.files:
        ir, diags = load_contract(f)
        if ir is None:
            for d in diags:
                span = f"{d.span.start.line}:{d.span.start.column}" if d.span else ""
                print(f"error[{d.code}]: {d.message}  {f}:{span}", file=sys.stderr)
            rc = 1
        else:
            print(json.dumps(ir))
    sys.exit(rc)
