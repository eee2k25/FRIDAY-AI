"""Math tools — safe calculator, unit conversion (pint), equation solving (sympy)."""
from __future__ import annotations

import ast
import math
import operator
import re

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

_MATH_FUNCS = {
    "sin", "cos", "tan", "asin", "acos", "atan", "atan2",
    "sqrt", "cbrt", "exp", "log", "log2", "log10", "log1p",
    "floor", "ceil", "fabs", "sinh", "cosh", "tanh",
}


def _safe_eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval_node(node.left), _safe_eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval_node(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _MATH_FUNCS:
        fn = getattr(math, node.func.id)
        args = [_safe_eval_node(a) for a in node.args]
        return fn(*args)
    if isinstance(node, ast.Name):
        consts = {"pi": math.pi, "e": math.e, "tau": math.tau}
        if node.id in consts:
            return consts[node.id]
    raise ValueError(f"not allowed in expression: {ast.unparse(node)[:60]}")


def _sympy_expr(s: str):
    """Parse a math expression with sympy, supporting implicit multiplication
    (2x → 2*x) while keeping function calls intact (sin(x) stays sin(x))."""
    import sympy
    from sympy.parsing.sympy_parser import (
        convert_xor,
        implicit_multiplication_application,
        parse_expr,
        standard_transformations,
    )

    return parse_expr(
        s,
        transformations=standard_transformations + (implicit_multiplication_application, convert_xor),
    )


def calculate(expression: str) -> str:
    """Evaluate a math expression. AST-safe first; sympy fallback for fancier input."""
    expr = expression.strip().replace("^", "**").replace("×", "*").replace("÷", "/")
    try:
        tree = ast.parse(expr, mode="eval")
        result = _safe_eval_node(tree.body)
        if isinstance(result, float) and result.is_integer():
            result = int(result)
        return f"{expression.strip()} = {result}"
    except Exception as e:  # noqa: BLE001
        if re.fullmatch(r"[0-9a-zA-Z_+\-*/().,\s^]{1,120}", expr):
            try:
                val = _sympy_expr(expr).evalf()
                return f"{expression.strip()} = {val}"
            except Exception as e2:  # noqa: BLE001
                raise RuntimeError(f"could not evaluate {expression!r}: {e} / sympy: {e2}") from e2
        raise RuntimeError(f"could not evaluate {expression!r}: {e}")


def unit_convert(value: float, from_unit: str, to_unit: str) -> str:
    """Convert between units with pint — electrical (V, A, W, ohm), mechanical,
    temperature, data, and everything else in the Pint database."""
    try:
        import pint
    except ImportError as e:
        raise RuntimeError("pint not installed. Run: pip install pint") from e
    ureg = pint.UnitRegistry()
    try:
        q = ureg.Quantity(float(value), from_unit)
        converted = q.to(to_unit)
        return f"{value} {from_unit} = {converted}"
    except Exception as e:  # noqa: BLE001
        return (
            f"Could not convert: {e}. Hint — use names like 'meters', 'kilometers_per_hour', "
            "'volts', 'amps', 'ohms', 'watts', 'celsius', 'gigabytes'."
        )


def solve_equation(equation: str, variable: str = "x") -> str:
    """Solve an algebraic equation with sympy, e.g. '2x + 5 = 9' or 'x**2 - 4 = 0'."""
    try:
        import sympy
    except ImportError as e:
        raise RuntimeError("sympy not installed. Run: pip install sympy") from e
    sym = sympy.Symbol(variable)
    expr = equation.strip().replace("^", "**")
    if "=" not in expr:
        expr = f"{expr} = 0"
    left, right = expr.split("=", 1)
    solutions = sympy.solve(_sympy_expr(left.strip()) - _sympy_expr(right.strip()), sym)
    if not solutions:
        return f"No solution found for {variable} in {equation!r}."
    lines = []
    for s in solutions:
        approx_s = ""
        try:
            approx = complex(s.evalf())
            approx_s = f"{approx.real:.6g}" + (
                f"{approx.imag:+.6g}i" if abs(approx.imag) > 1e-12 else ""
            )
            if not s.is_number:
                approx_s = ""
        except Exception:  # noqa: BLE001
            pass
        lines.append(f"{variable} = {s}" + (f"   (≈ {approx_s})" if approx_s else ""))
    return f"Solving {equation}:\n" + "\n".join(lines)


_DECLARATIONS: list[dict] = [
    {
        "name": "calculate",
        "description": "Safely evaluate a math expression (e.g. '2*(3+4)**2 / 7', 'sqrt(2)+sin(pi/2)').",
        "parameters": {
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
        },
    },
    {
        "name": "unit_convert",
        "description": "Convert a value between units: electrical (volts, amps, watts, ohms), mechanical, temperature, data size, etc.",
        "parameters": {
            "type": "object",
            "properties": {
                "value": {"type": "number"},
                "from_unit": {"type": "string"},
                "to_unit": {"type": "string"},
            },
            "required": ["value", "from_unit", "to_unit"],
        },
    },
    {
        "name": "solve_equation",
        "description": "Solve an algebraic equation for a variable, e.g. '2x + 5 = 9' or 'x^2 - 4 = 0'.",
        "parameters": {
            "type": "object",
            "properties": {
                "equation": {"type": "string"},
                "variable": {"type": "string", "description": "default 'x'"},
            },
            "required": ["equation"],
        },
    },
]


def register_tools(registry) -> None:
    for d in _DECLARATIONS:
        registry.register_tool(d["name"], globals()[d["name"]], d)
