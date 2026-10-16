"""Isolate the test run from the real machine: temp work dir, notes database and config."""
import atexit
import os
import shutil
import tempfile

_root = tempfile.mkdtemp(prefix="agent-tests-")
atexit.register(shutil.rmtree, _root, ignore_errors=True)

_work = os.path.join(_root, "work")
os.makedirs(_work)

os.environ["AGENT_WORKDIR"] = _work
os.environ["AGENT_MEMORY_DB"] = os.path.join(_root, "data", "memory.db")
os.environ["XDG_CONFIG_HOME"] = os.path.join(_root, "config")

for _name in (
    "AGENT_MODEL", "AGENT_TIER", "AGENT_THINK", "AGENT_SANDBOX", "AGENT_SANDBOX_NET",
    "AGENT_CONTEXT", "AGENT_MAX_REPLY", "AGENT_TIMEOUT", "AGENT_MAX_OUTPUT", "AGENT_MAX_STEPS",
):
    os.environ.pop(_name, None)
