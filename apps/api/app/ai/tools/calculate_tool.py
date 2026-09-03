"""calculate — a restricted-grammar arithmetic expression evaluator.

NEVER calls eval()/exec() on the raw expression string, under any
circumstance. The expression is parsed via ast.parse(expr, mode="eval")
and the resulting AST is walked, evaluating only a small explicit
whitelist of node types: numeric constants, the binary/unary arithmetic
operators, and a tiny whitelist of pure math functions. Any other node
(Name, Attribute, a non-whitelisted Call, Subscript, comprehensions, ...)
is rejected with a clean ToolExecutionError before any evaluation happens
— this is a restricted-grammar arithmetic evaluator, not a sandboxed
general-purpose interpreter.
"""

import ast
import operator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.tools.base import ToolExecutionError

_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_ALLOWED_FUNCTIONS = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
}
# Defense in depth against computational blow-up (e.g. nested exponentiation
# like (10**500)**500): reject a large exponent outright before attempting
# pow(), and reject any intermediate/final numeric result above a sane
# magnitude — both checks run on every operation, not just the top-level one.
_MAX_POWER_EXPONENT = 1000
_MAX_MAGNITUDE = 10**18
# A legitimate arithmetic expression never comes close to this many AST
# nodes; anything beyond it is rejected before evaluation, so a long
# operator chain (e.g. "1+1+1+...") can never recurse deep enough in
# _eval_node to risk a RecursionError.
_MAX_AST_NODES = 200


def _check_magnitude(value: Any) -> Any:
    # complex is included because a fractional power of a negative number
    # (e.g. (-2) ** 0.5) legitimately produces one — abs() on a complex
    # number returns its modulus, so the same comparison applies.
    if isinstance(value, (int, float, complex)) and abs(value) > _MAX_MAGNITUDE:
        raise ToolExecutionError("result too large")
    return value


def _eval_node(node: ast.AST) -> int | float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ToolExecutionError("only numeric constants are allowed")
        return node.value
    if isinstance(node, ast.BinOp):
        op_func = _BINARY_OPERATORS.get(type(node.op))
        if op_func is None:
            raise ToolExecutionError(f"unsupported operator: {type(node.op).__name__}")
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > _MAX_POWER_EXPONENT:
            raise ToolExecutionError("exponent too large")
        try:
            result = op_func(left, right)
        except ZeroDivisionError:
            raise ToolExecutionError("division by zero") from None
        return _check_magnitude(result)
    if isinstance(node, ast.UnaryOp):
        op_func = _UNARY_OPERATORS.get(type(node.op))
        if op_func is None:
            raise ToolExecutionError(f"unsupported operator: {type(node.op).__name__}")
        return _check_magnitude(op_func(_eval_node(node.operand)))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCTIONS:
            raise ToolExecutionError("unsupported function call")
        if node.keywords:
            raise ToolExecutionError("keyword arguments are not supported")
        args = [_eval_node(arg) for arg in node.args]
        try:
            result = _ALLOWED_FUNCTIONS[node.func.id](*args)
        except (TypeError, ValueError) as exc:
            raise ToolExecutionError(f"error calling {node.func.id}: {exc}") from exc
        return _check_magnitude(result)
    raise ToolExecutionError(f"unsupported expression syntax: {type(node).__name__}")


class CalculatorTool:
    name = "calculate"
    description = (
        "Evaluate a basic arithmetic expression (numbers, + - * / // % **, "
        "and abs/round/min/max)."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "An arithmetic expression, e.g. '2 * (3 + 4)'.",
            }
        },
        "required": ["expression"],
    }

    async def execute(
        self,
        arguments: dict[str, Any],
        *,
        organization_id: int,
        chatbot_id: int,
        db_session: AsyncSession,
    ) -> str:
        expression = arguments.get("expression")
        if not isinstance(expression, str) or not expression.strip():
            raise ToolExecutionError("'expression' is required and must be a non-empty string")
        try:
            parsed = ast.parse(expression, mode="eval")
        except SyntaxError as exc:
            raise ToolExecutionError(f"invalid expression syntax: {exc}") from exc
        except RecursionError:
            # A pathologically long operator chain can overflow the
            # parser itself before an AST is even produced.
            raise ToolExecutionError("expression too complex")
        if sum(1 for _ in ast.walk(parsed)) > _MAX_AST_NODES:
            raise ToolExecutionError("expression too complex")
        result = _eval_node(parsed)
        return str(result)
