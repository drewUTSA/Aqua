"""Private-file guard tests use only temporary fixtures and fake credentials."""

import importlib.util
import os
from pathlib import Path

import pytest


@pytest.fixture
def private_ops(tmp_path, monkeypatch):
    location = Path(__file__).resolve().parents[2] / "ops/appdb/private.py"
    spec = importlib.util.spec_from_file_location("aqua_private_fixture", location)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "directory", lambda: tmp_path)
    return module


def test_private_preparation_is_repeatable_without_secret_output(private_ops, capsys):
    private_ops.prepare()
    before = private_ops.read("credentials.json")
    private_ops.prepare()
    assert before == private_ops.read("credentials.json")
    assert capsys.readouterr().out == ""
    assert b"APP_STORAGE_ENABLED=false" in private_ops.read("runtime.env")


def test_private_file_permissions_links_and_replacement_fail_closed(
    private_ops, tmp_path
):
    private_ops.write_once("test-secret", b"synthetic")
    with pytest.raises(RuntimeError):
        private_ops.write_once("test-secret", b"changed")
    os.chmod(tmp_path / "test-secret", 0o644)
    with pytest.raises(RuntimeError):
        private_ops.read("test-secret")
    (tmp_path / "linked").symlink_to(tmp_path / "test-secret")
    with pytest.raises(RuntimeError):
        private_ops.read("linked")
    os.chmod(tmp_path / "test-secret", 0o600)
    os.link(tmp_path / "test-secret", tmp_path / "second-link")
    with pytest.raises(RuntimeError):
        private_ops.read("test-secret")


def test_private_corrupt_credentials_are_refused(private_ops):
    private_ops.write_once("credentials.json", b'{"runtime":"too-short"}')
    with pytest.raises(RuntimeError, match="unexpected credential"):
        private_ops.credentials()
