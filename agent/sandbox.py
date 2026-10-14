"""Run shell commands inside bubblewrap (bwrap)."""
import os
import shutil
from pathlib import Path

from agent.config import SANDBOX, SANDBOX_NET, WORKDIR

INSTALL_HINT = (
    "Install it with: sudo pacman -S bubblewrap (Arch), "
    "sudo apt install bubblewrap (Debian/Ubuntu) or sudo dnf install bubblewrap (Fedora)."
)


class SandboxUnavailable(Exception):
    pass


def build_argv(command: str) -> list[str]:
    """Return the argv that runs `command` (inside bubblewrap unless disabled)."""
    if not SANDBOX:
        return ["/bin/sh", "-c", command]

    if shutil.which("bwrap") is None:
        raise SandboxUnavailable(
            "bubblewrap (bwrap) is not installed, so the command was not run. " + INSTALL_HINT
        )

    workdir = Path(WORKDIR).resolve()
    if workdir in (Path("/"), Path.home().resolve()):
        raise SandboxUnavailable(
            "the working directory is your home folder or /, which is too broad for the sandbox. "
            "Run the agent from a project folder or set AGENT_WORKDIR."
        )
    wd = str(workdir)

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
    if os.path.isdir(os.path.join(wd, ".git")):
        argv += ["--ro-bind", os.path.join(wd, ".git"), os.path.join(wd, ".git")]
    if os.path.isfile(os.path.join(wd, ".env")):
        argv += ["--ro-bind", "/dev/null", os.path.join(wd, ".env")]
    argv += [
        "--clearenv",
        "--setenv", "PATH", "/usr/bin",
        "--setenv", "HOME", "/tmp",
        "--setenv", "LANG", "C.UTF-8",
        "--setenv", "TERM", "dumb",
    ]
    if SANDBOX_NET:
        argv.append("--share-net")
    return argv + ["--", "/usr/bin/sh", "-c", command]
