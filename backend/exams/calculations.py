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

# Sentinel for `coalesce` — handled with lazy argument evaluation in `_eval`,
# so a regular Python function can't be used here. Listed in SAFE_FUNCTIONS
# only so `_validate` accepts the call.
_COALESCE = object()

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
    "coalesce": _COALESCE,  # special-cased: returns first non-null arg
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
    ast.Attribute,  # for `player.sex`, `<slug>.<field_key>` syntax
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


class Namespace:
    """Read-only attribute proxy used for `player.X` and `<slug>.X` lookups.

    Snapshot tracker (when supplied) records every successful lookup as
    `{namespace_name}.{attr}` → value pairs, so the calling endpoint can
    persist an audit-of-record alongside the calculated result.
    """

    def __init__(self, name: str, values: Mapping[str, Any], tracker: dict | None = None):
        self._name = name
        self._values = dict(values)
        self._tracker = tracker

    def lookup(self, attr: str) -> Any:
        """Return the value (or None when the attr isn't present / is None)."""
        if attr not in self._values:
            return None
        value = self._values[attr]
        # Track only non-null reads — a missing/None value isn't a "value used".
        if value is not None and self._tracker is not None:
            self._tracker[f"{self._name}.{attr}"] = value
        return value


class FormulaError(ValueError):
    """Raised when a formula references unknown variables, calls a forbidden
    function, or fails to evaluate (e.g. division by zero)."""


# Brackets accept either a bare identifier (`[peso]`) or a single dotted
# identifier (`[player.sex]`, `[pentacompartimental.peso]`).
_BRACKET_RE = re.compile(r"\[([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)\]")


def _normalize(formula: str) -> str:
    """Convert `[name]` and `[ns.attr]` references to bare identifiers."""
    return _BRACKET_RE.sub(r"\1", formula)


def extract_namespace_refs(formula: str) -> set[str]:
    """Return the set of top-level namespace names referenced via dot syntax.

    For `[player.sex] + [pentacompartimental.peso] / [peso]` returns
    `{"player", "pentacompartimental"}`. Used by `compute_result_data` to
    decide which namespaces to assemble (player + which template slugs).
    """
    if not isinstance(formula, str) or not formula.strip():
        return set()
    try:
        tree = ast.parse(_normalize(formula), mode="eval")
    except SyntaxError:
        return set()
    refs: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            refs.add(node.value.id)
    return refs


def _validate(node: ast.AST) -> None:
    for child in ast.walk(node):
        if not isinstance(child, _ALLOWED_NODES):
            raise FormulaError(f"Unsupported expression: {type(child).__name__}")
        if isinstance(child, ast.Call):
            if not isinstance(child.func, ast.Name):
                raise FormulaError("Only direct function calls are allowed")
            if child.func.id not in SAFE_FUNCTIONS:
                raise FormulaError(f"Function not allowed: {child.func.id}")
        if isinstance(child, ast.Attribute):
            # Single-level only: `player.sex` ✓, `a.b.c` ✗
            if not isinstance(child.value, ast.Name):
                raise FormulaError(
                    "Only single-level attribute access is allowed (e.g. `player.sex`)"
                )


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
        # bool is checked first because `bool` is a subclass of `int`.
        if isinstance(node.value, bool):
            return 1.0 if node.value else 0.0
        if isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node.value, str):
            return node.value  # used for equality checks like `player.sex == "M"`
        raise FormulaError(f"Unsupported literal: {node.value!r}")
    if isinstance(node, ast.Name):
        if node.id in variables:
            value = variables[node.id]
            # Bare names are only meaningful for scalar fields; namespace
            # objects must be accessed via dot syntax.
            if isinstance(value, Namespace):
                raise FormulaError(
                    f"'{node.id}' is a namespace; use dot syntax (e.g. `{node.id}.<field>`)."
                )
            return _to_number(value)
        if node.id in SAFE_CONSTANTS:
            return SAFE_CONSTANTS[node.id]
        raise FormulaError(f"Unknown variable: {node.id}")
    if isinstance(node, ast.Attribute):
        # Validator ensures this is a single-level Name.attr.
        ns_name = node.value.id  # type: ignore[union-attr]
        if ns_name not in variables:
            raise FormulaError(f"Unknown namespace: {ns_name}")
        ns = variables[ns_name]
        if not isinstance(ns, Namespace):
            raise FormulaError(f"`{ns_name}` is not a namespace.")
        value = ns.lookup(node.attr)
        if value is None:
            raise FormulaError(f"`{ns_name}.{node.attr}` has no value.")
        # Numbers stay numbers; strings flow through so equality checks work.
        # Anything else gets coerced to a number.
        if isinstance(value, str):
            return value
        return _to_number(value)
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
        fname = node.func.id  # type: ignore[union-attr]
        # Lazy-evaluated: returns the first arg whose evaluation yields a real
        # number, swallowing `FormulaError` from missing or null variables. If
        # every arg is missing/null, the call itself raises so the surrounding
        # formula fails (and the field is stored as None by `compute_result_data`).
        if fname == "coalesce":
            if not node.args:
                raise FormulaError("coalesce: requires at least one argument")
            for arg in node.args:
                try:
                    value = _eval(arg, variables)
                except FormulaError:
                    continue
                if value is not None:
                    return value
            raise FormulaError("coalesce: all arguments were null/missing")

        func = SAFE_FUNCTIONS[fname]
        args = [_eval(arg, variables) for arg in node.args]
        try:
            return float(func(*args))
        except (ValueError, TypeError, ArithmeticError) as exc:
            raise FormulaError(f"Error in {fname}(): {exc}") from exc
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


def _build_player_namespace(player, tracker: dict) -> Namespace:
    """Snapshot the player's attributes that formulas may reference."""
    values = {
        "sex": player.sex or None,
        "current_weight_kg": (
            float(player.current_weight_kg)
            if player.current_weight_kg is not None else None
        ),
        "current_height_cm": (
            float(player.current_height_cm)
            if player.current_height_cm is not None else None
        ),
        "age": player.age,
    }
    return Namespace("player", values, tracker)


def _build_template_namespaces(player, slugs: set[str], tracker: dict) -> dict[str, Namespace]:
    """For each slug, find the player's most recent ExamResult on the matching
    template (in the same club) and expose its `result_data` as a namespace.
    """
    if not slugs or player is None:
        return {}
    # Lazy imports to avoid circular import at module load time.
    from .models import ExamResult, ExamTemplate

    club_id = player.category.club_id
    # Cross-template references resolve to the ACTIVE version of each
    # family so the formula sees the same canonical schema admins are
    # currently editing. The result fetch still fans out across all
    # versions of the family (by family_id) — a recently-renamed field
    # might be missing on an older result, but that's already handled by
    # `result_data.get(...)` returning None.
    templates = (
        ExamTemplate.objects
        .filter(
            slug__in=slugs,
            department__club_id=club_id,
            is_active_version=True,
        )
        .only("id", "slug", "family_id")
    )
    namespaces: dict[str, Namespace] = {}
    for tpl in templates:
        latest = (
            ExamResult.objects
            .filter(player_id=player.id, template__family_id=tpl.family_id)
            .order_by("-recorded_at")
            .first()
        )
        result_data = (latest.result_data if latest else {}) or {}
        namespaces[tpl.slug] = Namespace(tpl.slug, result_data, tracker)
    return namespaces


def compute_result_data(
    template,
    raw_data: Mapping[str, Any],
    player=None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run all calculated fields in a template's config_schema.

    Returns `(result_data, inputs_snapshot)`:
      - `result_data` is `raw_data` plus every successfully-computed
        calculated field. Failed formulas store None so the save still
        succeeds and the gap is visible.
      - `inputs_snapshot` records every external value (`player.X`,
        `<slug>.Y`) that was actually read while evaluating the formulas.
        Empty when no namespace references were used. Persist alongside
        the ExamResult to preserve the exact inputs at calculation time.
    """
    schema = template.config_schema or {}
    fields = schema.get("fields", []) or []
    out: dict[str, Any] = dict(raw_data)
    snapshot: dict[str, Any] = {}

    # Collect every namespace mentioned across all calculated formulas so we
    # only build/load each one once.
    all_refs: set[str] = set()
    for field in fields:
        if isinstance(field, dict) and field.get("type") == "calculated" and field.get("formula"):
            all_refs.update(extract_namespace_refs(field["formula"]))

    namespaces: dict[str, Namespace] = {}
    if "player" in all_refs and player is not None:
        namespaces["player"] = _build_player_namespace(player, snapshot)
    template_slugs = all_refs - {"player"}
    if template_slugs:
        namespaces.update(_build_template_namespaces(player, template_slugs, snapshot))

    for field in fields:
        if not isinstance(field, dict):
            continue
        if field.get("type") != "calculated":
            continue
        key = field.get("key")
        formula = field.get("formula")
        if not key or not formula:
            continue
        variables = {**out, **namespaces}
        try:
            out[key] = evaluate_formula(formula, variables)
        except FormulaError:
            # Failed formulas store None — partial data is still useful and
            # admins need to see the gap to fix the formula.
            out[key] = None
    return out, snapshot
