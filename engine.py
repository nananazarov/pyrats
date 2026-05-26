"""
File: engine.py
PYRATS — Evaluation Engine & Parser
"""

import re
from typing import Any, Dict, Optional

from models import RuleRow, TableSchema


def _parse_literal(s: str) -> Any:
    """Parses string representation of a literal to a Python value."""
    s = s.strip()
    if s.lower() == "true":
        return True
    if s.lower() == "false":
        return False
    # Quotes strings (single or double)
    if len(s) >= 2 and s[0] in ('"', "'") and s[-1] == s[0]:
        return s[1:-1]
    # Numbers
    try:
        if "." in s:
            return float(s)
        return int(s)
    except ValueError:
        return s


def _eval_single_op(expr: str, value: Any) -> bool:
    """Evaluates a single simple comparison like '>= 18', '== "active"', etc."""
    expr = expr.strip()
    for op_str, op_fn in [
        (">=", lambda a, b: a >= b),
        ("<=", lambda a, b: a <= b),
        ("!=", lambda a, b: a != b),
        ("==", lambda a, b: a == b),
        (">", lambda a, b: a > b),
        ("<", lambda a, b: a < b),
    ]:
        if expr.startswith(op_str):
            operand = _parse_literal(expr[len(op_str) :].strip())
            try:
                return bool(op_fn(value, operand))
            except TypeError:
                return False
    return False


def _coerce_value(value: Any, col_type: str) -> Any:
    """Coerces input value to the column type."""
    if col_type == "number":
        try:
            f = float(str(value))
            return int(f) if f == int(f) else f
        except (ValueError, TypeError):
            return value
    elif col_type == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes")
        return bool(value)
    else:  # string
        return str(value)


def evaluate_expression(expr: str, value: Any) -> bool:
    """
    Evaluates GoRules expression relative to value.

    Supported syntax:
      Comparisons:  > 100  < 50  >= 18  <= 65  == "active"  != 0
      Ranges:       [1..100]  (0..100)  [18..65)  (0..100]
      Lists:        'US', 'CA', 'GB'  /  1, 2, 3
      Combos:       > 0 and < 100  /  < 0 or > 100
      Wildcard:     (empty) or *
    """
    expr = expr.strip()

    # Empty / wildcard → always matches
    if not expr or expr == "*":
        return True

    # Range: [1..100], (0..100), [18..65), (0..100]
    range_m = re.fullmatch(r"([\[\(])\s*(.+?)\s*\.\.\s*(.+?)\s*([\]\)])", expr)
    if range_m:
        lb, low_s, high_s, rb = range_m.groups()
        try:
            low = _parse_literal(low_s)
            high = _parse_literal(high_s)
            left_ok = value >= low if lb == "[" else value > low
            right_ok = value <= high if rb == "]" else value < high
            return bool(left_ok and right_ok)
        except TypeError:
            return False

    # Combo AND: "> 0 and < 100"
    if re.search(r"\band\b", expr, re.IGNORECASE):
        parts = re.split(r"\band\b", expr, flags=re.IGNORECASE)
        return all(_eval_single_op(p.strip(), value) for p in parts)

    # Combo OR: "< 0 or > 100"
    if re.search(r"\bor\b", expr, re.IGNORECASE):
        parts = re.split(r"\bor\b", expr, flags=re.IGNORECASE)
        return any(_eval_single_op(p.strip(), value) for p in parts)

    # Simple comparison with operator
    if re.match(r"^(>=|<=|!=|==|>|<)", expr):
        return _eval_single_op(expr, value)

    # List: 'US', 'CA' or 1, 2, 3
    if "," in expr:
        items = [_parse_literal(item.strip()) for item in expr.split(",")]
        return value in items

    # Bare literal → check for equality
    try:
        return bool(value == _parse_literal(expr))
    except Exception:
        return False


def _coerce_result(raw: str, col_type: str) -> Any:
    """Parses result cell and coerces to column type."""
    raw = raw.strip()
    if col_type == "number":
        try:
            f = float(raw)
            return int(f) if f == int(f) else f
        except ValueError:
            return raw
    elif col_type == "boolean":
        return raw.lower() in ("true", "1", "yes")
    else:  # string
        if len(raw) >= 2 and raw[0] in ('"', "'") and raw[-1] == raw[0]:
            return raw[1:-1]
        return raw


class RuleEngine:
    def __init__(self, schema: TableSchema):
        self.schema = schema
        self.rules = sorted(schema.rules, key=lambda r: r.priority)

    def evaluate(self, ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        for rule in self.rules:
            if self._matches(rule, ctx):
                result: Dict[str, Any] = {}
                for i, col in enumerate(self.schema.outputs):
                    raw = rule.results[i] if i < len(rule.results) else ""
                    result[col.name] = _coerce_result(raw, col.type)
                return {
                    "matched": True,
                    "rule_id": rule.id,
                    "priority": rule.priority,
                    "result": result,
                    "outputs_schema": [c.model_dump() for c in self.schema.outputs],
                }
        return None

    def _matches(self, rule: RuleRow, ctx: Dict[str, Any]) -> bool:
        for i, col in enumerate(self.schema.inputs):
            expr = rule.conditions[i] if i < len(rule.conditions) else ""
            raw_val = ctx.get(col.name)
            value = _coerce_value(raw_val, col.type)
            if not evaluate_expression(expr, value):
                return False
        return True
