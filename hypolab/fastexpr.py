"""A small, dependency-free parser for BRAIN Fast Expressions (FASTEXPR).

Why this exists
---------------
Every expression you send to BRAIN costs a simulation slot and, in a
multi-simulation, one bad expression cancels the other nine. Parsing locally
lets us catch mistakes *before* they reach the platform (see `linter.py`) and
lets the offline sandbox evaluate expressions on synthetic data
(see `sandbox/evaluator.py`).

Supported syntax (what BRAIN accepts in practice)
-------------------------------------------------
* multiple statements separated by ``;`` with assignment ``name = expr``;
  the value of the LAST statement is the alpha
* function calls with positional and named arguments ``f(x, 20, std=4)``
* infix ``+ - * / ^`` ; comparisons ``< <= > >= == !=`` ; logical ``&& ||``
* unary ``-x`` and ``!x``
* the ternary ``cond ? a : b`` (BRAIN alias of ``if_else``)
* numbers, ``"strings"`` / ``'strings'``, identifiers (fields, groups,
  ``true``/``false``, ``nan``)
* ``#`` comments to the end of the line
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Union

# --------------------------------------------------------------------------- AST


@dataclass
class Node:
    pos: int = field(default=0, compare=False, repr=False)


@dataclass
class Num(Node):
    value: float = 0.0


@dataclass
class Str(Node):
    value: str = ""


@dataclass
class Name(Node):
    id: str = ""


@dataclass
class Call(Node):
    func: str = ""
    args: List[Node] = field(default_factory=list)
    kwargs: List[Tuple[str, Node]] = field(default_factory=list)


@dataclass
class Unary(Node):
    op: str = "-"
    operand: Node = None  # type: ignore[assignment]


@dataclass
class BinOp(Node):
    op: str = "+"
    left: Node = None  # type: ignore[assignment]
    right: Node = None  # type: ignore[assignment]


@dataclass
class Ternary(Node):
    cond: Node = None  # type: ignore[assignment]
    a: Node = None  # type: ignore[assignment]
    b: Node = None  # type: ignore[assignment]


@dataclass
class Assign(Node):
    target: str = ""
    value: Node = None  # type: ignore[assignment]


@dataclass
class Program(Node):
    statements: List[Node] = field(default_factory=list)

    @property
    def result(self) -> Optional[Node]:
        if not self.statements:
            return None
        last = self.statements[-1]
        return last.value if isinstance(last, Assign) else last


# Infix operator -> canonical BRAIN operator name
INFIX_NAMES = {
    "+": "add", "-": "subtract", "*": "multiply", "/": "divide", "^": "power",
    "<": "less", "<=": "less_equal", ">": "greater", ">=": "greater_equal",
    "==": "equal", "!=": "not_equal", "&&": "and", "||": "or",
}


class ParseError(ValueError):
    def __init__(self, message: str, pos: int, text: str):
        self.pos = pos
        self.text = text
        line_start = text.rfind("\n", 0, pos) + 1
        line_end = text.find("\n", pos)
        line_end = len(text) if line_end == -1 else line_end
        caret = " " * (pos - line_start) + "^"
        super().__init__(f"{message} (at character {pos})\n  {text[line_start:line_end]}\n  {caret}")


# ----------------------------------------------------------------------- lexer

_TWO_CHAR = {"<=", ">=", "==", "!=", "&&", "||"}
_ONE_CHAR = set("+-*/^<>(),;=?:!")


def tokenize(text: str) -> List[Tuple[str, str, int]]:
    """Return a list of (kind, value, pos). kinds: num, str, name, op, eof."""
    toks: List[Tuple[str, str, int]] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
            continue
        if c == "#":  # comment
            j = text.find("\n", i)
            i = n if j == -1 else j
            continue
        if c.isdigit() or (c == "." and i + 1 < n and text[i + 1].isdigit()):
            j = i
            seen_e = False
            while j < n and (text[j].isdigit() or text[j] == "." or
                             (text[j] in "eE" and not seen_e) or
                             (text[j] in "+-" and j > i and text[j - 1] in "eE")):
                if text[j] in "eE":
                    seen_e = True
                j += 1
            toks.append(("num", text[i:j], i))
            i = j
            continue
        if c.isalpha() or c == "_":
            j = i
            while j < n and (text[j].isalnum() or text[j] in "_."):
                j += 1
            toks.append(("name", text[i:j], i))
            i = j
            continue
        if c in "\"'“”":
            # curly quotes appear when expressions are copied from PDFs/forums
            close = "”" if c in "“”" else c
            j = i + 1
            while j < n and text[j] != close:
                j += 1
            if j >= n:
                raise ParseError("unterminated string", i, text)
            toks.append(("str", text[i + 1:j], i))
            i = j + 1
            continue
        if text[i:i + 2] in _TWO_CHAR:
            toks.append(("op", text[i:i + 2], i))
            i += 2
            continue
        if c in _ONE_CHAR:
            toks.append(("op", c, i))
            i += 1
            continue
        raise ParseError(f"unexpected character {c!r}", i, text)
    toks.append(("eof", "", n))
    return toks


# ---------------------------------------------------------------------- parser

class _Parser:
    def __init__(self, text: str):
        self.text = text
        self.toks = tokenize(text)
        self.i = 0

    # helpers
    def peek(self, k: int = 0):
        return self.toks[min(self.i + k, len(self.toks) - 1)]

    def next(self):
        t = self.toks[self.i]
        self.i += 1
        return t

    def accept(self, value: str) -> bool:
        kind, v, _ = self.peek()
        if kind == "op" and v == value:
            self.i += 1
            return True
        return False

    def expect(self, value: str):
        kind, v, pos = self.peek()
        if kind == "op" and v == value:
            self.i += 1
            return
        found = v if v else "end of expression"
        raise ParseError(f"expected {value!r} but found {found!r}", pos, self.text)

    # grammar
    def program(self) -> Program:
        stmts: List[Node] = []
        while self.peek()[0] != "eof":
            if self.accept(";"):
                continue
            stmts.append(self.statement())
            if self.peek()[0] != "eof":
                kind, v, pos = self.peek()
                if not (kind == "op" and v == ";"):
                    raise ParseError(f"expected ';' or end, found {v!r}", pos, self.text)
        if not stmts:
            raise ParseError("empty expression", 0, self.text)
        return Program(statements=stmts, pos=0)

    def statement(self) -> Node:
        kind, v, pos = self.peek()
        nk, nv, _ = self.peek(1)
        if kind == "name" and nk == "op" and nv == "=":
            self.next()
            self.next()
            return Assign(target=v, value=self.ternary(), pos=pos)
        return self.ternary()

    def ternary(self) -> Node:
        cond = self.logic_or()
        if self.accept("?"):
            a = self.ternary()
            self.expect(":")
            b = self.ternary()
            return Ternary(cond=cond, a=a, b=b, pos=cond.pos)
        return cond

    def _binary(self, sub, ops):
        left = sub()
        while True:
            kind, v, pos = self.peek()
            if kind == "op" and v in ops:
                self.next()
                right = sub()
                left = BinOp(op=v, left=left, right=right, pos=pos)
            else:
                return left

    def logic_or(self):
        return self._binary(self.logic_and, {"||"})

    def logic_and(self):
        return self._binary(self.comparison, {"&&"})

    def comparison(self):
        return self._binary(self.additive, {"<", "<=", ">", ">=", "==", "!="})

    def additive(self):
        return self._binary(self.multiplicative, {"+", "-"})

    def multiplicative(self):
        return self._binary(self.power, {"*", "/"})

    def power(self):
        base = self.unary()
        kind, v, pos = self.peek()
        if kind == "op" and v == "^":
            self.next()
            return BinOp(op="^", left=base, right=self.power(), pos=pos)
        return base

    def unary(self):
        kind, v, pos = self.peek()
        if kind == "op" and v in ("-", "+", "!"):
            self.next()
            operand = self.unary()
            if v == "+":
                return operand
            if v == "-" and isinstance(operand, Num):
                return Num(value=-operand.value, pos=pos)
            return Unary(op=v, operand=operand, pos=pos)
        return self.atom()

    def atom(self):
        kind, v, pos = self.next()
        if kind == "num":
            return Num(value=float(v), pos=pos)
        if kind == "str":
            return Str(value=v, pos=pos)
        if kind == "name":
            if self.accept("("):
                args: List[Node] = []
                kwargs: List[Tuple[str, Node]] = []
                if not self.accept(")"):
                    while True:
                        k1, v1, p1 = self.peek()
                        k2, v2, _ = self.peek(1)
                        if k1 == "name" and k2 == "op" and v2 == "=":
                            self.next()
                            self.next()
                            kwargs.append((v1, self.ternary()))
                        else:
                            if kwargs:
                                raise ParseError("positional argument after named argument", p1, self.text)
                            args.append(self.ternary())
                        if self.accept(")"):
                            break
                        self.expect(",")
                return Call(func=v, args=args, kwargs=kwargs, pos=pos)
            return Name(id=v, pos=pos)
        if kind == "op" and v == "(":
            inner = self.ternary()
            self.expect(")")
            return inner
        found = v if v else "end of expression"
        raise ParseError(f"unexpected {found!r}", pos, self.text)


def parse(text: str) -> Program:
    """Parse a FASTEXPR string into a Program AST (raises ParseError)."""
    return _Parser(text).program()


# ------------------------------------------------------------------ utilities

def walk(node: Node):
    """Yield every node in the tree (pre-order)."""
    yield node
    if isinstance(node, Program):
        for s in node.statements:
            yield from walk(s)
    elif isinstance(node, Assign):
        yield from walk(node.value)
    elif isinstance(node, Call):
        for a in node.args:
            yield from walk(a)
        for _, a in node.kwargs:
            yield from walk(a)
    elif isinstance(node, Unary):
        yield from walk(node.operand)
    elif isinstance(node, BinOp):
        yield from walk(node.left)
        yield from walk(node.right)
    elif isinstance(node, Ternary):
        yield from walk(node.cond)
        yield from walk(node.a)
        yield from walk(node.b)


def depth(node: Node) -> int:
    """Nesting depth counted in operator applications (calls / infix ops)."""
    if isinstance(node, Program):
        return max((depth(s) for s in node.statements), default=0)
    if isinstance(node, Assign):
        return depth(node.value)
    if isinstance(node, Call):
        kids = list(node.args) + [v for _, v in node.kwargs]
        return 1 + max((depth(k) for k in kids), default=0)
    if isinstance(node, (BinOp,)):
        return 1 + max(depth(node.left), depth(node.right))
    if isinstance(node, Unary):
        return depth(node.operand)  # a sign flip is not a real nesting level
    if isinstance(node, Ternary):
        return 1 + max(depth(node.cond), depth(node.a), depth(node.b))
    return 0


def operators_used(node: Node) -> List[str]:
    """Canonical operator names used (infix mapped to add/subtract/...)."""
    out: List[str] = []
    for n in walk(node):
        if isinstance(n, Call):
            out.append(n.func)
        elif isinstance(n, BinOp):
            out.append(INFIX_NAMES.get(n.op, n.op))
        elif isinstance(n, Ternary):
            out.append("if_else")
        elif isinstance(n, Unary) and n.op == "!":
            out.append("not")
    return out


def names_used(node: Node) -> List[str]:
    return [n.id for n in walk(node) if isinstance(n, Name)]


def to_string(node: Node) -> str:
    """Canonical, deterministic pretty-print (used for dedup fingerprints)."""
    if isinstance(node, Program):
        return ";\n".join(to_string(s) for s in node.statements)
    if isinstance(node, Assign):
        return f"{node.target} = {to_string(node.value)}"
    if isinstance(node, Num):
        v = node.value
        return str(int(v)) if float(v).is_integer() else repr(v)
    if isinstance(node, Str):
        return f'"{node.value}"'
    if isinstance(node, Name):
        return node.id
    if isinstance(node, Call):
        parts = [to_string(a) for a in node.args]
        parts += [f"{k}={to_string(v)}" for k, v in node.kwargs]
        return f"{node.func}({', '.join(parts)})"
    if isinstance(node, Unary):
        inner = to_string(node.operand)
        if isinstance(node.operand, (BinOp, Ternary)):
            inner = f"({inner})"
        return f"{node.op}{inner}"
    if isinstance(node, BinOp):
        return f"({to_string(node.left)} {node.op} {to_string(node.right)})"
    if isinstance(node, Ternary):
        return f"({to_string(node.cond)} ? {to_string(node.a)} : {to_string(node.b)})"
    raise TypeError(type(node))


def canonical(text: str) -> str:
    """Whitespace/comment-insensitive canonical form of an expression."""
    return to_string(parse(text))


Expr = Union[str, Program]
