"""Safe formula evaluator for ExamTemplate calculated fields.

Admins type expressions like `([dist_30] * 1.5) / [hr_avg]` in Django Admin.
We must never run those through `eval()`. Instead we:

1. Replace `[var_name]` with bare identifiers `var_name` (the bracket syntax
   from PROJECT.md is just a readable convention for admins).
2. Parse the expression to a Python AST.
3. Walk the AST, allowing only a whitelist of node types (numeric literals,
   names, arithmetic ops, comparisons, calls to a small whitelist of math
   functions). Anything else raises FormulaError.
4. Resolve Name nodes from the supplied variables dict.

This rejects attribute access, subscripts, comprehensions, lambdas, imports,
and every other Python feature an attacker could weaponise.
"""
from __future__ import annotations

import ast
import math
import re
from typing import Any, Mapping

# A whitelist of safe math functions admins can call inside formulas.
SAFE_FUNCTIONS: dict[str, Any] = {
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
    "sqrt": math.sqrt,
    "log": math.log,        # natural log by default; log(x, base) supported
    "log10": math.log10,
    "ln": math.log,
    "exp": math.exp,
    "pow": math.pow,
}

SAFE_CONSTANTS: dict[str, float] = {
    "pi": math.pi,
    "e": math.e,
}

# Top-level node types we permit — anything else is rejected up front.
_ALLOWED_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Call,
    ast.IfExp,
    ast.Compare,
    ast.BoolOp,
    # Operators
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.UAdd,
    ast.USub,
    ast.Not,
    ast.And,
    ast.Or,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
)


class FormulaError(ValueError):
    """Raised when a formula references unknown variables, calls a forbidden
    function, or fails to evaluate (e.g. division by zero)."""


_BRACKET_RE = re.compile(r"\[([A-Za-z_][A-Za-z0-9_]*)\]")


def _normalize(formula: str) -> str:
    """Convert `[name]` references to bare `name` identifiers."""
    return _BRACKET_RE.sub(r"\1", formula)


def _validate(node: ast.AST) -> None:
    for child in ast.walk(node):
        if not isinstance(child, _ALLOWED_NODES):
            raise FormulaError(f"Unsupported expression: {type(child).__name__}")
        if isinstance(child, ast.Call):
            if not isinstance(child.func, ast.Name):
                raise FormulaError("Only direct function calls are allowed")
            if child.func.id not in SAFE_FUNCTIONS:
                raise FormulaError(f"Function not allowed: {child.func.id}")


def _to_number(value: Any) -> float:
    if value is None:
        raise FormulaError("Variable value is None")
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise FormulaError(f"Variable value is not numeric: {value!r}") from exc


def _eval(node: ast.AST, variables: Mapping[str, Any]) -> Any:
    if isinstance(node, ast.Expression):
        return _eval(node.body, variables)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node.value, bool):
            return 1.0 if node.value else 0.0
        raise FormulaError(f"Unsupported literal: {node.value!r}")
    if isinstance(node, ast.Name):
        if node.id in variables:
            return _to_number(variables[node.id])
        if node.id in SAFE_CONSTANTS:
            return SAFE_CONSTANTS[node.id]
        raise FormulaError(f"Unknown variable: {node.id}")
    if isinstance(node, ast.UnaryOp):
        operand = _eval(node.operand, variables)
        if isinstance(node.op, ast.UAdd):
            return +operand
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.Not):
            return 1.0 if not operand else 0.0
    if isinstance(node, ast.BinOp):
        left = _eval(node.left, variables)
        right = _eval(node.right, variables)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if right == 0:
                raise FormulaError("Division by zero")
            return left / right
        if isinstance(node.op, ast.FloorDiv):
            if right == 0:
                raise FormulaError("Division by zero")
            return left // right
        if isinstance(node.op, ast.Mod):
            return left % right
        if isinstance(node.op, ast.Pow):
            return left ** right
    if isinstance(node, ast.IfExp):
        return _eval(node.body, variables) if _eval(node.test, variables) else _eval(node.orelse, variables)
    if isinstance(node, ast.Compare):
        left = _eval(node.left, variables)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval(comparator, variables)
            if isinstance(op, ast.Eq) and not (left == right):
                return 0.0
            if isinstance(op, ast.NotEq) and not (left != right):
                return 0.0
            if isinstance(op, ast.Lt) and not (left < right):
                return 0.0
            if isinstance(op, ast.LtE) and not (left <= right):
                return 0.0
            if isinstance(op, ast.Gt) and not (left > right):
                return 0.0
            if isinstance(op, ast.GtE) and not (left >= right):
                return 0.0
            left = right
        return 1.0
    if isinstance(node, ast.BoolOp):
        values = [_eval(v, variables) for v in node.values]
        if isinstance(node.op, ast.And):
            return 1.0 if all(values) else 0.0
        if isinstance(node.op, ast.Or):
            return 1.0 if any(values) else 0.0
    if isinstance(node, ast.Call):
        func = SAFE_FUNCTIONS[node.func.id]  # type: ignore[union-attr]
        args = [_eval(arg, variables) for arg in node.args]
        try:
            return float(func(*args))
        except (ValueError, TypeError, ArithmeticError) as exc:
            raise FormulaError(f"Error in {node.func.id}(): {exc}") from exc
    raise FormulaError(f"Unsupported expression: {type(node).__name__}")


def evaluate_formula(formula: str, variables: Mapping[str, Any]) -> float:
    """Safely evaluate a formula string against a mapping of variables.

    Raises FormulaError on unknown variables, forbidden constructs, or runtime
    arithmetic errors. Numeric output is always coerced to float.
    """
    if not isinstance(formula, str) or not formula.strip():
        raise FormulaError("Formula is empty")
    normalized = _normalize(formula)
    try:
        tree = ast.parse(normalized, mode="eval")
    except SyntaxError as exc:
        raise FormulaError(f"Invalid syntax: {exc.msg}") from exc
    _validate(tree)
    return float(_eval(tree, variables))


def compute_result_data(template, raw_data: Mapping[str, Any]) -> dict[str, Any]:
    """Run all calculated fields in a template's config_schema.

    Returns a new dict that is `raw_data` plus every successfully-computed
    calculated field. Fields that fail to evaluate are stored as None so the
    save still succeeds and the frontend can flag the gap visibly.
    """
    schema = template.config_schema or {}
    fields = schema.get("fields", []) or []
    out: dict[str, Any] = dict(raw_data)
    for field in fields:
        if not isinstance(field, dict):
            continue
        if field.get("type") != "calculated":
            continue
        key = field.get("key")
        formula = field.get("formula")
        if not key or not formula:
            continue
        try:
            out[key] = evaluate_formula(formula, out)
        except FormulaError:
            # Capture failure but don't abort the save — partial data is still
            # useful and admins need to see the gap to fix the formula.
            out[key] = None
    return out
