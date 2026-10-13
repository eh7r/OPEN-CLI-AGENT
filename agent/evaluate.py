"""Observe/Evaluate: classify tool results and enforce the retry rules."""
import json
from dataclasses import dataclass, field

from agent import permissions

MAX_SAME_CALL = 2
READ_ONLY_TOOLS = {"read_file", "list_dir", "git_status", "git_diff"}

OK, FAILED, TIMEOUT, DECLINED, BLOCKED = "ok", "failed", "timeout", "declined", "blocked"

TIMEOUT_WARNING = (
    "\nWARNING: this action timed out and may have partly run. Do NOT repeat it. "
    "Check the current state first (for example with list_dir or git_status), "
    "then tell the user what happened."
)


def classify(text: str) -> str:
    if text.startswith("Error: the user declined"):
        return DECLINED
    if text.startswith("Error: blocked by policy"):
        return BLOCKED
    if text.startswith("Error: the command timed out") or "git timed out" in text:
        return TIMEOUT
    if text.startswith("Error") or (text.startswith("exit code:") and not text.startswith("exit code: 0")):
        return FAILED
    return OK


def is_mutating(name: str, args: dict) -> bool:
    """Anything that can change files, git history or the system."""
    if name in READ_ONLY_TOOLS:
        return False
    if name == "terminal":
        return not permissions._is_safe(str(args.get("command", "")))
    return True


@dataclass
class Tracker:
    counts: dict = field(default_factory=dict)
    locked: set = field(default_factory=set)
    declined: bool = False

    @staticmethod
    def _key(name: str, args: dict) -> str:
        return name + ":" + json.dumps(args, sort_keys=True, default=str)

    def check(self, name: str, args: dict) -> str | None:
        """Return a refusal message if this exact call must not run, else None."""
        key = self._key(name, args)
        if key in self.locked:
            return "Error: this exact call must not be repeated. Do something different or tell the user."
        if self.counts.get(key, 0) >= MAX_SAME_CALL:
            return (
                f"Error: this exact call already ran {MAX_SAME_CALL} times. "
                "Do not repeat it; try a different approach or tell the user."
            )
        return None

    def record(self, name: str, args: dict, text: str) -> tuple[str, str]:
        """Record the outcome. Returns (text for the model, status)."""
        key = self._key(name, args)
        self.counts[key] = self.counts.get(key, 0) + 1
        status = classify(text)
        mutating = is_mutating(name, args)

        if status == DECLINED:
            self.declined = True
            self.locked.add(key)
        elif status == BLOCKED:
            self.locked.add(key)
        elif status in (FAILED, TIMEOUT) and mutating:
            self.locked.add(key)

        if status == TIMEOUT and mutating:
            text += TIMEOUT_WARNING
        return text, status
