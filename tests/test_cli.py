"""Unit tests for CLI commands (no browser needed)."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

import xhs_cli.cli as cli_module
from xhs_cli import __version__
from xhs_cli.cli import cli


@pytest.fixture
def runner():
    return CliRunner()


class TestCliVersion:
    def test_version_flag(self, runner):
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "xhs-cli" in result.output
        assert __version__ in result.output


class TestCliHelp:
    def test_main_help(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        # Should list all command groups
        for cmd in ["login", "logout", "status", "whoami", "search", "read",
                     "feed", "topics", "user", "user-posts", "followers",
                     "following", "like", "unlike", "comment", "favorite",
                     "unfavorite", "favorites", "post"]:
            assert cmd in result.output, f"Command '{cmd}' not found in --help output"

    def test_search_help(self, runner):
        result = runner.invoke(cli, ["search", "--help"])
        assert result.exit_code == 0
        assert "--json" in result.output

    def test_post_help(self, runner):
        result = runner.invoke(cli, ["post", "--help"])
        assert result.exit_code == 0
        assert "--image" in result.output
        assert "--content" in result.output

    def test_favorites_help(self, runner):
        result = runner.invoke(cli, ["favorites", "--help"])
        assert result.exit_code == 0
        assert "--max" in result.output


class TestStatusNotLoggedIn:
    def test_status_no_cookies(self, runner, tmp_config_dir):
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 1
        assert "Not logged in" in result.output

    def test_status_uses_saved_cookie_only(self, runner, tmp_config_dir, monkeypatch):
        monkeypatch.setattr(cli_module, "get_saved_cookie_string", lambda: "a1=abc")
        monkeypatch.setattr(
            cli_module,
            "get_cookie_string",
            lambda: pytest.fail("status should not trigger browser cookie extraction"),
        )
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "saved cookies" in result.output


class TestLoginCookieValidation:
    def test_login_valid_cookie(self, runner, tmp_config_dir):
        result = runner.invoke(cli, ["login", "--cookie", "a1=abc; web_session=xyz"])
        assert result.exit_code == 0
        assert "Cookie saved" in result.output

    def test_login_invalid_cookie(self, runner, tmp_config_dir):
        result = runner.invoke(cli, ["login", "--cookie", "bad_cookie_string"])
        assert result.exit_code == 1
        assert "Invalid cookie" in result.output

    def test_login_empty_cookie(self, runner, tmp_config_dir, monkeypatch):
        monkeypatch.setattr(
            cli_module,
            "qrcode_login",
            lambda: pytest.fail("qrcode_login should not be called for empty --cookie"),
        )
        result = runner.invoke(cli, ["login", "--cookie", ""])
        assert result.exit_code == 1
        assert "Invalid cookie" in result.output

    def test_login_verify_transient_error_does_not_clear(self, runner, tmp_config_dir, monkeypatch):
        monkeypatch.setattr(cli_module, "get_cookie_string", lambda: "a1=abc")
        monkeypatch.setattr(cli_module, "_verify_cookies", lambda _cookie_dict: None)
        monkeypatch.setattr(
            cli_module,
            "clear_cookies",
            lambda: pytest.fail("clear_cookies should not be called on transient verify errors"),
        )
        monkeypatch.setattr(cli_module, "qrcode_login", lambda: "a1=new")

        result = runner.invoke(cli, ["login"])
        assert result.exit_code == 0
        assert "Unable to verify cookies" in result.output

    def test_login_verify_invalid_clears_stale_cookies(self, runner, tmp_config_dir, monkeypatch):
        called = {"cleared": False}
        monkeypatch.setattr(cli_module, "get_cookie_string", lambda: "a1=abc")
        monkeypatch.setattr(cli_module, "_verify_cookies", lambda _cookie_dict: False)
        monkeypatch.setattr(
            cli_module,
            "clear_cookies",
            lambda: called.__setitem__("cleared", True) or ["cookies.json"],
        )
        monkeypatch.setattr(cli_module, "qrcode_login", lambda: "a1=new")

        result = runner.invoke(cli, ["login"])
        assert result.exit_code == 0
        assert called["cleared"]


class TestLogout:
    def test_logout_with_cookies(self, runner, tmp_config_dir):
        # First save some cookies
        runner.invoke(cli, ["login", "--cookie", "a1=abc; web_session=xyz"])
        # Then logout
        result = runner.invoke(cli, ["logout"])
        assert result.exit_code == 0
        assert "Logged out" in result.output

    def test_logout_no_cookies(self, runner, tmp_config_dir):
        result = runner.invoke(cli, ["logout"])
        assert result.exit_code == 0
        assert "No saved cookies" in result.output
