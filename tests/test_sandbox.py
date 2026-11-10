"""Tests for agent/sandbox.py.
Part 1 checks the argv that build_argv produces (bwrap faked as present).
Part 2 (test_real_*) runs the real bwrap in a temp project; skipped if bwrap cannot run."""
import os
import shutil
import subprocess

import pytest

from agent import sandbox


# ---------- helpers ----------

def has(argv, *seq):
    n = len(seq)
    return any(tuple(argv[i:i + n]) == seq for i in range(len(argv) - n + 1))


def index_of(argv, *seq):
    n = len(seq)
    return next(i for i in range(len(argv) - n + 1) if tuple(argv[i:i + n]) == seq)


def setenv_pairs(argv):
    head = argv[: argv.index("--")]
    return {head[i + 1]: head[i + 2] for i, a in enumerate(head) if a == "--setenv"}


# ---------- fixtures ----------

@pytest.fixture
def project(monkeypatch, tmp_path):
    """A temp project folder as WORKDIR, a fake HOME elsewhere, sandbox on, network closed."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.setattr(sandbox, "WORKDIR", str(proj))
    monkeypatch.setattr(sandbox, "SANDBOX", True)
    monkeypatch.setattr(sandbox, "SANDBOX_NET", False)
    return proj


@pytest.fixture
def unit(monkeypatch, project):
    """Same as project, with bwrap pretended to be installed."""
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: "/usr/bin/bwrap")
    return project


def sh(command):
    return subprocess.run(
        sandbox.build_argv(command),
        cwd=sandbox.WORKDIR,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=20,
    )


@pytest.fixture
def real(project):
    if shutil.which("bwrap") is None:
        pytest.skip("bwrap is not installed")
    probe = sh("true")
    if probe.returncode != 0:
        pytest.skip(f"bwrap cannot run here: {probe.stderr.strip()}")
    return project


# ---------- sandbox off / unavailable ----------

def test_sandbox_off_returns_plain_shell(monkeypatch, project):
    monkeypatch.setattr(sandbox, "SANDBOX", False)
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: None)  # bwrap not needed
    assert sandbox.build_argv("echo hi") == ["/bin/sh", "-c", "echo hi"]


def test_missing_bwrap_raises_with_hint(monkeypatch, project):
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: None)
    with pytest.raises(sandbox.SandboxUnavailable) as exc:
        sandbox.build_argv("ls")
    msg = str(exc.value)
    assert "not installed" in msg
    assert "command was not run" in msg
    assert "pacman -S bubblewrap" in msg


def test_unavailable_is_an_exception():
    assert issubclass(sandbox.SandboxUnavailable, Exception)


# ---------- work dir checks ----------

def test_root_workdir_refused(monkeypatch, unit):
    monkeypatch.setattr(sandbox, "WORKDIR", "/")
    with pytest.raises(sandbox.SandboxUnavailable) as exc:
        sandbox.build_argv("ls")
    assert "AGENT_WORKDIR" in str(exc.value)


def test_home_workdir_refused(monkeypatch, tmp_path, unit):
    monkeypatch.setattr(sandbox, "WORKDIR", str(tmp_path / "home"))
    with pytest.raises(sandbox.SandboxUnavailable) as exc:
        sandbox.build_argv("ls")
    assert "home folder" in str(exc.value)


def test_folder_inside_home_allowed(monkeypatch, tmp_path, unit):
    sub = tmp_path / "home" / "proj"
    sub.mkdir()
    monkeypatch.setattr(sandbox, "WORKDIR", str(sub))
    argv = sandbox.build_argv("ls")
    assert has(argv, "--bind", str(sub), str(sub))


def test_symlinked_workdir_is_resolved(monkeypatch, tmp_path, unit):
    link = tmp_path / "link"
    link.symlink_to(unit)
    monkeypatch.setattr(sandbox, "WORKDIR", str(link))
    argv = sandbox.build_argv("ls")
    real_path = str(unit.resolve())
    assert has(argv, "--bind", real_path, real_path)
    assert has(argv, "--chdir", real_path)


# ---------- argv structure ----------

def test_isolation_flags(unit):
    argv = sandbox.build_argv("ls")
    assert argv[0] == "bwrap"
    for flag in ("--unshare-all", "--die-with-parent", "--new-session", "--clearenv"):
        assert flag in argv


def test_command_is_last_and_untouched(unit):
    cmd = 'echo "a b"; rm -rf x && echo $HOME'
    argv = sandbox.build_argv(cmd)
    assert argv[-4:] == ["--", "/usr/bin/sh", "-c", cmd]


def test_system_dirs_read_only(unit):
    argv = sandbox.build_argv("ls")
    assert has(argv, "--ro-bind", "/usr", "/usr")
    assert has(argv, "--ro-bind", "/etc", "/etc")


def test_proc_dev_tmp(unit):
    argv = sandbox.build_argv("ls")
    assert has(argv, "--proc", "/proc")
    assert has(argv, "--dev", "/dev")
    assert has(argv, "--tmpfs", "/tmp")


def test_usr_symlinks(unit):
    argv = sandbox.build_argv("ls")
    assert has(argv, "--symlink", "usr/bin", "/bin")
    assert has(argv, "--symlink", "usr/bin", "/sbin")
    assert has(argv, "--symlink", "usr/lib", "/lib")
    assert has(argv, "--symlink", "usr/lib64", "/lib64") == os.path.exists("/usr/lib64")


def test_workdir_is_writable_and_current(unit):
    argv = sandbox.build_argv("ls")
    wd = str(unit.resolve())
    assert has(argv, "--bind", wd, wd)
    assert not has(argv, "--ro-bind", wd, wd)
    assert has(argv, "--chdir", wd)


def test_home_is_not_mounted(unit):
    argv = sandbox.build_argv("ls")
    assert "/home" not in argv
    assert os.path.expanduser("~") not in argv


# ---------- network ----------

def test_network_closed_by_default(unit):
    assert "--share-net" not in sandbox.build_argv("ls")


def test_network_opens_when_enabled(monkeypatch, unit):
    monkeypatch.setattr(sandbox, "SANDBOX_NET", True)
    argv = sandbox.build_argv("ls")
    assert "--share-net" in argv
    assert argv.index("--share-net") > argv.index("--unshare-all")


# ---------- .git and .env ----------

def test_git_dir_read_only(unit):
    (unit / ".git").mkdir()
    argv = sandbox.build_argv("ls")
    wd = str(unit.resolve())
    git = os.path.join(wd, ".git")
    assert has(argv, "--ro-bind", git, git)
    # must come after the writable workdir bind, or it would be overridden
    assert index_of(argv, "--ro-bind", git, git) > index_of(argv, "--bind", wd, wd)


def test_no_git_dir_no_extra_mount(unit):
    argv = sandbox.build_argv("ls")
    assert not any(a.endswith("/.git") for a in argv)


def test_git_file_read_only(unit):
    """A gitfile (worktree/submodule pointer) must not be repointable from the sandbox (S1)."""
    (unit / ".git").write_text("gitdir: /somewhere/else\n")
    argv = sandbox.build_argv("ls")
    wd = str(unit.resolve())
    git = os.path.join(wd, ".git")
    assert has(argv, "--ro-bind", git, git)
    assert index_of(argv, "--ro-bind", git, git) > index_of(argv, "--bind", wd, wd)


# ---------- build_git_argv (git runs inside the sandbox: S1/S6) ----------

GIT_TAIL = ["git", "--no-pager", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false"]


@pytest.fixture
def git_unit(monkeypatch, unit):
    (unit / ".git").mkdir()
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    return unit


def test_git_argv_runs_git_without_shell_with_hardening(git_unit):
    argv = sandbox.build_git_argv(str(git_unit), ["status", "--short"])
    assert argv[0] == "bwrap"
    assert argv[argv.index("--") + 1:] == GIT_TAIL + ["status", "--short"]


def test_git_argv_read_only_git_dir_by_default(git_unit):
    argv = sandbox.build_git_argv(str(git_unit), ["status"])
    wd = str(git_unit.resolve())
    git = os.path.join(wd, ".git")
    assert has(argv, "--bind", wd, wd)
    assert index_of(argv, "--ro-bind", git, git) > index_of(argv, "--bind", wd, wd)


def test_git_argv_write_leaves_git_dir_writable(git_unit):
    argv = sandbox.build_git_argv(str(git_unit), ["commit"], write=True)
    git = os.path.join(str(git_unit.resolve()), ".git")
    assert not has(argv, "--ro-bind", git, git)


def test_git_argv_env_cleared_and_pinned(git_unit):
    argv = sandbox.build_git_argv(str(git_unit), ["status"])
    wd = str(git_unit.resolve())
    env = setenv_pairs(argv)
    assert argv.index("--clearenv") < argv.index("--setenv")
    assert env["HOME"] == "/tmp"
    assert env["GIT_DIR"] == os.path.join(wd, ".git")
    assert env["GIT_WORK_TREE"] == wd
    assert env["GIT_CEILING_DIRECTORIES"] == wd
    assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_git_argv_network_always_closed(monkeypatch, git_unit):
    monkeypatch.setattr(sandbox, "SANDBOX_NET", True)
    argv = sandbox.build_git_argv(str(git_unit), ["status"], write=True)
    assert "--unshare-all" in argv
    assert "--share-net" not in argv


def test_git_argv_hides_env_file(git_unit):
    (git_unit / ".env").write_text("SECRET=1")
    argv = sandbox.build_git_argv(str(git_unit), ["status"])
    assert has(argv, "--ro-bind", "/dev/null", os.path.join(str(git_unit.resolve()), ".env"))


def test_git_argv_mounts_global_config_read_only(monkeypatch, git_unit, tmp_path):
    cfg = tmp_path / "gitconfig"
    cfg.write_text("[user]\n\tname = Me\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(cfg))
    argv = sandbox.build_git_argv(str(git_unit), ["commit"], write=True)
    assert has(argv, "--ro-bind", str(cfg), "/tmp/.gitconfig")


def test_git_argv_no_global_config(git_unit):
    argv = sandbox.build_git_argv(str(git_unit), ["status"])
    assert "/tmp/.gitconfig" not in argv


def test_git_argv_sandbox_off_is_plain_git(monkeypatch, git_unit):
    monkeypatch.setattr(sandbox, "SANDBOX", False)
    assert sandbox.build_git_argv(str(git_unit), ["status"]) == GIT_TAIL + ["status"]


def test_git_argv_missing_bwrap_raises(monkeypatch, git_unit):
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: None)
    with pytest.raises(sandbox.SandboxUnavailable):
        sandbox.build_git_argv(str(git_unit), ["status"])


def test_env_file_hidden(unit):
    (unit / ".env").write_text("SECRET=1")
    argv = sandbox.build_argv("ls")
    wd = str(unit.resolve())
    env_file = os.path.join(wd, ".env")
    assert has(argv, "--ro-bind", "/dev/null", env_file)
    assert index_of(argv, "--ro-bind", "/dev/null", env_file) > index_of(argv, "--bind", wd, wd)


def test_no_env_file_no_extra_mount(unit):
    argv = sandbox.build_argv("ls")
    assert not any(a.endswith("/.env") for a in argv)


def test_env_directory_is_not_treated_as_secret_file(unit):
    (unit / ".env").mkdir()
    argv = sandbox.build_argv("ls")
    assert not has(argv, "--ro-bind", "/dev/null", os.path.join(str(unit.resolve()), ".env"))


# ---------- environment ----------

def test_environment_cleared_then_minimal(unit):
    argv = sandbox.build_argv("ls")
    assert argv.index("--clearenv") < argv.index("--setenv")
    assert setenv_pairs(argv) == {
        "PATH": "/usr/bin",
        "HOME": "/tmp",
        "LANG": "C.UTF-8",
        "TERM": "dumb",
    }


# ---------- real bwrap ----------

def test_real_exit_code_passes_through(real):
    assert sh("exit 7").returncode == 7


def test_real_workdir_is_writable(real):
    r = sh("echo hi > made.txt")
    assert r.returncode == 0
    assert (real / "made.txt").read_text().strip() == "hi"


def test_real_starts_in_workdir(real):
    r = sh("pwd")
    assert r.stdout.strip() == str(real.resolve())


def test_real_usr_is_read_only(real):
    assert sh("touch /usr/agent-test-file").returncode != 0


def test_real_git_is_read_only(real):
    git = real / ".git"
    git.mkdir()
    (git / "HEAD").write_text("ref: main\n")
    assert sh("echo x > .git/HEAD").returncode != 0
    assert sh("touch .git/newfile").returncode != 0
    assert (git / "HEAD").read_text() == "ref: main\n"
    assert not (git / "newfile").exists()


def test_real_git_file_cannot_be_rewritten(real):
    (real / ".git").write_text("gitdir: /somewhere/else\n")
    assert sh("echo 'gitdir: ./evil' > .git").returncode != 0
    assert sh("rm -f .git").returncode != 0
    assert (real / ".git").read_text() == "gitdir: /somewhere/else\n"


def test_real_env_file_is_hidden(real):
    (real / ".env").write_text("SECRET=1")
    r = sh("cat .env")
    assert "SECRET" not in r.stdout
    assert (real / ".env").read_text() == "SECRET=1"


def test_real_home_is_hidden(real):
    assert sh("test ! -e /home").returncode == 0


def test_real_other_folders_invisible(real, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    (other / "secret.txt").write_text("top secret")
    r = sh(f"cat {other}/secret.txt")
    assert r.returncode != 0
    assert "top secret" not in r.stdout


def test_real_network_blocked(real):
    r = sh("cat /proc/net/dev")
    assert r.returncode == 0
    names = [ln.split(":")[0].strip() for ln in r.stdout.splitlines()[2:] if ":" in ln]
    assert names == ["lo"]


def test_real_environment_not_leaked(monkeypatch, real):
    monkeypatch.setenv("AGENT_TEST_SECRET", "leaked")
    r = sh('echo "[$AGENT_TEST_SECRET]"')
    assert r.stdout.strip() == "[]"


def test_real_home_variable_is_tmp(real):
    assert sh("echo $HOME").stdout.strip() == "/tmp"
