"""Unit tests for xhs_cli.client module (no real browser)."""

from __future__ import annotations

from xhs_cli.client import XhsClient


class _FakePage:
    def __init__(self, url: str, evaluate_result):
        self.url = url
        self._evaluate_result = evaluate_result

    def evaluate(self, _script, *_args):
        return self._evaluate_result


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
        assert XhsClient._is_publish_success("", "https://creator.xiaohongshu.com/note/123")

    def test_failure_when_no_success_signal_and_still_on_publish_page(self):
        assert not XhsClient._is_publish_success(
            "",
            "https://creator.xiaohongshu.com/publish/publish",
        )
