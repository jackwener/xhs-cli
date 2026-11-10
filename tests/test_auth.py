"""Unit tests for xhs_cli.auth module (pure functions, no browser)."""

from __future__ import annotations

import json
import os
import stat

from xhs_cli.auth import (
    _browser_response_payload,
    _dict_to_cookie_str,
    _has_required_cookies,
    _normalize_browser_cookies,
    _render_qr_half_blocks,
    _unwrap_browser_response_payload,
    clear_cookies,
    cookie_str_to_dict,
    get_cookie_string,
    get_saved_cookie_string,
    load_xsec_token,
    save_cookies,
    save_token_cache,
)


class TestCookieStrToDict:
    def test_basic(self):
        result = cookie_str_to_dict("a1=xxx; web_session=yyy")
        assert result == {"a1": "xxx", "web_session": "yyy"}

    def test_empty_string(self):
        assert cookie_str_to_dict("") == {}

    def test_single_cookie(self):
        assert cookie_str_to_dict("a1=abc") == {"a1": "abc"}

    def test_value_with_equals(self):
        result = cookie_str_to_dict("token=abc=def=ghi")
        assert result == {"token": "abc=def=ghi"}

    def test_whitespace_handling(self):
        result = cookie_str_to_dict("  a1 = xxx ;  b = yyy  ")
        assert result == {"a1": "xxx", "b": "yyy"}

    def test_no_equals(self):
        result = cookie_str_to_dict("invalid_cookie")
        assert result == {}

    def test_mixed_valid_invalid(self):
        result = cookie_str_to_dict("a1=xxx; bad; web_session=yyy")
        assert result == {"a1": "xxx", "web_session": "yyy"}


class TestDictToCookieStr:
    def test_basic(self):
        result = _dict_to_cookie_str({"a1": "xxx", "b": "yyy"})
        assert "a1=xxx" in result
        assert "b=yyy" in result

    def test_empty(self):
        assert _dict_to_cookie_str({}) == ""

    def test_roundtrip(self):
        original = {"a1": "abc", "web_session": "def"}
        cookie_str = _dict_to_cookie_str(original)
        parsed = cookie_str_to_dict(cookie_str)
        assert parsed == original


class TestHasRequiredCookies:
    def test_has_a1_and_web_session(self):
        assert _has_required_cookies({"a1": "val", "web_session": "sess", "other": "x"})

    def test_missing_a1(self):
        assert not _has_required_cookies({"web_session": "val"})

    def test_missing_web_session(self):
        assert not _has_required_cookies({"a1": "val"})

    def test_empty(self):
        assert not _has_required_cookies({})


class TestSaveAndLoadCookies:
    def test_save_and_load(self, tmp_config_dir, sample_cookie_str):
        save_cookies(sample_cookie_str)

        # Verify file exists
        cookie_file = tmp_config_dir / "cookies.json"
        assert cookie_file.exists()

        # Verify contents
        data = json.loads(cookie_file.read_text())
        assert "cookies" in data
        assert data["cookies"]["a1"] == "abc123"

    def test_file_permissions(self, tmp_config_dir, sample_cookie_str):
        save_cookies(sample_cookie_str)
        cookie_file = tmp_config_dir / "cookies.json"
        mode = stat.S_IMODE(os.stat(cookie_file).st_mode)
        assert mode == 0o600

    def test_load_roundtrip(self, tmp_config_dir, sample_cookie_str):
        save_cookies(sample_cookie_str)
        loaded = get_cookie_string()
        assert loaded is not None
        parsed = cookie_str_to_dict(loaded)
        assert parsed["a1"] == "abc123"
        assert parsed["web_session"] == "xyz789"

    def test_load_nonexistent(self, tmp_config_dir):
        assert get_cookie_string() is None

    def test_get_saved_cookie_string(self, tmp_config_dir, sample_cookie_str):
        save_cookies(sample_cookie_str)
        loaded = get_saved_cookie_string()
        assert loaded is not None
        parsed = cookie_str_to_dict(loaded)
        assert parsed["a1"] == "abc123"

    def test_save_cookies_handles_chmod_oserror(
        self,
        tmp_config_dir,
        sample_cookie_str,
        monkeypatch,
    ):
        from pathlib import Path

        def _chmod_with_failure(path_obj: Path, mode: int):
            if path_obj.name == "cookies.json":
                raise OSError("chmod not supported")
            return None

        monkeypatch.setattr(Path, "chmod", _chmod_with_failure)
        save_cookies(sample_cookie_str)
        cookie_file = tmp_config_dir / "cookies.json"
        assert cookie_file.exists()


class TestClearCookies:
    def test_clear(self, tmp_config_dir, sample_cookie_str):
        save_cookies(sample_cookie_str)
        save_token_cache({"note1": "token1"})
        removed = clear_cookies()
        assert "cookies.json" in removed
        assert "token_cache.json" in removed

    def test_clear_nothing(self, tmp_config_dir):
        removed = clear_cookies()
        assert removed == []


class TestTokenCache:
    def test_save_and_load(self, tmp_config_dir):
        save_token_cache({"note1": "token_a", "note2": "token_b"})
        assert load_xsec_token("note1") == "token_a"
        assert load_xsec_token("note2") == "token_b"

    def test_load_missing(self, tmp_config_dir):
        save_token_cache({"note1": "token_a"})
        assert load_xsec_token("nonexistent") == ""

    def test_load_no_cache_file(self, tmp_config_dir):
        assert load_xsec_token("anything") == ""

    def test_merge(self, tmp_config_dir):
        save_token_cache({"note1": "token_a"})
        save_token_cache({"note2": "token_b"})

        assert load_xsec_token("note1") == "token_a"
        assert load_xsec_token("note2") == "token_b"

    def test_overwrite(self, tmp_config_dir):
        save_token_cache({"note1": "old"})
        save_token_cache({"note1": "new"})
        assert load_xsec_token("note1") == "new"

    def test_token_cache_file_permissions(self, tmp_config_dir):
        save_token_cache({"note1": "token"})
        token_file = tmp_config_dir / "token_cache.json"
        mode = stat.S_IMODE(os.stat(token_file).st_mode)
        assert mode == 0o600

    def test_load_non_dict_cache(self, tmp_config_dir):
        (tmp_config_dir / "token_cache.json").write_text('["note1"]')
        assert load_xsec_token("note1") == ""

    def test_save_over_non_dict_cache(self, tmp_config_dir):
        (tmp_config_dir / "token_cache.json").write_text('["note1"]')
        save_token_cache({"note1": "token_a"})
        assert load_xsec_token("note1") == "token_a"


class TestQrHalfBlockRender:
    def test_empty_matrix(self):
        assert _render_qr_half_blocks([]) == ""

    def test_block_character_mapping(self):
        matrix = [
            [True, False],
            [True, False],
        ]
        rendered = _render_qr_half_blocks(matrix)
        assert "█" in rendered

    def test_half_block_top_and_bottom(self):
        top_only = [
            [True],
            [False],
        ]
        bottom_only = [
            [False],
            [True],
        ]
        assert "▀" in _render_qr_half_blocks(top_only)
        assert "▄" in _render_qr_half_blocks(bottom_only)


class TestBrowserAssistedQrHelpers:
    def test_normalize_browser_cookies_filters_domain_and_name(self):
        raw = [
            {"name": "a1", "value": "cookie-a1", "domain": ".xiaohongshu.com"},
            {"name": "web_session", "value": "cookie-session", "domain": ".xiaohongshu.com"},
            {"name": "ignored", "value": "x", "domain": ".xiaohongshu.com"},
            {"name": "webId", "value": "wrong-domain", "domain": ".example.com"},
        ]
        assert _normalize_browser_cookies(raw) == {
            "a1": "cookie-a1",
            "web_session": "cookie-session",
        }

    def test_unwrap_browser_response_payload_prefers_data_envelope(self):
        payload = {"success": True, "data": {"url": "https://example.com/qr"}}
        assert _unwrap_browser_response_payload(payload) == {"url": "https://example.com/qr"}

    def test_browser_response_payload_rejects_non_json_dict(self):
        class _Response:
            url = "https://www.xiaohongshu.com/api/sns/web/v1/login/qrcode/create"

            def json(self):
                return ["not", "a", "dict"]

        import pytest

        with pytest.raises(Exception, match="unexpected payload"):
            _browser_response_payload(_Response())

class TestQrCodeLogin:
    def test_qrcode_login_delegates_to_browser_assisted_flow(self, monkeypatch):
        monkeypatch.setattr(
            "xhs_cli.auth._browser_assisted_qrcode_login",
            lambda: "a1=browser; web_session=browser-session",
        )

        from xhs_cli.auth import qrcode_login

        assert qrcode_login() == "a1=browser; web_session=browser-session"
