---
name: verify-arithmetic
description: Recompute an arithmetic claim and report whether it is consistent.
when_to_use: A proposed numeric answer must be checked against its expression.
---

# Verify arithmetic

Executable skill. Arguments:

    {"expression": "42*3", "answer": "126"}

It re-evaluates the expression with the bundled safe evaluator (no `eval`) and
returns a one-line verdict. The result is advisory: the agent still decides
whether to submit the answer.
