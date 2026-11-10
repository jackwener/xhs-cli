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
from typing import Any

from .exceptions import LoginError

logger = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".xhs-cli"
COOKIE_FILE = CONFIG_DIR / "cookies.json"
# Cache file for xsec_token: maps note_id -> xsec_token so users don't
# need to copy-paste tokens manually after search.
TOKEN_CACHE_FILE = CONFIG_DIR / "token_cache.json"

# a1 is required for signing; web_session is required for a stable logged-in session.
REQUIRED_COOKIES = {"a1", "web_session"}
LOGIN_URL = "https://www.xiaohongshu.com/login"
QR_CREATE_ENDPOINT = "/api/sns/web/v1/login/qrcode/create"
QR_USERINFO_ENDPOINT = "/api/qrcode/userinfo"
QR_STATUS_ENDPOINT = "/api/sns/web/v1/login/qrcode/status"
BROWSER_EXPORT_COOKIE_NAMES = (
    "a1",
    "webId",
    "web_session",
    "web_session_sec",
    "id_token",
    "websectiga",
    "sec_poison_id",
    "xsecappid",
    "gid",
    "abRequestId",
    "webBuild",
    "loadts",
)


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
        if "a1" in cookies and "web_session" in cookies:
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
    """Login via QR code displayed to the user."""
    return _browser_assisted_qrcode_login()


def _browser_assisted_qrcode_login() -> str:
    """Login via QR code using network responses instead of page DOM heuristics."""
    import time

    from camoufox.sync_api import Camoufox

    print("🔑 Starting QR code login...")

    with Camoufox(headless=True) as browser:
        page = browser.new_page()
        state = {"last_status": -1}

        def _handle_response(response) -> None:
            if QR_USERINFO_ENDPOINT not in response.url:
                return
            try:
                payload = _browser_response_payload(response)
            except Exception as exc:
                logger.debug("Failed to parse QR poll response: %s", exc)
                return

            code_status = int(payload.get("codeStatus", -1))
            if code_status == state["last_status"]:
                return
            state["last_status"] = code_status

            if code_status == 1:
                print("📲 Scanned! Waiting for confirmation...")
            elif code_status == 2:
                print("✅ Login confirmed!")

        page.on("response", _handle_response)

        try:
            with page.expect_response(
                lambda response: (
                    QR_CREATE_ENDPOINT in response.url
                    and response.request.method == "POST"
                ),
                timeout=20_000,
            ) as qr_response_info:
                page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=20_000)
        except Exception as exc:
            raise LoginError("Failed to load Xiaohongshu login page in Camoufox.") from exc

        qr_payload = _browser_response_payload(qr_response_info.value)
        qr_url = str(qr_payload.get("url", "")).strip()
        if not qr_url:
            raise LoginError(f"QR login did not expose a QR URL: {qr_payload}")

        print("\n📱 Scan the QR code below with the Xiaohongshu app:\n")
        if not _display_qr_text_in_terminal(qr_url):
            print(f"QR URL: {qr_url}")
        print("\n⏳ Waiting for QR code scan...")

        try:
            with page.expect_response(
                lambda response: (
                    QR_STATUS_ENDPOINT in response.url
                    and response.request.method == "GET"
                ),
                timeout=240_000,
            ) as completion_info:
                pass
        except Exception as exc:
            raise LoginError("QR code login timed out after 4 minutes") from exc

        completion_response = completion_info.value
        _raise_for_browser_response(completion_response)
        completion_data = _browser_response_payload(completion_response)
        _wait_for_browser_login_settled(page)
        time.sleep(1)

        cookies = _normalize_browser_cookies(page.context.cookies())
        login_info = completion_data.get("login_info", {})
        if not isinstance(login_info, dict):
            login_info = {}

        session = login_info.get("session") or completion_data.get("session")
        secure_session = login_info.get("secure_session") or completion_data.get("secure_session")
        if isinstance(session, str) and session:
            cookies["web_session"] = session
        if isinstance(secure_session, str) and secure_session:
            cookies["web_session_sec"] = secure_session

        if not _has_required_cookies(cookies):
            raise LoginError(
                "QR login succeeded, but exported cookies were incomplete: "
                f"keys={', '.join(sorted(cookies.keys()))}"
            )

        cookie_str = _dict_to_cookie_str(cookies)
        save_cookies(cookie_str)
        return cookie_str
def _normalize_browser_cookies(raw_cookies: list[dict[str, Any]]) -> dict[str, str]:
    """Convert browser cookies into the local persisted cookie shape."""
    cookies: dict[str, str] = {}
    for entry in raw_cookies:
        name = entry.get("name")
        value = entry.get("value")
        domain = entry.get("domain", "")
        if not isinstance(name, str) or not isinstance(value, str):
            continue
        if name not in BROWSER_EXPORT_COOKIE_NAMES:
            continue
        if not isinstance(domain, str) or "xiaohongshu.com" not in domain:
            continue
        cookies[name] = value
    return cookies


def _unwrap_browser_response_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the inner data payload when browser responses use a common envelope."""
    data = payload.get("data")
    if isinstance(data, dict):
        return data
    return payload


def _browser_response_payload(response: Any) -> dict[str, Any]:
    """Decode a browser response body as JSON."""
    try:
        data = response.json()
    except Exception as exc:
        raise LoginError(f"Browser response from {response.url} was not valid JSON.") from exc
    if not isinstance(data, dict):
        raise LoginError(
            f"Browser response from {response.url} returned unexpected payload: {data!r}"
        )
    return _unwrap_browser_response_payload(data)


def _raise_for_browser_response(response: Any) -> None:
    """Raise a domain error for QR completion failures."""
    status = getattr(response, "status", None)
    if status in (461, 471):
        verify_type = response.headers.get("verifytype", "unknown")
        verify_uuid = response.headers.get("verifyuuid", "unknown")
        raise LoginError(
            "QR login requires verification. "
            f"verify_type={verify_type} verify_uuid={verify_uuid}"
        )
    if status and status >= 400:
        try:
            body = response.text()
        except Exception:
            body = "<unavailable>"
        raise LoginError(f"QR login failed: HTTP {status} body={body[:300]}")


def _wait_for_browser_login_settled(page: Any) -> None:
    """Wait briefly for the browser session and post-login page state to stabilize."""
    try:
        page.wait_for_url("**/explore*", timeout=5_000)
    except Exception:
        logger.debug("QR login did not navigate to /explore before timeout")

    try:
        response = page.wait_for_response(
            lambda resp: "/api/sns/web/v2/user/me" in resp.url and resp.request.method == "GET",
            timeout=5_000,
        )
    except Exception:
        logger.debug("QR login did not observe a post-login user/me response before timeout")
        return

    try:
        payload = _browser_response_payload(response)
    except Exception as exc:
        logger.debug("Failed to parse browser user/me response after QR login: %s", exc)
        return

    if bool(payload.get("guest", False)):
        logger.debug("QR login settled with guest=true in user/me payload: %s", payload)


def _render_qr_half_blocks(matrix: list[list[bool]]) -> str:
    """Render QR matrix using half-block characters (▀▄█)."""
    if not matrix:
        return ""

    border = 2
    width = len(matrix[0]) + border * 2
    padded = [[False] * width for _ in range(border)]
    for row in matrix:
        padded.append(([False] * border) + row + ([False] * border))
    padded.extend([[False] * width for _ in range(border)])

    chars = {
        (False, False): " ",
        (True, False): "▀",
        (False, True): "▄",
        (True, True): "█",
    }

    lines = []
    for y in range(0, len(padded), 2):
        top = padded[y]
        bottom = padded[y + 1] if y + 1 < len(padded) else [False] * width
        line = "".join(chars[(top[x], bottom[x])] for x in range(width))
        lines.append(line)
    return "\n".join(lines)


def _display_qr_text_in_terminal(qr_text: str) -> bool:
    """Render QR text as terminal half-block art."""
    try:
        import qrcode
    except ImportError:
        return False

    try:
        qr = qrcode.QRCode(border=0)
        qr.add_data(qr_text)
        qr.make(fit=True)
        print(_render_qr_half_blocks(qr.get_matrix()))
        return True
    except Exception:
        return False


def save_cookies(cookie_str: str):
    """Save cookies to config file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    cookies = cookie_str_to_dict(cookie_str)
    data = {"cookies": cookies}

    COOKIE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    try:
        COOKIE_FILE.chmod(0o600)  # Owner-only read/write
    except OSError:
        logger.debug("Failed to set permissions on %s", COOKIE_FILE)
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
            loaded = json.loads(TOKEN_CACHE_FILE.read_text())
            if isinstance(loaded, dict):
                existing = loaded
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
        if not isinstance(cache, dict):
            return ""
        token = cache.get(note_id, "")
        if token:
            logger.info("Auto-resolved xsec_token for %s from cache", note_id)
        return token
    except (OSError, json.JSONDecodeError):
        return ""
