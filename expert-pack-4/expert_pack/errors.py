"""Exception types shared by every expert-pack seam.

Adapters should raise the narrowest type below so the CLI can tell a wiring
mistake (``AssemblyError``) from a runtime failure (``ToolError``).  The agent
loop itself treats any adapter exception as an observation, never as a crash.
"""

from __future__ import annotations


class ExpertPackError(Exception):
    """Base class for every error raised deliberately by expert-pack."""


class ContractError(ExpertPackError):
    """An object bound to a slot does not satisfy the slot's contract."""


class SlotError(ExpertPackError):
    """A slot is unknown, duplicated, or bound in a way the catalog forbids."""


class VacancyError(ExpertPackError):
    """A required slot is vacant (or only holds a stub) in strict mode."""


class AssemblyError(ExpertPackError):
    """The assembly file cannot be read, parsed, or resolved."""


class ModelError(ExpertPackError):
    """A model backend is unbound or failed to answer."""


class ToolError(ExpertPackError):
    """A tool provider failed in a way it could not turn into a ToolResult."""


class McpError(ToolError):
    """An MCP transport, protocol, or server error."""


class MemoryError_(ExpertPackError):
    """The experience store cannot be read or written."""


# A non-underscored alias keeps ``from expert_pack.errors import MemoryError``
# from shadowing the builtin by accident in user code.
MemoryStoreError = MemoryError_
