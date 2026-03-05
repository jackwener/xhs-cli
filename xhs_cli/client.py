"""Xiaohongshu browser-based client using camoufox.

All operations navigate to pages and extract data from window.__INITIAL_STATE__,
exactly like a real user browsing. This avoids API-level risk control (300011).
"""

from __future__ import annotations

import logging
import random
import re
import time

from .exceptions import DataFetchError, LoginError

logger = logging.getLogger(__name__)

# Shared JavaScript function to unwrap Vue reactive refs from __INITIAL_STATE__.
# Vue wraps values in reactive Proxy objects with _value/dep structure.
UNWRAP_JS = """
function unwrap(obj, depth) {
    if (depth > 6 || obj === null || obj === undefined) return obj;
    if (typeof obj !== 'object') return obj;
    if ('_value' in obj && 'dep' in obj) return unwrap(obj._value, depth + 1);
    if ('value' in obj && 'dep' in obj) return unwrap(obj.value, depth + 1);
    if (Array.isArray(obj)) return obj.map(item => unwrap(item, depth + 1));
    const result = {};
    for (const key of Object.keys(obj)) {
        if (key === 'dep' || key.startsWith('__')) continue;
        try { result[key] = unwrap(obj[key], depth + 1); } catch(e) {}
    }
    return result;
}
""".strip()


class XhsClient:
    """Camoufox-based Xiaohongshu client.

    Navigates to real pages and extracts data from __INITIAL_STATE__,
    indistinguishable from a real user browsing.

    Can be used as a context manager:
        with XhsClient(cookie_dict) as client:
            client.start()
            ...
    """

    def __init__(self, cookie_dict: dict):
        self._cookie_dict = cookie_dict
        self._camoufox_ctx = None
        self._browser = None
        self._page = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    @staticmethod
    def _is_publish_success(page_text: str, current_url: str, note_id: str = "") -> bool:
        """Heuristic to determine whether publish action succeeded."""
        success_indicators = [
            "发布成功",
            "已发布",
            "publish-success",
            "published successfully",
        ]
        normalized = (page_text or "").lower()
        url = (current_url or "").lower()
        if "creator.xiaohongshu.com/login" in url or "website-login/captcha" in url:
            return False
        on_publish_page = "publish/publish" in url
        if any(indicator.lower() in normalized for indicator in success_indicators):
            return True
        if on_publish_page:
            return False
        if note_id and note_id.lower() in url:
            return True
        if re.search(r"/(explore|notes?)/([a-zA-Z0-9]+)", url):
            return True
        return False

    @staticmethod
    def _extract_note_id_from_url(url: str) -> str:
        """Extract note_id from common URL patterns."""
        if not url:
            return ""
        patterns = [
            r"/explore/([a-zA-Z0-9]+)",
            r"[?&](?:note_id|noteId|id)=([a-zA-Z0-9]+)",
            r"/notes?/([a-zA-Z0-9]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return ""

    def _extract_note_id_from_page(self) -> str:
        """Best-effort note_id extraction from current page links."""
        try:
            note_id = self._page.evaluate(
                """() => {
                    const links = Array.from(document.querySelectorAll('a[href*="/explore/"]'));
                    const hrefs = [window.location.href, ...links.map(a => a.href || '')];
                    for (const href of hrefs) {
                        const m = href.match(/\\/explore\\/([a-zA-Z0-9]+)/);
                        if (m && m[1]) return m[1];
                    }
                    return "";
                }"""
            )
        except Exception:
            return ""
        return str(note_id or "")

    def start(self):
        """Launch camoufox and inject cookies."""
        from camoufox.sync_api import Camoufox

        logger.info("Starting camoufox browser...")
        self._camoufox_ctx = Camoufox(headless=True)
        self._browser = self._camoufox_ctx.__enter__()
        self._page = self._browser.new_page()

        # Inject cookies
        cookies = [
            {"name": k, "value": v, "domain": ".xiaohongshu.com", "path": "/"}
            for k, v in self._cookie_dict.items()
        ]
        self._page.context.add_cookies(cookies)

        # Navigate to homepage to establish session
        self._goto(
            "https://www.xiaohongshu.com",
            timeout=20000,
            wait_min=1,
            wait_max=2,
            context="establishing browser session",
        )
        logger.info("Browser ready.")

    def close(self):
        """Shut down the browser."""
        if self._camoufox_ctx:
            try:
                self._camoufox_ctx.__exit__(None, None, None)
            except Exception:
                pass
            self._camoufox_ctx = None
            self._browser = None
            self._page = None
            logger.info("Browser closed.")

    # ===== Search =====

    def search_notes(self, keyword: str) -> list[dict]:
        """Search notes by keyword.

        Navigates to search_result page and extracts from __INITIAL_STATE__.search.feeds.
        """
        import urllib.parse
        params = urllib.parse.urlencode({"keyword": keyword, "source": "web_explore_feed"})
        url = f"https://www.xiaohongshu.com/search_result?{params}"

        logger.info("Searching: %s", keyword)
        self._goto(
            url,
            timeout=20000,
            wait_min=1,
            wait_max=2,
            context="loading search page",
        )

        # Wait for search.feeds to be populated by Vue
        self._wait_for_data(
            """() => {
                const s = window.__INITIAL_STATE__;
                if (!s || !s.search) return false;
                const f = s.search.feeds;
                if (!f) return false;
                const d = f._rawValue || f._value || f.value || f;
                return Array.isArray(d) || (d && typeof d === 'object');
            }""",
            timeout=15.0,
            desc="search.feeds",
            raise_on_timeout=True,
        )

        # Extract search feeds
        result = self._page.evaluate(
            """() => {
"""
            + UNWRAP_JS
            + """
            const s = window.__INITIAL_STATE__;
            if (!s || !s.search || !s.search.feeds) return null;
            return unwrap(s.search.feeds, 0);
        }"""
        )

        if not result:
            logger.warning("No search results found in __INITIAL_STATE__")
            return []

        return result if isinstance(result, list) else []

    # ===== Note Detail =====

    def get_note_detail(self, note_id: str, xsec_token: str = "") -> dict:
        """Get note detail by navigating to the explore page.

        Extracts from __INITIAL_STATE__.note.noteDetailMap.
        """
        url = f"https://www.xiaohongshu.com/explore/{note_id}"
        if xsec_token:
            url += f"?xsec_token={xsec_token}&xsec_source=pc_feed"

        logger.info("Loading note: %s", note_id)
        self._goto(
            url,
            timeout=20000,
            wait_min=1.5,
            wait_max=3,
            context=f"loading note {note_id}",
        )

        self._wait_for_data(
            """() => {
                const s = window.__INITIAL_STATE__;
                return s && s.note && s.note.noteDetailMap
                    && Object.keys(s.note.noteDetailMap).length > 0;
            }""",
            timeout=15.0,
            desc="note.noteDetailMap",
            raise_on_timeout=True,
        )

        # Extract note detail
        for _attempt in range(3):
            result = self._page.evaluate("""() => {
                if (window.__INITIAL_STATE__ &&
                    window.__INITIAL_STATE__.note &&
                    window.__INITIAL_STATE__.note.noteDetailMap) {
                    return JSON.parse(JSON.stringify(
                        window.__INITIAL_STATE__.note.noteDetailMap
                    ));
                }
                return null;
            }""")

            if result:
                # Find the note in the map
                if note_id in result:
                    return result[note_id]
                # Try first key if note_id not found
                if result:
                    first_key = next(iter(result))
                    return result[first_key]

            time.sleep(0.5)

        raise DataFetchError(f"Failed to extract note detail for {note_id}")

    # ===== User Profile =====

    def get_user_info(self, user_id: str) -> dict:
        """Get user profile by navigating to their profile page."""
        url = f"https://www.xiaohongshu.com/user/profile/{user_id}"

        logger.info("Loading user profile: %s", user_id)
        self._goto(
            url,
            timeout=20000,
            wait_min=1.5,
            wait_max=3,
            context=f"loading user profile {user_id}",
        )

        self._wait_for_data(
            """() => {
                const s = window.__INITIAL_STATE__;
                return s && s.user;
            }""",
            timeout=15.0,
            desc="user (profile)",
            raise_on_timeout=True,
        )

        # Vue wraps values in reactive refs like {_value, dep, ...}
        # We need to unwrap _value recursively
        result = self._page.evaluate(
            """() => {
"""
            + UNWRAP_JS
            + """
            if (window.__INITIAL_STATE__ && window.__INITIAL_STATE__.user) {
                const u = window.__INITIAL_STATE__.user;
                const data = {};
                // Extract key fields
                if (u.userPageData) data.userPageData = unwrap(u.userPageData, 0);
                if (u.notes) data.notes = unwrap(u.notes, 0);
                if (u.userInfo) data.userInfo = unwrap(u.userInfo, 0);
                if (Object.keys(data).length === 0) {
                    return unwrap(u, 0);
                }
                return data;
            }
            return null;
        }"""
        )

        if not result:
            logger.warning(
                "Failed to extract user profile from __INITIAL_STATE__ for %s; "
                "returning minimal fallback",
                user_id,
            )
            return {"userInfo": {"userId": user_id}}
        return result

    # ===== Followers / Following =====

    def _get_follow_list(self, user_id: str, tab: str) -> list[dict]:
        """Get a user's followers or following list.

        Args:
            user_id: The user ID to fetch for.
            tab: 'fans' for followers, 'follows' for following.
        """
        url = f"https://www.xiaohongshu.com/user/profile/{user_id}?tab={tab}"
        logger.info("Loading %s list for user %s", tab, user_id)
        self._goto(
            url,
            timeout=20000,
            wait_min=2,
            wait_max=3,
            context=f"loading {tab} list for user {user_id}",
        )
        self._wait_for_data(
            """() => {
                const s = window.__INITIAL_STATE__;
                return s && s.user;
            }""",
            timeout=15.0,
            desc="user (follow list)",
            raise_on_timeout=True,
        )

        result = self._page.evaluate(
            """(tab) => {
"""
            + UNWRAP_JS
            + """
            if (window.__INITIAL_STATE__ && window.__INITIAL_STATE__.user) {
                const u = window.__INITIAL_STATE__.user;
                // Try tab-specific keys, then generic 'fansUsers' / 'followUsers'
                const sources = [
                    u[tab],
                    tab === 'fans' ? u.fansUsers : u.followUsers,
                    tab === 'fans' ? u.fans : u.follows,
                ];
                for (const src of sources) {
                    if (src) {
                        const data = unwrap(src, 0);
                        if (Array.isArray(data)) return data;
                        if (data && typeof data === 'object') {
                            for (const key of ['value', '_value', 'data', 'list', 'users']) {
                                if (Array.isArray(data[key])) return data[key];
                            }
                        }
                    }
                }
            }
            return [];
        }""",
            tab,
        )

        return result if isinstance(result, list) else []

    def get_followers(self, user_id: str) -> list[dict]:
        """Get a user's followers list."""
        return self._get_follow_list(user_id, "fans")

    def get_following(self, user_id: str) -> list[dict]:
        """Get a user's following list."""
        return self._get_follow_list(user_id, "follows")

    # ===== User Posts =====

    def get_user_posts(self, user_id: str) -> list[dict]:
        """Get a user's published notes by navigating to their profile page.

        Extracts note list from __INITIAL_STATE__.user.notes which contains
        the first page of the user's published notes.
        """
        url = f"https://www.xiaohongshu.com/user/profile/{user_id}"

        logger.info("Loading user posts: %s", user_id)
        self._goto(
            url,
            timeout=20000,
            wait_min=1.5,
            wait_max=3,
            context=f"loading user posts for {user_id}",
        )

        self._wait_for_data(
            """() => {
                const s = window.__INITIAL_STATE__;
                if (!s || !s.user) return false;
                const n = s.user.notes;
                if (!n) return false;
                const d = n._rawValue || n._value || n.value || n;
                return Array.isArray(d) || (d && typeof d === 'object');
            }""",
            timeout=15.0,
            desc="user.notes",
            raise_on_timeout=True,
        )

        # Extract notes list from user profile state.
        # Vue wraps arrays in reactive refs, so we unwrap _value recursively.
        result = self._page.evaluate(
            """() => {
"""
            + UNWRAP_JS
            + """
            if (window.__INITIAL_STATE__ && window.__INITIAL_STATE__.user) {
                const u = window.__INITIAL_STATE__.user;
                // notes contains the list of user's published notes
                if (u.notes) {
                    const notes = unwrap(u.notes, 0);
                    // notes may be an array directly or wrapped in an object
                    if (Array.isArray(notes)) return notes;
                    if (notes && typeof notes === 'object') {
                        // Try common keys that hold the actual list
                        for (const key of ['value', '_value', 'data', 'list']) {
                            if (Array.isArray(notes[key])) return notes[key];
                        }
                    }
                    return notes;
                }
            }
            return null;
        }"""
        )

        return result if isinstance(result, list) else []

    # ===== Feed (Explore/Recommend) =====

    def get_feed(self) -> list[dict]:
        """Get recommended feed from the explore page.

        Navigates to xiaohongshu.com/explore and extracts the feed items
        from __INITIAL_STATE__.feed.
        """
        logger.info("Loading explore feed...")
        self._goto(
            "https://www.xiaohongshu.com/explore",
            timeout=20000,
            wait_min=2,
            wait_max=4,
            context="loading explore feed",
        )
        self._wait_for_data(
            """() => {
                const s = window.__INITIAL_STATE__;
                if (!s) return false;
                const f = (s.feed && s.feed.feeds) ||
                          (s.explore && s.explore.feeds) ||
                          (s.homefeed && s.homefeed.feeds);
                if (!f) return false;
                const d = f._rawValue || f._value || f.value || f;
                return Array.isArray(d) || (d && typeof d === 'object');
            }""",
            timeout=15.0,
            desc="feed.feeds",
            raise_on_timeout=True,
        )
        # Extract feed from explore page state
        result = self._page.evaluate(
            """() => {
"""
            + UNWRAP_JS
            + """
            const state = window.__INITIAL_STATE__;
            if (!state) return null;

            // Try multiple paths where feed data might live
            // Path 1: state.feed.feeds (explore page)
            if (state.feed && state.feed.feeds) {
                return unwrap(state.feed.feeds, 0);
            }
            // Path 2: state.explore.feeds
            if (state.explore && state.explore.feeds) {
                return unwrap(state.explore.feeds, 0);
            }
            // Path 3: state.homefeed
            if (state.homefeed && state.homefeed.feeds) {
                return unwrap(state.homefeed.feeds, 0);
            }
            return null;
        }"""
        )

        if not result:
            logger.warning("No feed data found in __INITIAL_STATE__")
            return []

        # result could be an array or an object wrapping an array
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            for key in ("value", "_value", "data", "list"):
                if key in result and isinstance(result[key], list):
                    return result[key]
        return []

    # ===== Topics / Hashtags =====

    def search_topics(self, keyword: str) -> list[dict]:
        """Search for topic/hashtag pages.

        Navigates to the search page with type=topic filter and extracts
        topic results from __INITIAL_STATE__.
        """
        import urllib.parse
        params = urllib.parse.urlencode({
            "keyword": keyword,
            "source": "web_explore_feed",
            "type": "topic",
        })
        url = f"https://www.xiaohongshu.com/search_result?{params}"

        logger.info("Searching topics: %s", keyword)
        self._goto(
            url,
            timeout=20000,
            wait_min=1.5,
            wait_max=3,
            context="loading topics search page",
        )

        self._wait_for_data(
            """() => {
                const s = window.__INITIAL_STATE__;
                if (!s || !s.search) return false;
                const t = s.search.topics || s.search.feeds;
                if (!t) return false;
                const d = t._rawValue || t._value || t.value || t;
                return Array.isArray(d) || (d && typeof d === 'object');
            }""",
            timeout=15.0,
            desc="search.topics",
            raise_on_timeout=True,
        )

        # Extract topic search results
        result = self._page.evaluate(
            """() => {
"""
            + UNWRAP_JS
            + """
            const state = window.__INITIAL_STATE__;
            if (!state || !state.search) return null;

            // Topics may be in search.feeds or search.topics
            const search = state.search;
            if (search.topics) return unwrap(search.topics, 0);
            if (search.feeds) return unwrap(search.feeds, 0);
            return null;
        }"""
        )

        if not result:
            logger.warning("No topic results found")
            return []

        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            for key in ("value", "_value", "data", "list"):
                if key in result and isinstance(result[key], list):
                    return result[key]
        return []

    # ===== Favorites =====

    def get_favorites(self, max_count: int = 50) -> list[dict]:
        """Get current user's favorite (collected) notes.

        Navigates to the user's profile collect tab and extracts notes.
        Scrolls down to load more notes up to max_count.

        Args:
            max_count: Maximum number of favorites to return.
        """
        # First get user_id from self info
        info = self.get_self_info()
        user_id = ""
        if isinstance(info, dict):
            # Try multiple extraction paths — page structure varies
            for path_key in ["userInfo", "basicInfo", "basic_info"]:
                sub = info.get(path_key, {})
                if isinstance(sub, dict):
                    uid = sub.get("userId", "") or sub.get("user_id", "")
                    if uid:
                        user_id = uid
                        break

            # Also check userPageData.basicInfo
            if not user_id:
                user_page = info.get("userPageData", {})
                if isinstance(user_page, dict):
                    basic = user_page.get("basicInfo", user_page.get("basic_info", {}))
                    if isinstance(basic, dict):
                        user_id = basic.get("userId", "") or basic.get("user_id", "")

            # Last resort: top-level keys
            if not user_id:
                user_id = (info.get("userId", "") or info.get("user_id", "") or
                           info.get("id", ""))

        if not user_id:
            raise LoginError("Cannot determine user_id. Make sure you are logged in.")

        # Navigate to user's collect tab
        url = f"https://www.xiaohongshu.com/user/profile/{user_id}?tab=collect"
        logger.info("Loading favorites: %s", url)
        self._goto(
            url,
            timeout=20000,
            wait_min=2,
            wait_max=3,
            context="loading favorites page",
        )
        self._wait_for_data(
            """() => {
                const s = window.__INITIAL_STATE__;
                return s && s.user;
            }""",
            timeout=15.0,
            desc="user (favorites)",
            raise_on_timeout=True,
        )

        all_notes = []
        seen_ids = set()

        # Extract notes and scroll to load more
        page_limit = max(1, (max_count + 9) // 10)
        for _scroll_attempt in range(page_limit):
            notes = self._page.evaluate(
                """() => {
"""
                + UNWRAP_JS
                + """
                if (window.__INITIAL_STATE__ && window.__INITIAL_STATE__.user) {
                    const u = window.__INITIAL_STATE__.user;
                    // Collect tab data is in user.collect or user.collectNotes
                    const sources = [u.collect, u.collectNotes, u.notes];
                    for (const src of sources) {
                        if (src) {
                            const data = unwrap(src, 0);
                            if (Array.isArray(data)) return data;
                            if (data && typeof data === 'object') {
                                for (const key of ['value', '_value', 'data', 'list']) {
                                    if (Array.isArray(data[key])) return data[key];
                                }
                            }
                        }
                    }
                }

                // Fallback: try to scrape visible note cards from DOM
                const cards = document.querySelectorAll(
                    'section.note-item, [class*="note-item"], a[href*="/explore/"]'
                );
                if (cards.length > 0) {
                    return Array.from(cards).map(card => {
                        const link = card.querySelector('a') || card;
                        const href = link.getAttribute('href') || '';
                        const title = card.querySelector('[class*="title"]');
                        const author = card.querySelector('[class*="author"]');
                        const likes = card.querySelector('[class*="like"]');
                        return {
                            noteId: (href.match(/\\/explore\\/([a-zA-Z0-9]+)/) || [])[1] || '',
                            displayTitle: title ? title.textContent.trim() : '',
                            user: { nickname: author ? author.textContent.trim() : '' },
                            interactInfo: { likedCount: likes ? likes.textContent.trim() : '' },
                            xsecToken: (href.match(/xsec_token=([^&]+)/) || [])[1] || '',
                        };
                    });
                }
                return [];
            }"""
            )

            if isinstance(notes, list):
                for note in notes:
                    if not isinstance(note, dict):
                        continue
                    nid = note.get("noteId", note.get("note_id", note.get("id", "")))
                    if nid and nid not in seen_ids:
                        seen_ids.add(nid)
                        all_notes.append(note)

            if len(all_notes) >= max_count:
                break

            # Scroll down to load more notes
            self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            self._human_wait(1.5, 2.5)

        return all_notes[:max_count]

    # ===== Self Info =====

    def get_self_info(self) -> dict:
        """Get current user's profile info.

        Strategy:
        1. Navigate to homepage and extract user_id from __INITIAL_STATE__
           (checks multiple paths: user.currentUser, sidebar, etc.)
        2. If user_id found, navigate to profile page for full info
        3. Falls back to whatever data is available from homepage
        """
        self._goto(
            "https://www.xiaohongshu.com",
            timeout=15000,
            wait_min=1,
            wait_max=2,
            context="loading homepage for self info",
        )
        self._wait_for_data(
            """() => {
                const s = window.__INITIAL_STATE__;
                if (!s) return false;
                if (s.user && s.user.userPageData) return true;
                if (s.user && s.user.currentUser) return true;
                if (s.user && s.user.userInfo) return true;
                if (s.sidebar && s.sidebar.user) return true;
                return false;
            }""",
            timeout=10.0,
            desc="user info",
            raise_on_timeout=True,
        )

        # Try to extract current user info from homepage state.
        # The data might be in different paths depending on page version.
        result = self._page.evaluate(
            """() => {
"""
            + UNWRAP_JS
            + """
            const state = window.__INITIAL_STATE__;
            if (!state) return null;

            // Try multiple paths where current user info might live
            const paths = [
                state.user && state.user.userPageData,
                state.user && state.user.currentUser,
                state.user && state.user.info,
                state.user && state.user.loginUser,
                state.sidebar && state.sidebar.user,
                state.app && state.app.user,
            ];

            for (const p of paths) {
                if (p) {
                    const data = unwrap(p, 0);
                    if (data && typeof data === 'object' && Object.keys(data).length > 0) {
                        return data;
                    }
                }
            }

            // Last resort: dump the entire user object for inspection
            if (state.user) {
                return unwrap(state.user, 0);
            }
            return null;
        }"""
        )

        if not result:
            return {}

        # Try to find user_id so we can navigate to profile for full info.
        user_id = None
        if isinstance(result, dict):
            # Check multiple paths where userId might live
            for sub_key in ["userInfo", "basicInfo", "basic_info"]:
                sub = result.get(sub_key, {})
                if isinstance(sub, dict):
                    uid = sub.get("userId", "") or sub.get("user_id", "")
                    if uid:
                        user_id = uid
                        break
            if not user_id:
                user_id = (result.get("userId", "") or result.get("user_id", "") or
                           result.get("id", ""))

        # If we got a user_id, fetch their full profile page for richer data
        if user_id:
            try:
                full_info = self.get_user_info(user_id)
                if full_info and isinstance(full_info, dict):
                    return full_info
            except Exception:
                pass

        return result

    # ===== Comments via scroll =====

    def get_note_comments(self, note_id: str, xsec_token: str = "",
                          max_comments: int = 50) -> list[dict]:
        """Load comments by scrolling the note page.

        Must be called after get_note_detail on the same note.
        """
        # Ensure we are on the expected note page before extracting comments.
        expected_path = f"/explore/{note_id}"
        if expected_path not in self._page.url:
            self._navigate_to_note(note_id, xsec_token)

        # First get initial comments from __INITIAL_STATE__
        comments_data = self._page.evaluate("""(noteId) => {
            if (window.__INITIAL_STATE__ &&
                window.__INITIAL_STATE__.note &&
                window.__INITIAL_STATE__.note.noteDetailMap) {
                const map = window.__INITIAL_STATE__.note.noteDetailMap;
                const detail = map[noteId] || map[Object.keys(map)[0]];
                if (detail) {
                    const comments = detail.comments;
                    if (comments !== undefined && comments !== null) {
                        return JSON.parse(JSON.stringify(comments));
                    }
                }
            }
            return null;
        }""", note_id)

        if not comments_data:
            return []
        if isinstance(comments_data, dict):
            for key in ("comments", "list", "data", "items"):
                value = comments_data.get(key)
                if isinstance(value, list):
                    comments_data = value
                    break
        if not isinstance(comments_data, list):
            return []
        if max_comments <= 0:
            return comments_data
        return comments_data[:max_comments]

    # ===== Like / Unlike =====

    def like_note(self, note_id: str, xsec_token: str = "") -> bool:
        """Like a note by clicking the like button."""
        return self._toggle_interact(note_id, xsec_token, "like", True)

    def unlike_note(self, note_id: str, xsec_token: str = "") -> bool:
        """Unlike a note by clicking the like button."""
        return self._toggle_interact(note_id, xsec_token, "like", False)

    # ===== Favorite / Unfavorite =====

    def favorite_note(self, note_id: str, xsec_token: str = "") -> bool:
        """Favorite a note by clicking the collect button."""
        return self._toggle_interact(note_id, xsec_token, "favorite", True)

    def unfavorite_note(self, note_id: str, xsec_token: str = "") -> bool:
        """Unfavorite a note by clicking the collect button."""
        return self._toggle_interact(note_id, xsec_token, "favorite", False)

    # ===== Comment =====

    def post_comment(self, note_id: str, content: str, xsec_token: str = "") -> bool:
        """Post a comment on a note by typing into the comment input."""
        self._navigate_to_note(note_id, xsec_token)
        before_count = self._get_comment_count(note_id)

        # Find and click comment input
        try:
            input_el = self._page.query_selector('#content-textarea')
            if not input_el:
                input_el = self._page.query_selector('[contenteditable="true"]')
            if not input_el:
                raise RuntimeError("Comment input not found")

            input_el.click()
            self._human_wait(0.3, 0.8)
            input_el.type(content, delay=random.randint(50, 150))
            self._human_wait(0.5, 1.0)

            # Click submit button
            submit = self._page.query_selector('.submit.active') or \
                     self._page.query_selector('button.submit')
            if submit:
                submit.click()
                self._human_wait(1, 2)
                if self._verify_comment_submitted(note_id, before_count):
                    logger.info("Comment posted on %s", note_id)
                    return True

            # Try pressing Enter as fallback
            self._page.keyboard.press("Enter")
            self._human_wait(1, 2)
            if self._verify_comment_submitted(note_id, before_count):
                logger.info("Comment posted (Enter) on %s", note_id)
                return True
            logger.warning("Comment submit attempted but no success signal found for %s", note_id)
            return False

        except Exception as e:
            logger.error("Failed to post comment: %s", e)
            return False

    def _get_comment_count(self, note_id: str) -> int:
        """Best-effort extraction of current comment count for a note."""
        try:
            count = self._page.evaluate("""(noteId) => {
                const s = window.__INITIAL_STATE__;
                if (!s || !s.note || !s.note.noteDetailMap) return -1;
                const map = s.note.noteDetailMap;
                const detail = map[noteId] || map[Object.keys(map)[0]];
                if (!detail) return -1;
                const note = detail.note || {};
                const interactInfo = note.interactInfo || {};
                const interactInfoSnake = note.interact_info || {};
                const candidates = [
                    interactInfo.commentCount,
                    interactInfoSnake.comment_count,
                ];
                for (const c of candidates) {
                    if (typeof c === 'number') return c;
                    if (typeof c === 'string' && c.trim()) {
                        const v = Number(c);
                        if (!Number.isNaN(v)) return v;
                    }
                }
                const comments = detail.comments;
                if (Array.isArray(comments)) return comments.length;
                if (comments && Array.isArray(comments.list)) return comments.list.length;
                if (comments && Array.isArray(comments.comments)) return comments.comments.length;
                return -1;
            }""", note_id)
            if isinstance(count, (int, float)):
                return int(count)
        except Exception:
            pass
        return -1

    def _verify_comment_submitted(self, note_id: str, before_count: int) -> bool:
        """Check whether comment submit succeeded."""
        # A visible success toast/message is the strongest signal.
        try:
            body_text = (self._page.text_content("body") or "").strip()
        except Exception:
            body_text = ""
        success_tokens = ("评论成功", "发布成功", "发送成功", "success")
        if body_text and any(token in body_text.lower() for token in success_tokens):
            return True

        # Fallback: comment count increased.
        after_count = self._get_comment_count(note_id)
        if before_count >= 0 and after_count >= 0 and after_count > before_count:
            return True
        return False

    # ===== Publish Note =====

    def publish_note(
        self,
        title: str,
        image_paths: list[str],
        content: str = "",
        return_detail: bool = False,
    ) -> bool | dict[str, str | bool]:
        """Publish a new image note on Xiaohongshu.

        Navigates to the creator publish page, uploads images via
        the file input, fills in title and description, then clicks
        the publish button.

        Args:
            title: Note title (required).
            image_paths: List of absolute paths to image files.
            content: Optional note body/description text.
        """
        import os

        # Validate image paths exist
        for path in image_paths:
            if not os.path.isfile(path):
                raise FileNotFoundError(f"Image not found: {path}")

        publish_url = "https://creator.xiaohongshu.com/publish/publish"
        logger.info("Navigating to publish page: %s", publish_url)
        self._goto(
            publish_url,
            timeout=30000,
            wait_min=3,
            wait_max=5,
            context="loading creator publish page",
        )

        # Creator publishing may require an additional login session.
        for frame in self._page.frames:
            frame_url = (frame.url or "").lower()
            if "creator.xiaohongshu.com/login" in frame_url:
                raise LoginError(
                    "Creator platform login required for publishing. "
                    "Please log in at https://creator.xiaohongshu.com first."
                )

        # Step 1: Upload images via file input.
        # The creator page has a hidden <input type="file"> for image upload.
        file_input_selectors = [
            'input[type="file"]',
            '[type="file"]',
            'input[accept*="image"]',
            'input[accept*="image/*"]',
            '.upload-input',
            '#upload-input',
        ]

        def _find_file_input():
            # Search main page first
            for sel in file_input_selectors:
                el = self._page.query_selector(sel)
                if el:
                    return el
            # Then search all iframes (creator console occasionally renders in frame)
            for frame in self._page.frames:
                for sel in file_input_selectors:
                    try:
                        el = frame.query_selector(sel)
                    except Exception:
                        el = None
                    if el:
                        return el
            return None

        file_input = None
        # Wait/retry loop for dynamic mount timing
        for _ in range(6):
            try:
                self._page.wait_for_selector(
                    'input[type="file"]',
                    state="attached",
                    timeout=2500,
                )
            except Exception:
                pass
            file_input = _find_file_input()
            if file_input:
                break
            self._human_wait(0.5, 1.2)

        if not file_input:
            # Try clicking the upload area to reveal a file input
            upload_area_selectors = [
                '.upload-wrapper',
                '[class*="upload"]',
                '.drag-over',
                '.creator-upload-entry',
            ]
            for sel in upload_area_selectors:
                area = self._page.query_selector(sel)
                if area:
                    area.click()
                    self._human_wait(1, 2)
                    break

            # Try again to find file input
            for _ in range(4):
                file_input = _find_file_input()
                if file_input:
                    break
                self._human_wait(0.5, 1.2)

        if not file_input:
            raise RuntimeError(
                "Cannot find file upload input on the publish page. "
                "The page structure may have changed."
            )

        # Upload all images at once
        logger.info("Uploading %d images...", len(image_paths))
        file_input.set_input_files(image_paths)
        # Wait for upload to complete
        self._human_wait(3, 5)

        # Wait a bit more for thumbnails to appear (large files may take longer)
        for _ in range(10):
            thumbnails = self._page.query_selector_all(
                'img[class*="thumbnail"], img[class*="preview"], '
                '.image-item, [class*="upload-item"]'
            )
            if len(thumbnails) >= len(image_paths):
                break
            self._human_wait(1, 2)

        logger.info("Images uploaded, filling in details...")

        # Step 2: Fill in title.
        title_selectors = [
            '#title-textarea',
            '[placeholder*="标题"]',
            'input[class*="title"]',
            'textarea[class*="title"]',
            '.title-input textarea',
            '.title-input input',
        ]

        for sel in title_selectors:
            title_el = self._page.query_selector(sel)
            if title_el:
                title_el.click()
                self._human_wait(0.3, 0.5)
                title_el.fill(title)
                logger.info("Title filled: %s", title)
                break
        else:
            logger.warning("Title input not found, trying keyboard input")
            # Some pages may focus the title field automatically
            self._page.keyboard.type(title)

        self._human_wait(0.5, 1)

        # Step 3: Fill in content/description (optional).
        if content:
            content_selectors = [
                '#post-textarea',
                '[placeholder*="正文"]',
                '[placeholder*="描述"]',
                '[placeholder*="添加描述"]',
                'textarea[class*="content"]',
                'textarea[class*="desc"]',
                '.ql-editor',
                '[contenteditable="true"]',
            ]

            for sel in content_selectors:
                content_el = self._page.query_selector(sel)
                if content_el:
                    content_el.click()
                    self._human_wait(0.3, 0.5)
                    # contenteditable divs need keyboard input, not fill
                    tag = content_el.evaluate("el => el.tagName.toLowerCase()")
                    if tag in ("textarea", "input"):
                        content_el.fill(content)
                    else:
                        self._page.keyboard.type(content)
                    logger.info("Content filled (%d chars)", len(content))
                    break
            else:
                logger.warning("Content input not found")

        self._human_wait(1, 2)

        # Step 4: Click publish button.
        publish_selectors = [
            'button:has-text("发布")',
            '.publishBtn',
            '[class*="publish-btn"]',
            'button[class*="submit"]',
            'button.css-k01sra',
        ]

        for sel in publish_selectors:
            publish_btn = self._page.query_selector(sel)
            if publish_btn:
                logger.info("Clicking publish button...")
                publish_btn.click()
                self._human_wait(3, 5)

                page_text = self._page.text_content("body") or ""
                current_url = self._page.url
                note_id = (
                    self._extract_note_id_from_url(current_url)
                    or self._extract_note_id_from_page()
                )
                if self._is_publish_success(page_text, current_url, note_id):
                    logger.info("Note published successfully. Current URL: %s", current_url)
                    if return_detail:
                        return {"success": True, "note_id": note_id, "url": current_url}
                    return True

                logger.warning(
                    "Publish button clicked but no success signal found. Current URL: %s",
                    current_url,
                )
                if return_detail:
                    return {"success": False, "note_id": note_id, "url": current_url}
                return False

        raise RuntimeError(
            "Cannot find publish button on the page. "
            "The page structure may have changed."
        )

    # ===== Delete Note =====

    def delete_note(self, note_id: str, xsec_token: str = "") -> bool:
        """Delete a note by opening menu actions on the note page."""
        self._navigate_to_note(note_id, xsec_token)

        more_selectors = [
            'button:has-text("...")',
            '[aria-label*="更多"]',
            '[class*="more"]',
            '.more',
            '.reds-icon.more',
        ]
        menu_opened = False
        for sel in more_selectors:
            el = self._page.query_selector(sel)
            if not el:
                continue
            try:
                el.click()
                self._human_wait(0.8, 1.5)
                menu_opened = True
                break
            except Exception:
                continue

        if not menu_opened:
            logger.error("Failed to open note menu for delete action")
            return False

        delete_selectors = [
            'button:has-text("删除")',
            '[role="menuitem"]:has-text("删除")',
            'text=删除',
            '[class*="delete"]',
        ]
        delete_clicked = False
        for sel in delete_selectors:
            el = self._page.query_selector(sel)
            if not el:
                continue
            try:
                el.click()
                self._human_wait(0.8, 1.5)
                delete_clicked = True
                break
            except Exception:
                continue

        if not delete_clicked:
            logger.error("Delete menu item not found/clickable for note %s", note_id)
            return False

        confirm_selectors = [
            'button:has-text("确定")',
            'button:has-text("确认")',
            'button:has-text("删除")',
            '.reds-button-primary',
        ]
        for sel in confirm_selectors:
            el = self._page.query_selector(sel)
            if not el:
                continue
            try:
                el.click()
                self._human_wait(2, 3)
                break
            except Exception:
                continue

        page_text = (self._page.text_content("body") or "").strip()
        if "删除成功" in page_text or "已删除" in page_text:
            return True

        if "删除失败" in page_text or "操作失败" in page_text:
            return False

        if self._verify_note_deleted(note_id, xsec_token):
            return True

        return False

    def _verify_note_deleted(self, note_id: str, xsec_token: str = "") -> bool:
        """Re-open the note page and verify the note is no longer available."""
        url = f"https://www.xiaohongshu.com/explore/{note_id}"
        if xsec_token:
            url += f"?xsec_token={xsec_token}&xsec_source=pc_feed"
        try:
            self._goto(
                url,
                timeout=20000,
                wait_min=1,
                wait_max=2,
                context=f"verifying deletion for note {note_id}",
            )
            exists = self._page.evaluate("""(targetNoteId) => {
                const s = window.__INITIAL_STATE__;
                if (!s || !s.note || !s.note.noteDetailMap) return false;
                const map = s.note.noteDetailMap;
                if (!map || Object.keys(map).length === 0) return false;
                if (map[targetNoteId]) return true;
                const first = map[Object.keys(map)[0]];
                return !!(first && first.note);
            }""", note_id)
            if exists:
                return False
            body_text = (self._page.text_content("body") or "").strip()
            unavailable_tokens = ("内容不存在", "已删除", "not found", "removed")
            normalized = body_text.lower()
            return any(token in normalized for token in unavailable_tokens)
        except Exception:
            return False

    # ===== Internal: Interaction helpers =====

    def _navigate_to_note(self, note_id: str, xsec_token: str = ""):
        """Navigate to note detail page."""
        url = f"https://www.xiaohongshu.com/explore/{note_id}"
        if xsec_token:
            url += f"?xsec_token={xsec_token}&xsec_source=pc_feed"
        self._goto(
            url,
            timeout=20000,
            wait_min=1.5,
            wait_max=3,
            context=f"loading note {note_id}",
        )
        self._wait_for_data(
            """() => {
                const s = window.__INITIAL_STATE__;
                return s && s.note && s.note.noteDetailMap
                    && Object.keys(s.note.noteDetailMap).length > 0;
            }""",
            timeout=15.0,
            desc="note (navigate)",
            raise_on_timeout=True,
        )

    def _get_interact_state(self, note_id: str) -> dict:
        """Get like/favorite state from __INITIAL_STATE__."""
        result = self._page.evaluate("""(noteId) => {
            if (window.__INITIAL_STATE__ &&
                window.__INITIAL_STATE__.note &&
                window.__INITIAL_STATE__.note.noteDetailMap) {
                const map = window.__INITIAL_STATE__.note.noteDetailMap;
                const detail = map[noteId] || map[Object.keys(map)[0]];
                if (detail && detail.note && detail.note.interactInfo) {
                    return detail.note.interactInfo;
                }
            }
            return null;
        }""", note_id)
        return result or {}

    def _toggle_interact(self, note_id: str, xsec_token: str,
                         action: str, target_state: bool) -> bool:
        """Toggle like/favorite by clicking the button.

        Args:
            action: "like" or "favorite"
            target_state: True to like/favorite, False to unlike/unfavorite
        """
        SELECTORS = {
            "like": ".interact-container .left .like-lottie",
            "favorite": ".interact-container .left .reds-icon.collect-icon",
        }
        STATE_KEYS = {
            "like": "liked",
            "favorite": "collected",
        }

        self._navigate_to_note(note_id, xsec_token)

        # Check current state
        state = self._get_interact_state(note_id)
        current = state.get(STATE_KEYS[action], False)
        if current == target_state:
            action_name = action if target_state else f"un{action}"
            logger.info("Note %s already %sd, skipping", note_id, action_name)
            return True

        # Click the button
        selector = SELECTORS[action]
        el = self._page.query_selector(selector)
        if not el:
            logger.error("%s button not found: %s", action, selector)
            return False

        el.click()
        self._human_wait(2, 3)

        # Verify
        state = self._get_interact_state(note_id)
        new_state = state.get(STATE_KEYS[action], False)
        if new_state == target_state:
            logger.info("Note %s %s success", note_id, action)
            return True

        # Retry once
        logger.warning("State didn't change, retrying click...")
        el = self._page.query_selector(selector)
        if el:
            el.click()
            self._human_wait(2, 3)

        state = self._get_interact_state(note_id)
        final_state = state.get(STATE_KEYS[action], False)
        if final_state == target_state:
            logger.info("Note %s %s success after retry", note_id, action)
            return True

        logger.error("Failed to %s note %s after retry", action, note_id)
        return False

    # ===== Internal helpers =====

    def _goto(
        self,
        url: str,
        *,
        timeout: int = 20000,
        wait_until: str = "domcontentloaded",
        wait_min: float = 1.0,
        wait_max: float = 2.0,
        context: str = "loading page",
    ):
        """Navigate to URL and fail fast if redirected to risk-control pages."""
        self._page.goto(url, wait_until=wait_until, timeout=timeout)
        self._human_wait(wait_min, wait_max)
        self._raise_if_blocked(context, include_body=True)

    def _detect_block_reason(self, include_body: bool = False) -> str:
        """Detect whether current page is a security verification/risk-control page."""
        if not self._page:
            return ""

        page_url = getattr(self._page, "url", "") or ""
        url = page_url.lower()
        url_markers = (
            "website-login/captcha",
            "verifyuuid=",
            "verifytype=",
        )
        if any(marker in url for marker in url_markers):
            return f"redirected to verification URL: {page_url}"

        if not include_body:
            return ""

        try:
            body_text = (self._page.text_content("body") or "").lower()
        except Exception:
            return ""

        body_markers = (
            "security verification",
            "scan with logged-in",
            "qr code expires",
            "requests too frequent",
            "try again later",
            "请求过于频繁",
            "请求太频繁",
            "安全验证",
            "扫码验证",
        )
        for marker in body_markers:
            if marker in body_text:
                return f"verification page content detected ({marker})"
        return ""

    def _raise_if_blocked(self, context: str, include_body: bool = False):
        """Raise LoginError when the page is blocked by risk control."""
        reason = self._detect_block_reason(include_body=include_body)
        if reason:
            raise LoginError(f"Blocked by security verification while {context}: {reason}")

    def _wait_for_initial_state(self, timeout: float = 10.0):
        """Wait for window.__INITIAL_STATE__ to be populated."""
        start = time.time()
        while time.time() - start < timeout:
            try:
                result = self._page.evaluate(
                    "() => window.__INITIAL_STATE__ !== undefined"
                )
                if result:
                    return
                self._raise_if_blocked("waiting for initial state", include_body=False)
            except LoginError:
                raise
            except Exception:
                pass
            time.sleep(0.3)
        logger.warning("__INITIAL_STATE__ not found after %.1fs", timeout)

    def _wait_for_data(
        self,
        js_condition: str,
        timeout: float = 15.0,
        desc: str = "data",
        raise_on_timeout: bool = False,
    ):
        """Wait for a JS condition (returning truthy) to be met.

        Used to wait for Vue to asynchronously populate __INITIAL_STATE__
        sub-keys after initial page load.
        """
        start = time.time()
        while time.time() - start < timeout:
            try:
                if self._page.evaluate(js_condition):
                    logger.debug("%s ready after %.1fs", desc, time.time() - start)
                    return
                self._raise_if_blocked(f"waiting for {desc}", include_body=False)
            except LoginError:
                raise
            except Exception:
                pass
            time.sleep(0.5)
        self._raise_if_blocked(f"waiting for {desc}", include_body=True)
        logger.warning("%s not ready after %.1fs", desc, timeout)
        if raise_on_timeout:
            raise DataFetchError(f"{desc} not ready after {timeout:.1f}s")

    def _human_wait(self, min_sec: float = 1.0, max_sec: float = 3.0):
        """Wait a random human-like interval."""
        time.sleep(random.uniform(min_sec, max_sec))
