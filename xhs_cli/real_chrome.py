"""Helpers for connecting xhs-cli to a real Chrome session via CDP."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from playwright.sync_api import sync_playwright

from .client import XhsClient

DEFAULT_CHROME_CDP_URL = "http://127.0.0.1:9222"


def build_cdp_launch_help(cdp_url: str) -> str:
    """Return a short remediation message for enabling Chrome remote debugging."""
    port = cdp_url.rsplit(":", 1)[-1] if ":" in cdp_url else "9222"
    return (
        f"Cannot connect to real Chrome at {cdp_url}. "
        "Quit Chrome completely, then relaunch it with remote debugging enabled. "
        "Example (macOS):\n"
        f'  /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome '
        f"--remote-debugging-port={port} --profile-directory=Default"
    )


@contextmanager
def get_real_chrome_client(cdp_url: str = DEFAULT_CHROME_CDP_URL) -> Iterator[XhsClient]:
    """Connect to a real Chrome session and expose it as an XhsClient-like object."""
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.connect_over_cdp(cdp_url)
        except Exception as exc:  # pragma: no cover - exact playwright error varies
            raise RuntimeError(build_cdp_launch_help(cdp_url)) from exc

        contexts = list(browser.contexts)
        if not contexts:
            raise RuntimeError(
                "Connected to Chrome, but no browser context is available. "
                "Open at least one normal Chrome window in that session and retry."
            )

        context = contexts[0]
        page = context.new_page()

        client = XhsClient({})
        client._browser = browser
        client._page = page

        try:
            yield client
        finally:
            try:
                page.close()
            except Exception:
                pass
