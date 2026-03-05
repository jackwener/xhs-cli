"""Unit tests for xhs_cli.auth module (pure functions, no browser)."""

from __future__ import annotations

import json
import os
import stat

from xhs_cli.auth import (
    _dict_to_cookie_str,
    _has_required_cookies,
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
    def test_has_a1(self):
        assert _has_required_cookies({"a1": "val", "other": "x"})

    def test_missing_a1(self):
        assert not _has_required_cookies({"web_session": "val"})

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
