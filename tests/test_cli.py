"""Unit tests for CLI commands (no browser needed)."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from click.testing import CliRunner

import xhs_cli.cli as cli_module
from xhs_cli import __version__
from xhs_cli.cli import cli
from xhs_cli.exceptions import DataFetchError


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
                     "unfavorite", "favorites", "post", "delete"]:
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
        assert "--json" in result.output

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

    def test_login_cookie_missing_web_session(self, runner, tmp_config_dir):
        result = runner.invoke(cli, ["login", "--cookie", "a1=abc_only"])
        assert result.exit_code == 1
        assert "Invalid cookie" in result.output

    def test_login_cookie_name_collision_is_invalid(self, runner, tmp_config_dir):
        result = runner.invoke(cli, ["login", "--cookie", "my_a1=abc; my_web_session=xyz"])
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
        called = {"qrcode": False}
        monkeypatch.setattr(cli_module, "get_cookie_string", lambda: "a1=abc")
        monkeypatch.setattr(cli_module, "_verify_cookies", lambda _cookie_dict: None)
        monkeypatch.setattr(
            cli_module,
            "clear_cookies",
            lambda: pytest.fail("clear_cookies should not be called on transient verify errors"),
        )
        monkeypatch.setattr(
            cli_module,
            "qrcode_login",
            lambda: called.__setitem__("qrcode", True) or "a1=new",
        )

        result = runner.invoke(cli, ["login"])
        assert result.exit_code == 0
        assert "Unable to verify cookies" in result.output
        assert called["qrcode"] is False

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

    def test_login_verify_ok_but_probe_fails_triggers_refresh(
        self,
        runner,
        tmp_config_dir,
        monkeypatch,
    ):
        called = {"cleared": False, "qrcode": False}
        probe_results = iter([False, True])
        monkeypatch.setattr(
            cli_module,
            "get_cookie_string",
            lambda: "a1=abc; web_session=xyz",
        )
        monkeypatch.setattr(cli_module, "_verify_cookies", lambda _cookie_dict: True)
        monkeypatch.setattr(
            cli_module,
            "_probe_session_usability",
            lambda _cookie_dict: next(probe_results),
        )
        monkeypatch.setattr(
            cli_module,
            "clear_cookies",
            lambda: called.__setitem__("cleared", True) or ["cookies.json"],
        )
        monkeypatch.setattr(
            cli_module,
            "qrcode_login",
            lambda: called.__setitem__("qrcode", True) or "a1=new; web_session=new",
        )

        result = runner.invoke(cli, ["login"])
        assert result.exit_code == 0
        assert called["cleared"] is True
        assert called["qrcode"] is True

    def test_login_qrcode_success_but_probe_fails_exits(self, runner, tmp_config_dir, monkeypatch):
        called = {"cleared": False}
        monkeypatch.setattr(cli_module, "qrcode_login", lambda: "a1=new; web_session=new")
        monkeypatch.setattr(cli_module, "_probe_session_usability", lambda _cookie_dict: False)
        monkeypatch.setattr(
            cli_module,
            "clear_cookies",
            lambda: called.__setitem__("cleared", True) or ["cookies.json"],
        )

        result = runner.invoke(cli, ["login", "--qrcode"])
        assert result.exit_code == 1
        assert called["cleared"] is True
        assert "session is still limited" in result.output

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


class _FakeVerifyClient:
    def __init__(self, info, should_raise=False):
        self._info = info
        self._should_raise = should_raise

    def __enter__(self):
        if self._should_raise:
            raise RuntimeError("boom")
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get_self_info(self):
        return self._info


class TestVerifyCookies:
    def test_guest_session_is_invalid(self, monkeypatch):
        monkeypatch.setattr(
            "xhs_cli.client.XhsClient",
            lambda _cookie_dict: _FakeVerifyClient(
                {"userInfo": {"userId": "u123", "guest": True}}
            ),
        )
        assert cli_module._verify_cookies({"a1": "x", "web_session": "y"}) is False

    def test_profile_with_nickname_is_valid(self, monkeypatch):
        monkeypatch.setattr(
            "xhs_cli.client.XhsClient",
            lambda _cookie_dict: _FakeVerifyClient(
                {"userPageData": {"basicInfo": {"nickname": "Alice", "userId": "u1"}}}
            ),
        )
        assert cli_module._verify_cookies({"a1": "x", "web_session": "y"}) is True

    def test_transient_error_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            "xhs_cli.client.XhsClient",
            lambda _cookie_dict: _FakeVerifyClient({}, should_raise=True),
        )
        assert cli_module._verify_cookies({"a1": "x", "web_session": "y"}) is None


class _FakeProbeClient:
    def __init__(self, feed=None, error=None):
        self._feed = feed if feed is not None else []
        self._error = error

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get_feed(self):
        if self._error:
            raise self._error
        return self._feed


class TestProbeSessionUsability:
    def test_probe_success(self, monkeypatch):
        monkeypatch.setattr(
            "xhs_cli.client.XhsClient",
            lambda _cookie_dict: _FakeProbeClient(feed=[]),
        )
        assert cli_module._probe_session_usability({"a1": "x", "web_session": "y"}) is True

    def test_probe_data_fetch_error(self, monkeypatch):
        monkeypatch.setattr(
            "xhs_cli.client.XhsClient",
            lambda _cookie_dict: _FakeProbeClient(error=DataFetchError("bad state")),
        )
        assert cli_module._probe_session_usability({"a1": "x", "web_session": "y"}) is False

    def test_probe_transient_error(self, monkeypatch):
        monkeypatch.setattr(
            "xhs_cli.client.XhsClient",
            lambda _cookie_dict: _FakeProbeClient(error=RuntimeError("temporary")),
        )
        assert cli_module._probe_session_usability({"a1": "x", "web_session": "y"}) is None


class _FakeDataClient:
    def search_notes(self, _keyword):
        return [
            "bad-item",
            {
                "id": "n1",
                "xsec_token": "tok1",
                "note_card": {
                    "display_title": "title",
                    "user": {"nickname": "alice"},
                    "interact_info": {"liked_count": 12},
                },
            },
        ]

    def get_followers(self, _user_id):
        return ["bad-user", {"nickname": "bob", "userId": "u1"}]


@contextmanager
def _fake_client_ctx(client):
    yield client


class TestCliRobustness:
    def test_search_skips_non_dict_items(self, runner, monkeypatch):
        monkeypatch.setattr(cli_module, "_get_client", lambda: _fake_client_ctx(_FakeDataClient()))
        monkeypatch.setattr(cli_module, "save_token_cache", lambda *_args, **_kwargs: None)
        result = runner.invoke(cli, ["search", "coffee"])
        assert result.exit_code == 0
        assert "Search: coffee" in result.output

    def test_followers_skips_non_dict_items(self, runner, monkeypatch):
        monkeypatch.setattr(cli_module, "_get_client", lambda: _fake_client_ctx(_FakeDataClient()))
        result = runner.invoke(cli, ["followers", "u123"])
        assert result.exit_code == 0
        assert "Followers" in result.output
