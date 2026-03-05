"""Authentication for Xiaohongshu.

Strategy:
1. Try loading saved cookies from ~/.xhs-cli/cookies.json
2. Try extracting cookies from local Chrome/Firefox via browser-cookie3
3. Fallback: QR code login via API + terminal display
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .exceptions import LoginError

logger = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".xhs-cli"
COOKIE_FILE = CONFIG_DIR / "cookies.json"
# Cache file for xsec_token: maps note_id -> xsec_token so users don't
# need to copy-paste tokens manually after search.
TOKEN_CACHE_FILE = CONFIG_DIR / "token_cache.json"

# a1 is required for signing. web_session is needed for authenticated endpoints
# but not for anonymous operations like search.
REQUIRED_COOKIES = {"a1"}


def get_saved_cookie_string() -> str | None:
    """Load only saved cookies from local config file.

    This helper never triggers browser extraction and has no write side effects.
    """
    return _load_saved_cookies()


def get_cookie_string() -> str | None:
    """Try all auth methods in order. Returns cookie string or None."""
    # 1. Saved cookies
    cookie = _load_saved_cookies()
    if cookie:
        logger.info("Loaded saved cookies from %s", COOKIE_FILE)
        return cookie

    # 2. browser-cookie3
    cookie = _extract_browser_cookies()
    if cookie:
        logger.info("Extracted cookies from local browser")
        save_cookies(cookie)
        return cookie

    return None


def _load_saved_cookies() -> str | None:
    """Load cookies from saved file."""
    if not COOKIE_FILE.exists():
        return None

    try:
        data = json.loads(COOKIE_FILE.read_text())
        cookies = data.get("cookies", {})
        if _has_required_cookies(cookies):
            return _dict_to_cookie_str(cookies)
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Failed to load saved cookies: %s", e)

    return None


def _extract_browser_cookies() -> str | None:
    """Extract xiaohongshu cookies from local browsers using browser-cookie3.

    Runs extraction in a subprocess with timeout to avoid hanging
    when the browser is running (Chrome DB lock issue).
    """
    import subprocess
    import sys

    # Python script to run in subprocess
    extract_script = '''
import json, sys
try:
    import browser_cookie3 as bc3
except ImportError:
    print(json.dumps({"error": "not_installed"}))
    sys.exit(0)

browsers = [
    ("Chrome", bc3.chrome),
    ("Firefox", bc3.firefox),
    ("Edge", bc3.edge),
    ("Brave", bc3.brave),
]

for name, loader in browsers:
    try:
        cj = loader(domain_name=".xiaohongshu.com")
        cookies = {c.name: c.value for c in cj if "xiaohongshu" in (c.domain or "")}
        if "a1" in cookies:
            print(json.dumps({"browser": name, "cookies": cookies}))
            sys.exit(0)
    except Exception:
        pass

print(json.dumps({"error": "no_cookies"}))
'''

    try:
        result = subprocess.run(
            [sys.executable, "-c", extract_script],
            capture_output=True, text=True, timeout=15,
        )

        if result.returncode != 0:
            logger.debug("Cookie extraction subprocess failed: %s", result.stderr)
            return None

        data = json.loads(result.stdout.strip())

        if "error" in data:
            if data["error"] == "not_installed":
                logger.warning("browser-cookie3 not installed")
            else:
                logger.debug("No valid cookies found in any browser")
            return None

        cookies = data["cookies"]
        browser = data["browser"]
        logger.info("Found valid cookies in %s (%d cookies)", browser, len(cookies))
        return _dict_to_cookie_str(cookies)

    except subprocess.TimeoutExpired:
        logger.warning("Cookie extraction timed out (browser may be running). "
                       "Try closing your browser or use `xhs login --cookie <string>`")
        return None
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Cookie extraction parse error: %s", e)
        return None


def qrcode_login() -> str:
    """Login via QR code displayed to the user.

    Opens xiaohongshu login page in camoufox (headless), captures the QR code
    as a screenshot, opens it with the system image viewer, then polls for
    login completion by checking cookies.
    """
    import tempfile
    import time

    from camoufox.sync_api import Camoufox

    print("🔑 Starting QR code login...")

    with Camoufox(headless=True) as browser:
        page = browser.new_page()
        page.goto("https://www.xiaohongshu.com", wait_until="domcontentloaded", timeout=20000)
        time.sleep(3)

        # Dismiss any overlay/mask that might block clicks (cookie consent, etc.)
        mask_selectors = [
            ".reds-mask",
            '[aria-label="弹窗遮罩"]',
            ".close-button",
            ".reds-popup-close",
        ]
        for mask_sel in mask_selectors:
            mask = page.query_selector(mask_sel)
            if mask:
                try:
                    mask.click(force=True)
                    time.sleep(1)
                except Exception:
                    pass

        # Try clicking login button with force=True to bypass any remaining overlays
        login_btn = (
            page.query_selector('.login-btn') or
            page.query_selector('[class*="login"]') or
            page.query_selector('button:has-text("登录")')
        )
        if login_btn:
            try:
                login_btn.click(force=True)
                time.sleep(3)
            except Exception:
                # If click still fails, navigate directly to login page
                logger.debug("Login button click failed, trying direct navigation")
                pass

        # If no QR code visible yet, try navigating directly to the login URL
        qr_visible = page.query_selector(".qrcode-img") or page.query_selector(
            'img[class*="qrcode"]'
        )
        if not qr_visible:
            page.goto(
                "https://www.xiaohongshu.com/login",
                wait_until="domcontentloaded",
                timeout=20000,
            )
            time.sleep(3)

        # Try to screenshot the QR code element directly
        qr_selectors = [
            '.qrcode-img',
            'img[class*="qrcode"]',
            'img[class*="qr-code"]',
            '.login-container img',
            'canvas[class*="qrcode"]',
        ]

        qr_path = Path(tempfile.mkdtemp()) / "xhs_qrcode.png"
        qr_found = False

        for sel in qr_selectors:
            el = page.query_selector(sel)
            if el:
                try:
                    el.screenshot(path=str(qr_path))
                    qr_found = True
                    break
                except Exception:
                    continue

        # Fallback: screenshot the entire login modal or viewport
        if not qr_found:
            modal_selectors = [
                '.login-container',
                '[class*="login-modal"]',
                '[class*="login-dialog"]',
                '.modal-content',
            ]
            for sel in modal_selectors:
                el = page.query_selector(sel)
                if el:
                    try:
                        el.screenshot(path=str(qr_path))
                        qr_found = True
                        break
                    except Exception:
                        continue

        # Last resort: full page screenshot
        if not qr_found:
            page.screenshot(path=str(qr_path), full_page=False)
            qr_found = True

        # Display QR code directly in the terminal
        print("\n📱 Scan the QR code below with the Xiaohongshu app:\n")
        _display_image_in_terminal(qr_path)

        # Record current web_session value BEFORE user scans.
        # The page may already have a stale web_session cookie from
        # the initial load, so we only consider login successful when
        # a NEW or CHANGED web_session appears.
        initial_cookies = page.context.cookies()
        initial_session = ""
        for c in initial_cookies:
            if c["name"] == "web_session" and "xiaohongshu" in c.get("domain", ""):
                initial_session = c["value"]

        # Poll for login completion
        print("\n⏳ Waiting for QR code scan...")
        for i in range(120):
            time.sleep(2)
            cookies = page.context.cookies()
            cookie_dict = {
                c["name"]: c["value"]
                for c in cookies
                if "xiaohongshu" in c.get("domain", "")
            }

            current_session = cookie_dict.get("web_session", "")
            # Login is successful only when web_session is NEW or CHANGED
            if current_session and current_session != initial_session:
                print("✅ Login successful!")
                cookie_str = "; ".join(f"{k}={v}" for k, v in cookie_dict.items())
                save_cookies(cookie_str)
                # Clean up temp file
                try:
                    qr_path.unlink()
                except Exception:
                    pass
                return cookie_str

            if i % 15 == 14:
                print("  Still waiting...")

    raise LoginError("QR code login timed out after 4 minutes")


def _display_image_in_terminal(image_path):
    """Display an image directly in the terminal.

    Uses the iTerm2/WezTerm/Kitty inline image protocol (ESC ]1337)
    which renders images inside the terminal window. Falls back to
    opening with the system viewer if the protocol is not supported.
    """
    import base64
    import subprocess
    import sys

    try:
        with open(image_path, 'rb') as f:
            image_data = base64.b64encode(f.read()).decode('ascii')

        # iTerm2 / WezTerm inline image protocol
        # ESC ] 1337 ; File=[args] : base64_data BEL
        osc = f'\033]1337;File=inline=1;preserveAspectRatio=1;width=40:{image_data}\a'
        sys.stdout.write(osc)
        sys.stdout.write('\n')
        sys.stdout.flush()
    except Exception:
        # Fallback: open with system image viewer
        print(f"QR code saved to: {image_path}")
        try:
            if sys.platform == 'darwin':
                subprocess.Popen(['open', str(image_path)])
            elif sys.platform == 'win32':
                subprocess.Popen(['start', str(image_path)], shell=True)
            else:
                subprocess.Popen(['xdg-open', str(image_path)])
        except Exception:
            print(f"Please open manually: {image_path}")


def save_cookies(cookie_str: str):
    """Save cookies to config file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    cookies = cookie_str_to_dict(cookie_str)
    data = {"cookies": cookies}

    COOKIE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    COOKIE_FILE.chmod(0o600)  # Owner-only read/write
    logger.info("Cookies saved to %s", COOKIE_FILE)


def clear_cookies():
    """Remove saved cookies and token cache (for logout)."""
    removed = []
    for f in (COOKIE_FILE, TOKEN_CACHE_FILE):
        if f.exists():
            f.unlink()
            removed.append(f.name)
    if removed:
        logger.info("Removed: %s", ", ".join(removed))
    return removed


def _has_required_cookies(cookies: dict) -> bool:
    return REQUIRED_COOKIES.issubset(cookies.keys())


def _dict_to_cookie_str(cookies: dict) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


def cookie_str_to_dict(cookie_str: str) -> dict:
    """Parse a cookie header string into a dict.

    Example: "a1=xxx; web_session=yyy" -> {"a1": "xxx", "web_session": "yyy"}
    """
    result = {}
    for item in cookie_str.split(";"):
        item = item.strip()
        if "=" in item:
            k, v = item.split("=", 1)
            result[k.strip()] = v.strip()
    return result


# ===== xsec_token cache =====
# After a search, we cache the note_id -> xsec_token mapping so that
# subsequent commands (note, like, favorite, comment) can automatically
# resolve the token without requiring the user to pass --xsec-token.


def save_token_cache(token_map: dict[str, str]):
    """Save note_id -> xsec_token mapping from search results.

    Merges with any existing cache so tokens from previous searches
    are preserved until overwritten by a new search containing the
    same note_id.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Merge with existing cache
    existing = {}
    if TOKEN_CACHE_FILE.exists():
        try:
            existing = json.loads(TOKEN_CACHE_FILE.read_text())
        except (OSError, json.JSONDecodeError):
            pass

    existing.update(token_map)
    TOKEN_CACHE_FILE.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
    try:
        TOKEN_CACHE_FILE.chmod(0o600)
    except OSError:
        logger.debug("Failed to set permissions on %s", TOKEN_CACHE_FILE)
    logger.info("Cached %d xsec_token(s) to %s", len(token_map), TOKEN_CACHE_FILE)


def load_xsec_token(note_id: str) -> str:
    """Look up cached xsec_token for a given note_id.

    Returns the token string if found, or empty string if not cached.
    """
    if not TOKEN_CACHE_FILE.exists():
        return ""

    try:
        cache = json.loads(TOKEN_CACHE_FILE.read_text())
        token = cache.get(note_id, "")
        if token:
            logger.info("Auto-resolved xsec_token for %s from cache", note_id)
        return token
    except (OSError, json.JSONDecodeError):
        return ""
