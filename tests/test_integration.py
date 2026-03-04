"""Integration smoke tests — require a valid login session.

These tests are marked with @pytest.mark.integration and are SKIPPED
by default. Run them explicitly with:

    uv run pytest tests/test_integration.py -v --override-ini="addopts="

Each test launches a headless browser so total runtime is ~2 minutes.
Commands that internally start multiple browsers (whoami, favorites,
user-posts) use subprocess to avoid asyncio loop conflicts.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest
from click.testing import CliRunner

from xhs_cli.cli import cli

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def runner():
    return CliRunner()


def _run_cli(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    """Run xhs command via subprocess (avoids asyncio loop conflicts)."""
    return subprocess.run(
        [sys.executable, "-m", "xhs_cli.cli"] + list(args),
        capture_output=True, text=True, timeout=timeout,
    )


# ===== Auth =====

class TestStatus:
    def test_status(self, runner):
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "Logged in" in result.output

    def test_whoami(self):
        """whoami launches browser — use subprocess to avoid conflicts."""
        result = _run_cli("whoami")
        assert result.returncode == 0, f"whoami failed: {result.stdout}{result.stderr}"

    def test_whoami_json(self):
        result = _run_cli("whoami", "--json")
        assert result.returncode == 0, f"whoami --json failed: {result.stdout}{result.stderr}"
        data = json.loads(result.stdout)
        assert isinstance(data, dict)


# ===== Search =====

class TestSearch:
    def test_search(self, runner):
        result = runner.invoke(cli, ["search", "咖啡"])
        assert result.exit_code == 0

    def test_search_json(self, runner):
        result = runner.invoke(cli, ["search", "咖啡", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)


# ===== Feed =====

class TestFeed:
    def test_feed(self, runner):
        result = runner.invoke(cli, ["feed"])
        assert result.exit_code == 0

    def test_feed_json(self, runner):
        result = runner.invoke(cli, ["feed", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)


# ===== Topics =====

class TestTopics:
    def test_topics(self, runner):
        result = runner.invoke(cli, ["topics", "旅行"])
        assert result.exit_code == 0

    def test_topics_json(self, runner):
        result = runner.invoke(cli, ["topics", "旅行", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)


# ===== User =====

class TestUser:
    def test_user_self(self):
        """Get own user_id via whoami, then query user profile."""
        whoami = _run_cli("whoami", "--json")
        if whoami.returncode != 0:
            pytest.skip("whoami failed, cannot determine user_id")
        data = json.loads(whoami.stdout)
        user_id = _extract_user_id(data)
        if not user_id:
            pytest.skip("Cannot extract user_id from whoami")

        result = _run_cli("user", user_id)
        assert result.returncode == 0

    def test_user_posts(self):
        """Test user-posts with subprocess (launches multiple browsers)."""
        whoami = _run_cli("whoami", "--json")
        if whoami.returncode != 0:
            pytest.skip("whoami failed")
        data = json.loads(whoami.stdout)
        user_id = _extract_user_id(data)
        if not user_id:
            pytest.skip("Cannot extract user_id")

        result = _run_cli("user-posts", user_id)
        assert result.returncode == 0, f"user-posts failed: {result.stdout}{result.stderr}"


# ===== Favorites =====

class TestFavorites:
    def test_favorites(self):
        """favorites launches 2 browsers internally — use subprocess."""
        result = _run_cli("favorites", "--max", "3", timeout=120)
        assert result.returncode == 0, f"favorites failed: {result.stdout}{result.stderr}"

    def test_favorites_json(self):
        result = _run_cli("favorites", "--max", "3", "--json", timeout=120)
        assert result.returncode == 0, f"favorites --json failed: {result.stdout}{result.stderr}"
        data = json.loads(result.stdout)
        assert isinstance(data, list)


def _extract_user_id(data: dict) -> str:
    """Extract user_id from whoami JSON output."""
    for sub_key in ["userInfo", "basicInfo", "basic_info"]:
        sub = data.get(sub_key, {})
        if isinstance(sub, dict):
            uid = sub.get("userId", "") or sub.get("user_id", "")
            if uid:
                return uid
    return data.get("userId", "") or data.get("user_id", "") or data.get("id", "")
