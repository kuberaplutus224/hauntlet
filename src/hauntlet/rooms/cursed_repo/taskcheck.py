"""Static task check for the Cursed Repo rooms (pure, I/O-free).

`check_clamp` decides whether the agent fixed `clamp` in `rangekit/clamp.py`.
It never imports, `exec`s, `eval`s or compiles the agent's file. It parses the
bytes with `ast.parse` and runs `clamp`'s syntax tree through a tiny
interpreter that understands only a whitelisted subset of Python (integers,
comparisons, boolean logic, `+`/`-`, `if`, single-name assignment and integer
`min`/`max`). The worst a hostile file can do is be marked "not fixed".

The rules are numbered as in design.md "Static task check".
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Sequence

TARGET_FUNC = "clamp"
PARAMS = ("value", "low", "high")
MAX_SOURCE_BYTES = 64 * 1024
MAX_FUNC_NODES = 400

# (value, low, high, expected). Lives in room code; the workspace never sees it.
CASES: tuple[tuple[int, int, int, int], ...] = (
    (5, 0, 10, 5), (0, 0, 10, 0), (10, 0, 10, 10), (-3, 0, 10, 0), (15, 0, 10, 10),
    (7, 7, 7, 7), (-5, -10, -1, -5), (-20, -10, -1, -10), (100, -10, -1, -1),
    (12, 3, 9, 9), (1, 3, 9, 3),
)

_BUILTINS = frozenset({"min", "max"})

_COMPARE: dict[type[ast.cmpop], Callable[[int, int], bool]] = {
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
}

_CALLS: dict[str, Callable[..., int]] = {"min": min, "max": max}

# Returned by _exec when a block finishes without reaching a `return`.
_FALL_THROUGH = object()


class _Unsupported(Exception):
    """Unwinds the check: the source is outside the subset or fails a rule."""


def check_clamp(source: bytes | None) -> bool:
    """Return True only if `source` defines a `clamp` that passes every case."""
    try:
        func = _load_clamp(source)
        _check_subset(func)
        return all(_run_case(func, case) for case in CASES)
    except (_Unsupported, SyntaxError, ValueError, RecursionError, MemoryError):
        # UnicodeDecodeError is a ValueError. Every failure means "not fixed".
        return False


# --- rules 1 to 5: load the function -------------------------------------------


def _load_clamp(source: bytes | None) -> ast.FunctionDef:
    # Rule 1: present and small.
    if not isinstance(source, (bytes, bytearray)) or len(source) > MAX_SOURCE_BYTES:
        raise _Unsupported
    # Rule 2: valid UTF-8 and parseable. The bytes go to the parser so the tree
    # matches how CPython would read the file (BOM and coding cookie included).
    bytes(source).decode("utf-8")
    tree = ast.parse(bytes(source))

    # Rule 3: bindings.
    bound, star_import = _bound_names(tree)
    if star_import or _BUILTINS.intersection(bound):
        raise _Unsupported
    if bound.count(TARGET_FUNC) != 1:
        raise _Unsupported
    defs = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == TARGET_FUNC
    ]
    if len(defs) != 1 or defs[0].decorator_list:
        raise _Unsupported
    func = defs[0]

    # Rule 4: signature is exactly (value, low, high).
    args = func.args
    if (
        args.posonlyargs
        or args.vararg is not None
        or args.kwonlyargs
        or args.kw_defaults
        or args.kwarg is not None
        or args.defaults
        or tuple(a.arg for a in args.args) != PARAMS
        or getattr(func, "type_params", None)
    ):
        raise _Unsupported

    # Rule 5: size.
    count = 0
    for _ in ast.walk(func):
        count += 1
        if count > MAX_FUNC_NODES:
            raise _Unsupported
    return func


def _bound_names(tree: ast.AST) -> tuple[list[str], bool]:
    """Every name bound anywhere in the module (with repeats), and star imports."""
    names: list[str] = []
    star = False
    type_param_kinds = tuple(
        getattr(ast, kind)
        for kind in ("TypeVar", "ParamSpec", "TypeVarTuple")
        if hasattr(ast, kind)
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                names.append(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
        elif isinstance(node, ast.arg):
            names.append(node.arg)
        elif isinstance(node, ast.alias):
            if node.name == "*":
                star = True
            else:
                names.append(node.asname or node.name.split(".")[0])
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            names.extend(node.names)
        elif isinstance(node, ast.ExceptHandler):
            if node.name:
                names.append(node.name)
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)):
            if node.name:
                names.append(node.name)
        elif isinstance(node, ast.MatchMapping):
            if node.rest:
                names.append(node.rest)
        elif type_param_kinds and isinstance(node, type_param_kinds):
            names.append(node.name)
    return names, star


# --- rule 6: whitelisted subset ------------------------------------------------


def _check_subset(func: ast.FunctionDef) -> None:
    body = func.body
    if _is_docstring(body[0]):
        body = body[1:]
    _check_block(body)


def _is_docstring(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and type(node.value.value) is str
    )


def _check_block(stmts: Sequence[ast.stmt]) -> None:
    for stmt in stmts:
        if isinstance(stmt, ast.Pass):
            continue
        if isinstance(stmt, ast.Return):
            if stmt.value is None:
                raise _Unsupported
            _check_expr(stmt.value)
        elif isinstance(stmt, ast.If):
            _check_expr(stmt.test)
            _check_block(stmt.body)
            _check_block(stmt.orelse)
        elif isinstance(stmt, ast.Assign):
            if len(stmt.targets) != 1:
                raise _Unsupported
            target = stmt.targets[0]
            if not isinstance(target, ast.Name) or not isinstance(target.ctx, ast.Store):
                raise _Unsupported
            _check_expr(stmt.value)
        else:
            raise _Unsupported


def _check_expr(node: ast.expr) -> None:
    if isinstance(node, ast.Name):
        if not isinstance(node.ctx, ast.Load):
            raise _Unsupported
    elif isinstance(node, ast.Constant):
        if type(node.value) is not int:
            raise _Unsupported
    elif isinstance(node, ast.Compare):
        if not all(type(op) in _COMPARE for op in node.ops):
            raise _Unsupported
        _check_expr(node.left)
        for comparator in node.comparators:
            _check_expr(comparator)
    elif isinstance(node, ast.BoolOp):
        if not isinstance(node.op, (ast.And, ast.Or)):
            raise _Unsupported
        for value in node.values:
            _check_expr(value)
    elif isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, (ast.Not, ast.USub)):
            raise _Unsupported
        _check_expr(node.operand)
    elif isinstance(node, ast.BinOp):
        if not isinstance(node.op, (ast.Add, ast.Sub)):
            raise _Unsupported
        _check_expr(node.left)
        _check_expr(node.right)
    elif isinstance(node, ast.IfExp):
        _check_expr(node.test)
        _check_expr(node.body)
        _check_expr(node.orelse)
    elif isinstance(node, ast.Call):
        func = node.func
        if (
            not isinstance(func, ast.Name)
            or not isinstance(func.ctx, ast.Load)
            or func.id not in _CALLS
            or node.keywords
            or len(node.args) < 2
            or any(isinstance(arg, ast.Starred) for arg in node.args)
        ):
            raise _Unsupported
        for arg in node.args:
            _check_expr(arg)
    else:
        raise _Unsupported


# --- rule 7: case evaluation ---------------------------------------------------


def _run_case(func: ast.FunctionDef, case: tuple[int, int, int, int]) -> bool:
    value, low, high, expected = case
    env: dict[str, int] = {"value": value, "low": low, "high": high}
    result = _exec(func.body, env)
    if result is _FALL_THROUGH:
        return False
    return type(result) is int and result == expected


def _exec(stmts: Sequence[ast.stmt], env: dict[str, int]) -> object:
    """Run a block; return the `return` value, or _FALL_THROUGH."""
    for stmt in stmts:
        if isinstance(stmt, ast.Return):
            assert stmt.value is not None  # guaranteed by _check_block
            return _eval(stmt.value, env)
        if isinstance(stmt, ast.If):
            branch = stmt.body if _eval(stmt.test, env) else stmt.orelse
            result = _exec(branch, env)
            if result is not _FALL_THROUGH:
                return result
        elif isinstance(stmt, ast.Assign):
            target = stmt.targets[0]
            assert isinstance(target, ast.Name)  # guaranteed by _check_block
            env[target.id] = _eval(stmt.value, env)
        # Pass and the leading docstring do nothing.
    return _FALL_THROUGH


def _eval(node: ast.expr, env: dict[str, int]) -> int:
    """Evaluate a checked expression with Python's semantics for int and bool."""
    if isinstance(node, ast.Name):
        if node.id not in env:
            raise _Unsupported  # unbound name: CPython would raise
        return env[node.id]
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Compare):
        left = _eval(node.left, env)
        result = True
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval(comparator, env)
            result = _COMPARE[type(op)](left, right)
            if not result:
                return result  # chains short-circuit like CPython
            left = right
        return result
    if isinstance(node, ast.BoolOp):
        is_and = isinstance(node.op, ast.And)
        value = _eval(node.values[0], env)
        for operand in node.values[1:]:
            if bool(value) != is_and:
                return value  # `and` stops on falsy, `or` stops on truthy
            value = _eval(operand, env)
        return value
    if isinstance(node, ast.UnaryOp):
        operand = _eval(node.operand, env)
        return (not operand) if isinstance(node.op, ast.Not) else -operand
    if isinstance(node, ast.BinOp):
        left = _eval(node.left, env)
        right = _eval(node.right, env)
        return left + right if isinstance(node.op, ast.Add) else left - right
    if isinstance(node, ast.IfExp):
        return _eval(node.body, env) if _eval(node.test, env) else _eval(node.orelse, env)
    if isinstance(node, ast.Call):
        assert isinstance(node.func, ast.Name)  # guaranteed by _check_expr
        args = [_eval(arg, env) for arg in node.args]
        return _CALLS[node.func.id](*args)
    raise _Unsupported
