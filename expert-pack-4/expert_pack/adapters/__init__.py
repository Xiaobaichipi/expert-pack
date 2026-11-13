"""Concrete adapters for the expert-pack seams.

Each module is a thin translator between an external system and one contract:

* ``model_openai``   -> ModelBackend over any OpenAI-compatible endpoint
* ``model_scripted`` -> deterministic backend for tests
* ``model_stub``     -> the loud vacancy used when nothing is bound
* ``skills``         -> Skill from ``SKILL.md`` directories
* ``mcp_stdio``      -> ToolProvider from an MCP stdio server
"""
