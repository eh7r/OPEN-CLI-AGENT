from dataclasses import dataclass
from typing import Callable

from pydantic import BaseModel, Field, ValidationError
from rich.console import Console

from agent import permissions, shell

console = Console()


@dataclass
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    func: Callable[[BaseModel], str]


_REGISTRY: dict[str, Tool] = {}


def register(name: str, description: str, args_model: type[BaseModel]):
    """Decorator: add a function to the tool registry."""

    def decorator(func):
        _REGISTRY[name] = Tool(name, description, args_model, func)
        return func

    return decorator


def schemas() -> list[dict]:
    """Tool definitions in the format the model expects."""
    result = []
    for tool in _REGISTRY.values():
        params = tool.args_model.model_json_schema()
        params.pop("title", None)
        for prop in params.get("properties", {}).values():
            prop.pop("title", None)
        result.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": params,
                },
            }
        )
    return result


def execute(name: str, args: dict) -> str:
    """Validate the arguments, run the tool, always return text (never raise)."""
    tool = _REGISTRY.get(name)
    if tool is None:
        return f"Error: unknown tool '{name}'. Available: {', '.join(_REGISTRY)}"

    try:
        parsed = tool.args_model(**args)
    except ValidationError as e:
        problems = "; ".join(
            f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()
        )
        return f"Error: invalid arguments for '{name}': {problems}. Fix them and try again."

    try:
        return tool.func(parsed)
    except Exception as e:
        return f"Error: tool '{name}' failed: {e}"


# ---------------- Tools ----------------


class TerminalArgs(BaseModel):
    command: str = Field(description="The shell command to run")


@register("terminal", "Run a shell command and return its output", TerminalArgs)
def terminal(args: TerminalArgs) -> str:
    allowed, message = permissions.authorize(args.command)
    if not allowed:
        return message
    return shell.run_command(args.command)
