"""Run shell commands (and git) inside bubblewrap (bwrap)."""
import os
import shutil
from pathlib import Path

from agent.config import SANDBOX, SANDBOX_NET, WORKDIR

INSTALL_HINT = (
    "Install it with: sudo pacman -S bubblewrap (Arch), "
    "sudo apt install bubblewrap (Debian/Ubuntu) or sudo dnf install bubblewrap (Fedora)."
)

# Added to every git call: repo hooks and fsmonitor never run, whatever .git/config says.
GIT_HARDENING = ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false"]


class SandboxUnavailable(Exception):
    pass


def _check_workdir(path: str) -> str:
    """Return the resolved work dir, or raise if bwrap is missing or the dir is too broad."""
    if shutil.which("bwrap") is None:
        raise SandboxUnavailable(
            "bubblewrap (bwrap) is not installed, so the command was not run. " + INSTALL_HINT
        )

    workdir = Path(path).resolve()
    if workdir in (Path("/"), Path.home().resolve()):
        raise SandboxUnavailable(
            "the working directory is your home folder or /, which is too broad for the sandbox. "
            "Run the agent from a project folder or set AGENT_WORKDIR."
        )
    return str(workdir)


def _base(wd: str) -> list[str]:
    """Mounts shared by every sandboxed run: system read-only, wd writable, .env hidden."""
    argv = [
        "bwrap",
        "--unshare-all",
        "--die-with-parent",
        "--new-session",
        "--ro-bind", "/usr", "/usr",
        "--symlink", "usr/bin", "/bin",
        "--symlink", "usr/bin", "/sbin",
        "--symlink", "usr/lib", "/lib",
    ]
    if os.path.exists("/usr/lib64"):
        argv += ["--symlink", "usr/lib64", "/lib64"]
    argv += [
        "--ro-bind", "/etc", "/etc",
        "--proc", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
        "--bind", wd, wd,
        "--chdir", wd,
    ]
    if os.path.isfile(os.path.join(wd, ".env")):
        argv += ["--ro-bind", "/dev/null", os.path.join(wd, ".env")]
    return argv


def _env(extra: dict[str, str] | None = None) -> list[str]:
    out = [
        "--clearenv",
        "--setenv", "PATH", "/usr/bin",
        "--setenv", "HOME", "/tmp",
        "--setenv", "LANG", "C.UTF-8",
        "--setenv", "TERM", "dumb",
    ]
    for key, value in (extra or {}).items():
        out += ["--setenv", key, value]
    return out


def build_argv(command: str) -> list[str]:
    """Return the argv that runs `command` (inside bubblewrap unless disabled)."""
    if not SANDBOX:
        return ["/bin/sh", "-c", command]

    wd = _check_workdir(WORKDIR)
    argv = _base(wd)
    git = os.path.join(wd, ".git")
    # read-only .git dir, and a gitfile (worktree/submodule pointer) cannot be repointed
    if os.path.isdir(git) or os.path.isfile(git):
        argv += ["--ro-bind", git, git]
    argv += _env()
    if SANDBOX_NET:
        argv.append("--share-net")
    return argv + ["--", "/usr/bin/sh", "-c", command]


def git_env(wd: str) -> dict[str, str]:
    """Pin git to wd/.git: no repo discovery, no prompts, no optional index writes."""
    return {
        "GIT_DIR": os.path.join(wd, ".git"),
        "GIT_WORK_TREE": wd,
        "GIT_CEILING_DIRECTORIES": wd,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
    }


def _global_gitconfig() -> str | None:
    """The user's global git config file (for user.name/email), if any."""
    if "GIT_CONFIG_GLOBAL" in os.environ:
        candidates = [os.environ["GIT_CONFIG_GLOBAL"]]
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        candidates = [os.path.expanduser("~/.gitconfig"), os.path.join(xdg, "git", "config")]
    return next((c for c in candidates if os.path.isfile(c)), None)


def build_git_argv(workdir: str, git_args: list[str], write: bool = False) -> list[str]:
    """Return the argv that runs git (no shell) on workdir's repo.
    In bwrap: network off, .git read-only unless `write`, repo hooks and fsmonitor disabled.
    With the sandbox off: plain git with the same hardening flags."""
    cmd = ["git", "--no-pager", *GIT_HARDENING, *git_args]
    if not SANDBOX:
        return cmd

    wd = _check_workdir(workdir)
    argv = _base(wd)
    if not write:
        git = os.path.join(wd, ".git")
        argv += ["--ro-bind", git, git]
    config = _global_gitconfig()
    if config:
        argv += ["--ro-bind", config, "/tmp/.gitconfig"]
    return argv + _env(git_env(wd)) + ["--", *cmd]
