"""Safe arithmetic evaluation shared by the demo MCP server and the skill."""

from __future__ import annotations

import ast


class _Calculator(ast.NodeVisitor):
    def visit_Expression(self, node: ast.Expression) -> float:
        return self.visit(node.body)

    def visit_Constant(self, node: ast.Constant) -> float:
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        raise ValueError("only numeric constants are allowed")

    def visit_UnaryOp(self, node: ast.UnaryOp) -> float:
        value = self.visit(node.operand)
        if isinstance(node.op, ast.USub):
            return -value
        if isinstance(node.op, ast.UAdd):
            return value
        raise ValueError("unsupported unary operator")

    def visit_BinOp(self, node: ast.BinOp) -> float:
        left = self.visit(node.left)
        right = self.visit(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if right == 0:
                raise ValueError("division by zero")
            return left / right
        if isinstance(node.op, ast.Pow):
            if abs(right) > 10:
                raise ValueError("exponent too large")
            return left**right
        raise ValueError("unsupported operator")

    def generic_visit(self, node: ast.AST) -> float:  # noqa: N802 - ast API
        raise ValueError(f"unsupported expression element: {type(node).__name__}")


def evaluate(expression: str) -> float:
    value = _Calculator().visit(ast.parse(expression, mode="eval"))
    if abs(value) > 1e12:
        raise ValueError("result out of range")
    return value


def format_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)
