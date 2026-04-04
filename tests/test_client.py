"""Unit tests for xhs_cli.client module (no real browser)."""

from __future__ import annotations

import pytest

from xhs_cli.client import XhsClient
from xhs_cli.exceptions import DataFetchError, LoginError


class _FakePage:
    def __init__(self, url: str, evaluate_result):
        self.url = url
        self._evaluate_result = evaluate_result

    def evaluate(self, _script, *_args):
        return self._evaluate_result


class _FakeProfilePage:
    def __init__(self, evaluate_result, url: str = "https://www.xiaohongshu.com/user/profile/u123"):
        self._evaluate_result = evaluate_result
        self.url = url

    def goto(self, *_args, **_kwargs):
        return None

    def evaluate(self, _script, *_args):
        return self._evaluate_result

    def text_content(self, _selector):
        return ""


class _FakeWaitPage:
    def __init__(self, url: str, body: str):
        self.url = url
        self._body = body

    def evaluate(self, _script, *_args):
        return False

    def text_content(self, _selector):
        return self._body


class _FakeHydratePage:
    def __init__(self, html: str, url: str = "https://www.xiaohongshu.com/explore"):
        self.url = url
        self._html = html
        self._hydrated = False

    def evaluate(self, script, *args):
        if args and "eval(scriptText)" in script:
            self._hydrated = True
            return True
        if "window.__INITIAL_STATE__ !== undefined && window.__INITIAL_STATE__ !== null" in script:
            if args:
                self._hydrated = True
                return True
            return self._hydrated
        if "window.__INITIAL_STATE__ !== undefined" in script:
            return self._hydrated
        if "window.__INITIAL_STATE__" in script:
            return self._hydrated
        return False

    def content(self):
        return self._html

    def text_content(self, _selector):
        return ""


class _FakeGotoPage:
    def __init__(self, url: str):
        self.url = url

    def goto(self, url, *_args, **_kwargs):
        self.url = url

    def text_content(self, _selector):
        return ""

    def evaluate(self, _script, *_args):
        return False


class TestGetNoteComments:
    def test_extracts_note_comments_and_applies_max_limit(self):
        client = XhsClient({})
        client._page = _FakePage(
            "https://www.xiaohongshu.com/explore/note123",
            {"comments": [{"id": "c1"}, {"id": "c2"}]},
        )

        comments = client.get_note_comments("note123", max_comments=1)
        assert comments == [{"id": "c1"}]

    def test_navigates_to_target_note_when_page_mismatch(self, monkeypatch):
        client = XhsClient({})
        client._page = _FakePage(
            "https://www.xiaohongshu.com/explore/other",
            [{"id": "c1"}],
        )
        called = {"value": False}

        def _fake_nav(note_id: str, xsec_token: str):
            called["value"] = True
            assert note_id == "note123"
            assert xsec_token == "tok"
            client._page.url = f"https://www.xiaohongshu.com/explore/{note_id}"

        monkeypatch.setattr(client, "_navigate_to_note", _fake_nav)
        comments = client.get_note_comments("note123", xsec_token="tok", max_comments=10)
        assert called["value"]
        assert comments == [{"id": "c1"}]


class TestPublishResultHeuristic:
    def test_success_indicator_in_page_text(self):
        assert XhsClient._is_publish_success("发布成功", "https://creator.xiaohongshu.com/publish/publish")

    def test_success_when_redirected_away_from_publish_url(self):
        assert XhsClient._is_publish_success(
            "",
            "https://creator.xiaohongshu.com/note/123",
            "123",
        )

    def test_failure_when_no_success_signal_and_still_on_publish_page(self):
        assert not XhsClient._is_publish_success(
            "",
            "https://creator.xiaohongshu.com/publish/publish",
        )

    def test_failure_when_redirected_without_publish_signal_or_note_id(self):
        assert not XhsClient._is_publish_success(
            "",
            "https://creator.xiaohongshu.com/login",
        )

    def test_failure_when_only_generic_success_word_present(self):
        assert not XhsClient._is_publish_success(
            "Operation success",
            "https://creator.xiaohongshu.com/publish/publish",
        )

    def test_extract_note_id_from_explore_url(self):
        note_id = XhsClient._extract_note_id_from_url("https://www.xiaohongshu.com/explore/abc123")
        assert note_id == "abc123"

    def test_extract_note_id_from_query(self):
        note_id = XhsClient._extract_note_id_from_url(
            "https://creator.xiaohongshu.com/publish/success?noteId=xyz987"
        )
        assert note_id == "xyz987"


class TestCreatorPublishAccessProbe:
    def test_probe_returns_false_after_creator_login_redirect(self, monkeypatch):
        client = XhsClient({})
        client._page = _FakeGotoPage(
            "https://www.xiaohongshu.com/explore"
        )

        def _fake_goto(*_args, **_kwargs):
            client._page.url = (
                "https://creator.xiaohongshu.com/login"
                "?source=&redirectReason=401&lastUrl=%252Fpublish%252Fpublish"
            )

        monkeypatch.setattr(client, "_goto", _fake_goto)

        assert client.probe_creator_publish_access() is False

    def test_probe_returns_true_when_publish_page_is_accessible(self, monkeypatch):
        client = XhsClient({})
        client._page = _FakeGotoPage("https://www.xiaohongshu.com/explore")
        monkeypatch.setattr(
            client,
            "_goto",
            lambda *_args, **_kwargs: setattr(
                client._page, "url", "https://creator.xiaohongshu.com/publish/publish"
            ),
        )

        assert client.probe_creator_publish_access() is True


class TestGetUserInfoFallback:
    def test_returns_unwrapped_user_object_when_key_fields_missing(self, monkeypatch):
        client = XhsClient({})
        client._page = _FakeProfilePage({"nickname": "TestUser", "userId": "u123"})
        monkeypatch.setattr(client, "_human_wait", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(client, "_wait_for_data", lambda *_args, **_kwargs: None)

        info = client.get_user_info("u123")
        assert info["nickname"] == "TestUser"

    def test_returns_minimal_fallback_when_state_missing(self, monkeypatch):
        client = XhsClient({})
        client._page = _FakeProfilePage(None)
        monkeypatch.setattr(client, "_human_wait", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(client, "_wait_for_data", lambda *_args, **_kwargs: None)

        info = client.get_user_info("u123")
        assert info == {"userInfo": {"userId": "u123"}}


class TestWaitForData:
    def test_raises_login_error_when_verification_page_detected(self, monkeypatch):
        client = XhsClient({})
        client._page = _FakeWaitPage(
            "https://www.xiaohongshu.com/website-login/captcha?verifyUuid=abc",
            "Security Verification",
        )
        monkeypatch.setattr("xhs_cli.client.time.sleep", lambda *_args, **_kwargs: None)

        with pytest.raises(LoginError, match="security verification"):
            client._wait_for_data(
                "() => false",
                timeout=0.01,
                desc="user profile",
                raise_on_timeout=True,
            )

    def test_raises_data_fetch_error_when_not_blocked(self, monkeypatch):
        client = XhsClient({})
        client._page = _FakeWaitPage(
            "https://www.xiaohongshu.com/user/profile/u123",
            "normal page body",
        )
        monkeypatch.setattr("xhs_cli.client.time.sleep", lambda *_args, **_kwargs: None)

        with pytest.raises(DataFetchError, match="user profile"):
            client._wait_for_data(
                "() => false",
                timeout=0.01,
                desc="user profile",
                raise_on_timeout=True,
            )

    def test_wait_for_data_hydrates_initial_state_from_inline_html(self, monkeypatch):
        client = XhsClient({})
        client._page = _FakeHydratePage(
            '<html><body><script>window.__INITIAL_STATE__={"feed":{"feeds":[{"id":"n1"}]}}</script></body></html>'
        )
        monkeypatch.setattr("xhs_cli.client.time.sleep", lambda *_args, **_kwargs: None)

        client._wait_for_data(
            "() => !!window.__INITIAL_STATE__",
            timeout=0.5,
            desc="feed.feeds",
            raise_on_timeout=True,
        )

    def test_hydrate_initial_state_returns_false_when_no_inline_state(self):
        client = XhsClient({})
        client._page = _FakeHydratePage("<html><body><div>no state</div></body></html>")

        assert client._hydrate_initial_state_from_html() is False
