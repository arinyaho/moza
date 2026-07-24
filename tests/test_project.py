import json

import pytest

from mien.project import (find_declaration, ensure_gitignored, is_allowed,
                          record_allow, write_declaration)


def _cfg_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MIEN_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))


class TestFindDeclaration:
    def test_reads_the_profile_name(self, tmp_path):
        (tmp_path / ".mien").write_text("work\n")
        profile, path = find_declaration(str(tmp_path))
        assert profile == "work"
        assert path == str((tmp_path / ".mien").resolve())

    def test_walks_up_to_the_nearest(self, tmp_path):
        (tmp_path / ".mien").write_text("work\n")
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        (tmp_path / "a" / ".mien").write_text("nearer\n")  # nearer one wins
        profile, _ = find_declaration(str(deep))
        assert profile == "nearer"

    def test_ignores_comments_and_blank_lines(self, tmp_path):
        (tmp_path / ".mien").write_text("# a comment\n\n  work  \n")
        profile, _ = find_declaration(str(tmp_path))
        assert profile == "work"

    def test_none_when_absent(self, tmp_path):
        assert find_declaration(str(tmp_path)) == (None, None)


class TestAllowState:
    def test_record_and_check_are_keyed_by_path_and_profile(self, tmp_path, monkeypatch):
        _cfg_env(tmp_path, monkeypatch)
        p = "/some/ws/.mien"
        assert not is_allowed(p, "work")
        record_allow(p, "work")
        assert is_allowed(p, "work")
        # A different profile at the same path is NOT approved — re-confirm on change.
        assert not is_allowed(p, "personal")
        # A different path is independent.
        assert not is_allowed("/other/.mien", "work")

    def test_allowed_file_is_0600(self, tmp_path, monkeypatch):
        _cfg_env(tmp_path, monkeypatch)
        record_allow("/x/.mien", "work")
        allowed = tmp_path / "allowed.json"
        assert allowed.exists()
        assert (allowed.stat().st_mode & 0o777) == 0o600
        assert json.loads(allowed.read_text())["/x/.mien"] == "work"


class TestGitignore:
    def test_adds_dot_mien_to_global_ignore_once(self, tmp_path, monkeypatch):
        _cfg_env(tmp_path, monkeypatch)
        assert ensure_gitignored() is True
        ignore = tmp_path / "xdg" / "git" / "ignore"
        assert ".mien" in ignore.read_text().splitlines()
        # Idempotent — does not duplicate.
        assert ensure_gitignored() is False
        assert ignore.read_text().count(".mien") == 1


def test_write_declaration_roundtrips(tmp_path):
    path = write_declaration(str(tmp_path), "work")
    assert (tmp_path / ".mien").read_text().strip() == "work"
    profile, found = find_declaration(str(tmp_path))
    assert (profile, found) == ("work", path)
