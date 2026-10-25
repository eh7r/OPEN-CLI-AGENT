import pytest
from agent import file_tools


def test_tilde_expanded_and_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(file_tools, "WORKDIR", str(tmp_path))
    with pytest.raises(ValueError):
        file_tools._resolve("~/outside.txt")
    assert not (tmp_path / "~").exists()


def test_normal_path_still_works(tmp_path, monkeypatch):
    monkeypatch.setattr(file_tools, "WORKDIR", str(tmp_path))
    assert file_tools._resolve("a.txt") == tmp_path.resolve() / "a.txt"
