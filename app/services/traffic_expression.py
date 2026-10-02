"""Small, bounded expression interpreter. Never evaluates Python code."""
import ast
import math
import operator

METRICS = {
    "leads", "qualified_leads", "submitted_leads", "registrations", "first_deposits",
    "redepositors", "redeposits", "tagged_leads", "assessed_leads", "coverage",
    "clicks", "spend", "channel_join_requests", "channel_joins", "channel_leaves",
    "funnel_starts",
    "registered_depositors", "deposited_redepositors", "approved_requests", "request_funnel_starts",
}
OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
COMPARISONS = {ast.Gt: operator.gt, ast.GtE: operator.ge, ast.Lt: operator.lt, ast.LtE: operator.le, ast.Eq: operator.eq, ast.NotEq: operator.ne}


def parse_expression(expression: str) -> ast.Expression:
    if len(expression) > 500:
        raise ValueError("Формула длиннее 500 символов")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError("Некорректная формула") from exc
    nodes = list(ast.walk(tree))
    if len(nodes) > 80:
        raise ValueError("Слишком сложная формула")
    for node in nodes:
        if isinstance(node, ast.Name):
            if node.id not in METRICS | {"percent", "min", "max"}:
                raise ValueError(f"Неизвестный показатель: {node.id}")
        elif isinstance(node, ast.Constant):
            if type(node.value) not in (int, float) or not math.isfinite(node.value) or abs(node.value) > 1e9:
                raise ValueError("Недопустимое число в формуле")
        elif isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in {"percent", "min", "max"} or len(node.args) != 2 or node.keywords:
                raise ValueError("Доступны percent(a, b), min(a, b), max(a, b)")
        elif not isinstance(node, (ast.Expression, ast.BinOp, ast.UnaryOp, ast.UAdd, ast.USub, ast.Load, ast.BoolOp, ast.And, ast.Or, ast.Compare, *OPS, *COMPARISONS)):
            raise ValueError("Формула поддерживает только арифметику и показатели")
    return tree


def evaluate_expression(expression: str, metrics: dict) -> float | None:
    def visit(node):
        if isinstance(node, ast.Constant):
            return float(node.value)
        if isinstance(node, ast.Name):
            value = metrics.get(node.id)
            if value is None:
                raise ArithmeticError("Missing metric")
            return float(value)
        if isinstance(node, ast.UnaryOp):
            return (-1 if isinstance(node.op, ast.USub) else 1) * visit(node.operand)
        if isinstance(node, ast.BinOp):
            return OPS[type(node.op)](visit(node.left), visit(node.right))
        if isinstance(node, ast.Call):
            a, b = (visit(arg) for arg in node.args)
            if node.func.id == "percent":
                return 100 * a / b
            return min(a, b) if node.func.id == "min" else max(a, b)
        if isinstance(node, ast.Compare):
            values = [visit(node.left), *(visit(value) for value in node.comparators)]
            return float(all(COMPARISONS[type(op)](values[index], values[index + 1]) for index, op in enumerate(node.ops)))
        if isinstance(node, ast.BoolOp):
            values = [bool(visit(value)) for value in node.values]
            return float(all(values) if isinstance(node.op, ast.And) else any(values))
        raise ValueError("Некорректная формула")
    try:
        result = visit(parse_expression(expression).body)
        return result if math.isfinite(result) else None
    except (ArithmeticError, OverflowError):
        return None
