---
name: grounded-answer
description: Retrieve the needed fact before computing or asserting it, then cite the observation.
when_to_use: The task needs a value that was not supplied directly and must be looked up.
---

# Grounded answer

When a task asks you to compute, compare, or report a value that is not already
in the task text:

1. Identify the missing operand and retrieve it with a lookup action.
2. Quote the retrieved value in your reasoning before using it.
3. Only then compute, and put the raw computed value in the final answer.
4. If the lookup fails, change the item or report that the fact is unavailable;
   do not invent a number.

This skill contains no executable code. Selecting it loads these instructions
into the agent's context for the rest of the episode.
