"""Tool registry — tool name string -> Tool instance."""


class DuplicateToolError(Exception):
    pass


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, object] = {}

    def register(self, tool: object) -> None:
        name = tool.name
        if name in self._tools:
            raise DuplicateToolError(f"tool already registered: {name}")
        self._tools[name] = tool

    def get(self, name: str) -> object | None:
        return self._tools.get(name)

    def list(self) -> list[object]:
        return list(self._tools.values())

    def exists(self, name: str) -> bool:
        return name in self._tools
