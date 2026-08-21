"""
src/whatif/formula_eval.py
=============================
Safe arithmetic-expression evaluator for First-Principle "Formula" cells
(Model Definition's Formula Editor, see FORMULAS_COLUMNS in config_io.py).

Deliberately NOT Python's eval()/exec() on user-supplied text -- that would
let a saved formula run arbitrary code. Instead, every expression is parsed
into an AST (ast.parse(..., mode="eval")) and walked against an explicit
whitelist of node types and function names; anything outside that whitelist
raises FormulaError before any evaluation happens, both at validate time
(no data needed) and at evaluate time (row values needed).
"""
from __future__ import annotations

import ast
import math
import operator


class FormulaError(ValueError):
    """A formula that fails to parse, or uses a node type/function outside
    the whitelist below."""


_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.FloorDiv: operator.floordiv,
}
_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_FUNCTIONS = {
    "sqrt": math.sqrt,
    "log": math.log,
    "log10": math.log10,
    "log2": math.log2,
    "exp": math.exp,
    "abs": abs,
    "min": min,
    "max": max,
    "pow": pow,
    "round": round,
}


def _parse(expr: str) -> ast.Expression:
    if not expr or not expr.strip():
        raise FormulaError("Formula is empty.")
    try:
        return ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise FormulaError(f"Invalid formula syntax: {exc.msg}") from exc


def _walk_check(node: ast.AST) -> None:
    """Raises FormulaError the first time it finds something outside the
    whitelist -- run at validate/save time so a bad formula is rejected
    before it's ever stored, not discovered later at runtime."""
    if isinstance(node, ast.Expression):
        _walk_check(node.body)
    elif isinstance(node, ast.BinOp):
        if type(node.op) not in _BIN_OPS:
            raise FormulaError(f"Operator '{type(node.op).__name__}' isn't supported.")
        _walk_check(node.left)
        _walk_check(node.right)
    elif isinstance(node, ast.UnaryOp):
        if type(node.op) not in _UNARY_OPS:
            raise FormulaError(f"Unary operator '{type(node.op).__name__}' isn't supported.")
        _walk_check(node.operand)
    elif isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS:
            func_name = getattr(node.func, "id", None) or ast.dump(node.func)
            raise FormulaError(
                f"Function '{func_name}' isn't supported. Allowed: {', '.join(sorted(_FUNCTIONS))}."
            )
        if node.keywords:
            raise FormulaError("Keyword arguments aren't supported in a formula.")
        for arg in node.args:
            _walk_check(arg)
    elif isinstance(node, ast.Name):
        return
    elif isinstance(node, ast.Constant):
        if not isinstance(node.value, (int, float)) or isinstance(node.value, bool):
            raise FormulaError("Only numeric constants are supported.")
    else:
        raise FormulaError(f"'{type(node).__name__}' isn't supported in a formula.")


def validate_formula(expr: str) -> list[str]:
    """Syntax/whitelist-only check -- no variable values needed, so this can
    run the instant a formula is typed, before any historian row exists.
    Returns a list of error messages (empty if valid)."""
    try:
        _walk_check(_parse(expr))
    except FormulaError as exc:
        return [str(exc)]
    return []


def extract_variable_names(expr: str) -> list[str]:
    """Every distinct Name this formula reads as a variable (not as a
    function call), in first-seen order. Used to auto-populate Model
    Definition's Input parameter_N cells so the engine's dependency graph
    (built off those exact cells -- see engine.py::build_dependency_graph)
    schedules this parameter after whatever it depends on."""
    tree = _parse(expr)
    names: list[str] = []
    seen: set[str] = set()

    def walk(node: ast.AST) -> None:
        if isinstance(node, ast.Call):
            for arg in node.args:
                walk(arg)
            return
        if isinstance(node, ast.Name):
            if node.id not in seen:
                seen.add(node.id)
                names.append(node.id)
            return
        for child in ast.iter_child_nodes(node):
            walk(child)

    walk(tree.body)
    return names


def evaluate_formula(expr: str, variables: dict) -> float:
    """Evaluates `expr` against `variables` (name -> numeric value).
    Raises FormulaError for anything outside the whitelist, and a plain
    KeyError for a referenced name missing from `variables` -- both are
    exceptions the caller (engine.py::simulate_and_update_parameter)
    already catches broadly and degrades gracefully from (logs, keeps the
    baseline value), so no extra error handling is needed at the call site."""
    tree = _parse(expr)
    _walk_check(tree)

    def ev(node: ast.AST):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id not in variables:
                raise KeyError(node.id)
            return variables[node.id]
        if isinstance(node, ast.BinOp):
            return _BIN_OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp):
            return _UNARY_OPS[type(node.op)](ev(node.operand))
        if isinstance(node, ast.Call):
            func = _FUNCTIONS[node.func.id]
            return func(*[ev(a) for a in node.args])
        raise FormulaError(f"'{type(node).__name__}' isn't supported in a formula.")

    return float(ev(tree.body))
