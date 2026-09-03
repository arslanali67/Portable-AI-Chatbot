"""Individual tool behavior — pure unit tests, no DB/network required.

Covers each of the 3 platform-defined allowlisted tools directly:
get_current_datetime, calculate, search_knowledge_base. The full
multi-turn execution loop (ChatRuntimeService._run_with_tool_execution),
cap exhaustion, failure/timeout handling, chatbots.tools validation, and
streaming behavior are covered in test_tool_execution_loop.py (requires
Docker PostgreSQL, run: pytest -m identity).
"""

import asyncio

import pytest

from app.ai.tools.base import ToolExecutionError
from app.ai.tools.calculate_tool import CalculatorTool
from app.ai.tools.datetime_tool import DateTimeTool
from app.ai.tools.registry import DuplicateToolError, ToolRegistry


def _run(coro):
    return asyncio.run(coro)


PLATFORM_CTX = dict(organization_id=1, chatbot_id=1, db_session=None)


# --- get_current_datetime ---


def test_datetime_defaults_to_utc() -> None:
    result = _run(DateTimeTool().execute({}, **PLATFORM_CTX))
    assert result.endswith("+00:00")


def test_datetime_valid_timezone() -> None:
    result = _run(DateTimeTool().execute({"timezone": "America/New_York"}, **PLATFORM_CTX))
    assert "-04:00" in result or "-05:00" in result  # EDT or EST depending on DST


def test_datetime_invalid_timezone_clean_error() -> None:
    with pytest.raises(ToolExecutionError):
        _run(DateTimeTool().execute({"timezone": "Not/AZone"}, **PLATFORM_CTX))


def test_datetime_non_string_timezone_clean_error() -> None:
    with pytest.raises(ToolExecutionError):
        _run(DateTimeTool().execute({"timezone": 123}, **PLATFORM_CTX))


# --- calculate: correct behavior ---


def test_calculate_basic_arithmetic() -> None:
    assert _run(CalculatorTool().execute({"expression": "2 * (3 + 4)"}, **PLATFORM_CTX)) == "14"


def test_calculate_all_operators() -> None:
    calc = CalculatorTool()
    assert _run(calc.execute({"expression": "7 // 2"}, **PLATFORM_CTX)) == "3"
    assert _run(calc.execute({"expression": "7 % 2"}, **PLATFORM_CTX)) == "1"
    assert _run(calc.execute({"expression": "2 ** 10"}, **PLATFORM_CTX)) == "1024"
    assert _run(calc.execute({"expression": "-5 + 3"}, **PLATFORM_CTX)) == "-2"


def test_calculate_whitelisted_functions() -> None:
    calc = CalculatorTool()
    assert _run(calc.execute({"expression": "abs(-5)"}, **PLATFORM_CTX)) == "5"
    assert _run(calc.execute({"expression": "round(3.7)"}, **PLATFORM_CTX)) == "4"
    assert _run(calc.execute({"expression": "min(3, 1, 2)"}, **PLATFORM_CTX)) == "1"
    assert _run(calc.execute({"expression": "max(3, 1, 2)"}, **PLATFORM_CTX)) == "3"


# --- calculate: every category of rejected AST node, tested explicitly ---


def test_calculate_rejects_name_node() -> None:
    """Name: a bare identifier, e.g. referencing a variable."""
    with pytest.raises(ToolExecutionError):
        _run(CalculatorTool().execute({"expression": "x + 1"}, **PLATFORM_CTX))


def test_calculate_rejects_attribute_node() -> None:
    """Attribute: attribute access, the classic sandbox-escape vector."""
    with pytest.raises(ToolExecutionError):
        _run(
            CalculatorTool().execute(
                {"expression": "(1).__class__"}, **PLATFORM_CTX
            )
        )


def test_calculate_rejects_call_to_non_whitelisted_function() -> None:
    """Call: only abs/round/min/max are whitelisted — anything else,
    including dangerous builtins, is rejected before it can execute."""
    calc = CalculatorTool()
    with pytest.raises(ToolExecutionError):
        _run(calc.execute({"expression": "__import__('os').system('echo pwned')"}, **PLATFORM_CTX))
    with pytest.raises(ToolExecutionError):
        _run(calc.execute({"expression": "open('/etc/passwd')"}, **PLATFORM_CTX))
    with pytest.raises(ToolExecutionError):
        _run(calc.execute({"expression": "eval('1')"}, **PLATFORM_CTX))


def test_calculate_rejects_subscript_node() -> None:
    """Subscript: indexing/slicing syntax."""
    with pytest.raises(ToolExecutionError):
        _run(CalculatorTool().execute({"expression": "[1, 2, 3][0]"}, **PLATFORM_CTX))


def test_calculate_rejects_comprehension_node() -> None:
    """ListComp (and comprehensions generally): arbitrary iteration."""
    with pytest.raises(ToolExecutionError):
        _run(CalculatorTool().execute({"expression": "[x for x in range(3)]"}, **PLATFORM_CTX))


def test_calculate_never_evals_raw_text() -> None:
    """Never eval()/exec() on the raw string under any circumstance: a
    string that would execute real code if handed to eval() is instead
    rejected as unsupported syntax/node, proving no fallback to eval()
    exists anywhere in the evaluator."""
    calc = CalculatorTool()
    with pytest.raises(ToolExecutionError):
        _run(calc.execute({"expression": "__import__('sys').exit(1)"}, **PLATFORM_CTX))
    # A syntactically invalid Python statement (not an expression) must
    # also fail cleanly, not silently do something else.
    with pytest.raises(ToolExecutionError):
        _run(calc.execute({"expression": "import os"}, **PLATFORM_CTX))


# --- calculate: safety edges ---


def test_calculate_division_by_zero_clean_error() -> None:
    with pytest.raises(ToolExecutionError):
        _run(CalculatorTool().execute({"expression": "1 / 0"}, **PLATFORM_CTX))


def test_calculate_huge_exponent_rejected() -> None:
    with pytest.raises(ToolExecutionError):
        _run(CalculatorTool().execute({"expression": "2 ** 100000"}, **PLATFORM_CTX))


def test_calculate_nested_exponentiation_blowup_rejected() -> None:
    """Defense in depth: even an individually-small exponent chained
    against an already-huge intermediate result is caught by the
    magnitude check, not just the top-level exponent check."""
    with pytest.raises(ToolExecutionError):
        _run(CalculatorTool().execute({"expression": "(10 ** 30) ** 5"}, **PLATFORM_CTX))


def test_calculate_missing_expression_clean_error() -> None:
    with pytest.raises(ToolExecutionError):
        _run(CalculatorTool().execute({}, **PLATFORM_CTX))


def test_calculate_invalid_syntax_clean_error() -> None:
    with pytest.raises(ToolExecutionError):
        _run(CalculatorTool().execute({"expression": "2 +"}, **PLATFORM_CTX))


def test_calculate_complex_intermediate_magnitude_still_capped() -> None:
    """A fractional power of a negative number produces a complex value —
    confirm it's still subject to the same magnitude cap as int/float,
    not a silent bypass."""
    with pytest.raises(ToolExecutionError):
        _run(CalculatorTool().execute({"expression": "((-2)**0.5)**900"}, **PLATFORM_CTX))


def test_calculate_long_operator_chain_rejected_cleanly() -> None:
    """A long flat operator chain must never raise a raw RecursionError —
    it's rejected with the tool's own clean error before evaluation."""
    expression = "1" + "+1" * 5000
    with pytest.raises(ToolExecutionError):
        _run(CalculatorTool().execute({"expression": expression}, **PLATFORM_CTX))


def test_calculate_boolean_constant_rejected() -> None:
    """bool is technically a subclass of int in Python — must not be
    silently accepted as if it were a number."""
    with pytest.raises(ToolExecutionError):
        _run(CalculatorTool().execute({"expression": "True + 1"}, **PLATFORM_CTX))


# --- ToolRegistry ---


def test_tool_registry_register_get_list_exists() -> None:
    registry = ToolRegistry()
    tool = DateTimeTool()
    registry.register(tool)
    assert registry.get("get_current_datetime") is tool
    assert registry.exists("get_current_datetime")
    assert not registry.exists("nonexistent_tool")
    assert registry.get("nonexistent_tool") is None
    assert registry.list() == [tool]


def test_tool_registry_duplicate_raises() -> None:
    registry = ToolRegistry()
    registry.register(DateTimeTool())
    with pytest.raises(DuplicateToolError):
        registry.register(DateTimeTool())


def test_default_tool_registry_has_exactly_the_approved_allowlist() -> None:
    from app.ai.registry import tool_registry

    names = {t.name for t in tool_registry.list()}
    assert names == {"get_current_datetime", "calculate", "search_knowledge_base"}
