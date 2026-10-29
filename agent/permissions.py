import re
import shlex

from rich.console import Console
from rich.markup import escape

from agent.approval import confirm

console = Console()

# Read-only commands that may run without asking.
SAFE_COMMANDS = {
    "ls", "pwd", "cat", "head", "tail", "wc",
    "whoami", "date", "uname", "df", "du", "echo",
}

# Anything touching these is never auto-approved.
SENSITIVE = re.compile(
    r"(\.ssh|\.gnupg|\.aws|\.kube|\.env|id_rsa|id_ed25519|/etc/shadow|/etc/sudoers)"
)

OPERATORS = re.compile(r"[;&|<>`\n]|\$\(")
SEGMENT_SPLIT = re.compile(r"[;&|\n]+")

DANGEROUS_TARGETS = {"/", "/*", "~", "~/", "$HOME", "*", ".", ".."}
DENY_REGEX = [
    (r":\(\)\s*\{", "fork bomb"),
    (r"(curl|wget)[^|]*\|\s*(sudo\s+)?(sh|bash|zsh|fish)\b", "piping a download into a shell"),
    (r">\s*/dev/(sd|nvme|vd|mmcblk)", "writing directly to a disk device"),
]


def _deny_reason(command: str) -> str | None:
    """Return why a command is always blocked, or None."""
    for pattern, reason in DENY_REGEX:
        if re.search(pattern, command):
            return reason

    for segment in SEGMENT_SPLIT.split(command):
        try:
            tokens = shlex.split(segment)
        except ValueError:
            continue
        while tokens and tokens[0] in ("sudo", "doas"):
            tokens = tokens[1:]
        if not tokens:
            continue
        name, args = tokens[0], tokens[1:]

        if name == "rm":
            if "--no-preserve-root" in args:
                return "rm with --no-preserve-root"
            recursive = "--recursive" in args or any(
                a.startswith("-") and not a.startswith("--") and ("r" in a or "R" in a)
                for a in args
            )
            targets = [a for a in args if not a.startswith("-")]
            if recursive and any(t in DANGEROUS_TARGETS for t in targets):
                return "recursive delete of root, home or everything"
        if name.startswith("mkfs"):
            return "formatting a filesystem"
        if name == "dd" and any(a.startswith("of=/dev/") for a in args):
            return "writing directly to a disk device"
        if name in ("chmod", "chown") and "-R" in args and "/" in args:
            return "recursive permission change on root"
    return None


def _is_safe(command: str) -> bool:
    if OPERATORS.search(command) or SENSITIVE.search(command):
        return False
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    return bool(tokens) and tokens[0] in SAFE_COMMANDS


def authorize(command: str) -> tuple[bool, str]:
    """Decide if a command may run. Returns (allowed, message for the model)."""
    command = command.strip()
    if not command:
        return False, "Error: empty command."

    reason = _deny_reason(command)
    if reason:
        console.print(f"[red][BLOCKED][/red] {escape(command)}  ({reason})")
        return False, f"Error: blocked by policy ({reason}). Do not retry this command."

    if _is_safe(command):
        return True, ""

    return confirm(f"the agent wants to run: {command}")
