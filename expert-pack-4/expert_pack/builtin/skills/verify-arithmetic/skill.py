"""Executable part of the ``verify-arithmetic`` skill."""

from __future__ import annotations

from expert_pack.builtin.safe_math import evaluate, format_number

SPEC = {"description": "Recompute an arithmetic claim and report consistency."}


def run(context, arguments):
    expression = str(arguments.get("expression", "")).strip()
    claimed = str(arguments.get("answer", "")).strip()
    if not expression:
        return {"ok": False, "error": "missing 'expression' argument"}
    try:
        value = evaluate(expression)
    except (SyntaxError, ValueError, TypeError) as exc:
        return {"ok": False, "error": f"cannot evaluate {expression!r}: {exc}"}
    actual = format_number(value)
    consistent = (claimed == "") or claimed == actual
    verdict = "consistent" if consistent else "inconsistent"
    return {
        "ok": True,
        "content": f"{expression} = {actual}; claimed={claimed or '(none)'}; {verdict}",
        "data": {"expression": expression, "actual": actual, "consistent": consistent},
    }
