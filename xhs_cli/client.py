"""Xiaohongshu browser-based client using camoufox.

All operations navigate to pages and extract data from window.__INITIAL_STATE__,
exactly like a real user browsing. This avoids API-level risk control (300011).
"""

from __future__ import annotations

import json
import logging
import random
import time
from typing import Any

logger = logging.getLogger(__name__)


class XhsClient:
    """Camoufox-based Xiaohongshu client.

    Navigates to real pages and extracts data from __INITIAL_STATE__,
    indistinguishable from a real user browsing.
    """

    def __init__(self, cookie_dict: dict[str, str]):
        self._cookie_dict = cookie_dict
        self._camoufox_ctx = None
        self._browser = None
        self._page = None

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
        self._page.goto(
            "https://www.xiaohongshu.com",
            wait_until="domcontentloaded",
            timeout=20000,
        )
        self._human_wait(1, 2)
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
        self._page.goto(url, wait_until="domcontentloaded", timeout=20000)
        self._human_wait(1, 2)

        # Wait for __INITIAL_STATE__ to be populated
        self._wait_for_initial_state()

        # Extract search feeds
        result = self._page.evaluate("""() => {
            if (window.__INITIAL_STATE__ &&
                window.__INITIAL_STATE__.search &&
                window.__INITIAL_STATE__.search.feeds) {
                const feeds = window.__INITIAL_STATE__.search.feeds;
                const feedsData = feeds.value !== undefined ? feeds.value : feeds._value;
                if (feedsData) {
                    return JSON.parse(JSON.stringify(feedsData));
                }
            }
            return null;
        }""")

        if not result:
            logger.warning("No search results found in __INITIAL_STATE__")
            return []

        return result

    # ===== Note Detail =====

    def get_note_detail(self, note_id: str, xsec_token: str = "") -> dict:
        """Get note detail by navigating to the explore page.

        Extracts from __INITIAL_STATE__.note.noteDetailMap.
        """
        url = f"https://www.xiaohongshu.com/explore/{note_id}"
        if xsec_token:
            url += f"?xsec_token={xsec_token}&xsec_source=pc_feed"

        logger.info("Loading note: %s", note_id)
        self._page.goto(url, wait_until="domcontentloaded", timeout=20000)
        self._human_wait(1.5, 3)

        self._wait_for_initial_state()

        # Extract note detail
        for attempt in range(3):
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

        raise RuntimeError(f"Failed to extract note detail for {note_id}")

    # ===== User Profile =====

    def get_user_info(self, user_id: str) -> dict:
        """Get user profile by navigating to their profile page."""
        url = f"https://www.xiaohongshu.com/user/profile/{user_id}"

        logger.info("Loading user profile: %s", user_id)
        self._page.goto(url, wait_until="domcontentloaded", timeout=20000)
        self._human_wait(1.5, 3)

        self._wait_for_initial_state()

        # Vue wraps values in reactive refs like {_value, dep, ...}
        # We need to unwrap _value recursively
        result = self._page.evaluate("""() => {
            function unwrap(obj, depth) {
                if (depth > 6 || obj === null || obj === undefined) return obj;
                if (typeof obj !== 'object') return obj;

                // Unwrap Vue ref: if has _value, use that
                if ('_value' in obj && 'dep' in obj) {
                    return unwrap(obj._value, depth + 1);
                }
                // Also handle .value pattern
                if ('value' in obj && 'dep' in obj) {
                    return unwrap(obj.value, depth + 1);
                }

                if (Array.isArray(obj)) {
                    return obj.map(item => unwrap(item, depth + 1));
                }

                const result = {};
                const seen = new Set();
                for (const key of Object.keys(obj)) {
                    if (key === 'dep' || key === '__v_raw' || key === '__v_skip'
                        || key.startsWith('__')) continue;
                    if (seen.has(key)) continue;
                    seen.add(key);
                    try {
                        result[key] = unwrap(obj[key], depth + 1);
                    } catch(e) {}
                }
                return result;
            }

            if (window.__INITIAL_STATE__ && window.__INITIAL_STATE__.user) {
                const u = window.__INITIAL_STATE__.user;
                const data = {};
                // Extract key fields
                if (u.userPageData) data.userPageData = unwrap(u.userPageData, 0);
                if (u.notes) data.notes = unwrap(u.notes, 0);
                if (u.userInfo) data.userInfo = unwrap(u.userInfo, 0);
                return data;
            }
            return null;
        }""")

        if not result:
            raise RuntimeError(f"Failed to extract user profile for {user_id}")
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
        self._page.goto(url, wait_until="domcontentloaded", timeout=20000)
        self._human_wait(2, 3)
        self._wait_for_initial_state()

        result = self._page.evaluate("""(tab) => {
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
        }""", tab)

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
        self._page.goto(url, wait_until="domcontentloaded", timeout=20000)
        self._human_wait(1.5, 3)

        self._wait_for_initial_state()

        # Extract notes list from user profile state.
        # Vue wraps arrays in reactive refs, so we unwrap _value recursively.
        result = self._page.evaluate("""() => {
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
        }""")

        return result if isinstance(result, list) else []

    # ===== Feed (Explore/Recommend) =====

    def get_feed(self) -> list[dict]:
        """Get recommended feed from the explore page.

        Navigates to xiaohongshu.com/explore and extracts the feed items
        from __INITIAL_STATE__.feed.
        """
        logger.info("Loading explore feed...")
        self._page.goto(
            "https://www.xiaohongshu.com/explore",
            wait_until="domcontentloaded",
            timeout=20000,
        )
        self._human_wait(2, 4)

        self._wait_for_initial_state()

        # Extract feed from explore page state
        result = self._page.evaluate("""() => {
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
        }""")

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
        self._page.goto(url, wait_until="domcontentloaded", timeout=20000)
        self._human_wait(1.5, 3)

        self._wait_for_initial_state()

        # Extract topic search results
        result = self._page.evaluate("""() => {
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

            const state = window.__INITIAL_STATE__;
            if (!state || !state.search) return null;

            // Topics may be in search.feeds or search.topics
            const search = state.search;
            if (search.topics) return unwrap(search.topics, 0);
            if (search.feeds) return unwrap(search.feeds, 0);
            return null;
        }""")

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
            basic = info.get("basicInfo", info.get("basic_info", {}))
            user_page = info.get("userPageData", {})
            if user_page:
                basic = user_page.get("basicInfo", user_page.get("basic_info", basic))
            if not basic or not isinstance(basic, dict):
                basic = info
            user_id = (basic.get("userId", "") or basic.get("user_id", "") or
                       basic.get("id", ""))

        if not user_id:
            raise RuntimeError("Cannot determine user_id. Make sure you are logged in.")

        # Navigate to user's collect tab
        url = f"https://www.xiaohongshu.com/user/profile/{user_id}?tab=collect"
        logger.info("Loading favorites: %s", url)
        self._page.goto(url, wait_until="domcontentloaded", timeout=20000)
        self._human_wait(2, 3)
        self._wait_for_initial_state()

        all_notes = []
        seen_ids = set()

        # Extract notes and scroll to load more
        for scroll_attempt in range(max(1, max_count // 10)):
            notes = self._page.evaluate("""() => {
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
                const cards = document.querySelectorAll('section.note-item, [class*="note-item"], a[href*="/explore/"]');
                if (cards.length > 0) {
                    return Array.from(cards).map(card => {
                        const link = card.querySelector('a') || card;
                        const href = link.getAttribute('href') || '';
                        const title = card.querySelector('[class*="title"]');
                        const author = card.querySelector('[class*="author"]');
                        const likes = card.querySelector('[class*="like"]');
                        return {
                            noteId: (href.match(/\\/explore\\/([a-f0-9]+)/) || [])[1] || '',
                            displayTitle: title ? title.textContent.trim() : '',
                            user: { nickname: author ? author.textContent.trim() : '' },
                            interactInfo: { likedCount: likes ? likes.textContent.trim() : '' },
                            xsecToken: (href.match(/xsec_token=([^&]+)/) || [])[1] || '',
                        };
                    });
                }
                return [];
            }""")

            if isinstance(notes, list):
                for note in notes:
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
        self._page.goto(
            "https://www.xiaohongshu.com",
            wait_until="domcontentloaded",
            timeout=15000,
        )
        self._human_wait(1, 2)
        self._wait_for_initial_state()

        # Try to extract current user info from homepage state.
        # The data might be in different paths depending on page version.
        result = self._page.evaluate("""() => {
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
        }""")

        if not result:
            return {}

        # Try to find user_id so we can navigate to profile for full info.
        # user_id might be in basicInfo.userId, userId, user_id, id, etc.
        user_id = None
        if isinstance(result, dict):
            basic = result.get("basicInfo", result.get("basic_info", result))
            user_id = (basic.get("userId", "") or basic.get("user_id", "") or
                       basic.get("id", "") or result.get("userId", "") or
                       result.get("user_id", "") or result.get("id", ""))

        # If we got a user_id, fetch their full profile page for richer data
        if user_id:
            try:
                full_info = self.get_user_info(user_id)
                if full_info:
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
        # First get initial comments from __INITIAL_STATE__
        comments_data = self._page.evaluate("""() => {
            if (window.__INITIAL_STATE__ &&
                window.__INITIAL_STATE__.note &&
                window.__INITIAL_STATE__.note.noteDetailMap) {
                const map = window.__INITIAL_STATE__.note.noteDetailMap;
                const keys = Object.keys(map);
                if (keys.length > 0) {
                    const comments = map[keys[0]].comments;
                    if (comments) {
                        return JSON.parse(JSON.stringify(comments));
                    }
                }
            }
            return null;
        }""")

        return comments_data if comments_data else []

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
                logger.info("Comment posted on %s", note_id)
                return True

            # Try pressing Enter as fallback
            self._page.keyboard.press("Enter")
            self._human_wait(1, 2)
            logger.info("Comment posted (Enter) on %s", note_id)
            return True

        except Exception as e:
            logger.error("Failed to post comment: %s", e)
            return False

    # ===== Publish Note =====

    def publish_note(self, title: str, image_paths: list[str],
                     content: str = "") -> bool:
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
        self._page.goto(publish_url, wait_until="domcontentloaded", timeout=30000)
        self._human_wait(3, 5)

        # Step 1: Upload images via file input.
        # The creator page has a hidden <input type="file"> for image upload.
        file_input_selectors = [
            'input[type="file"]',
            'input[accept*="image"]',
            '.upload-input',
            '#upload-input',
        ]

        file_input = None
        for sel in file_input_selectors:
            file_input = self._page.query_selector(sel)
            if file_input:
                break

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
            for sel in file_input_selectors:
                file_input = self._page.query_selector(sel)
                if file_input:
                    break

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

                # Check for success indicators
                # After publishing, the page usually redirects or shows a success message
                success_indicators = [
                    '发布成功',
                    'publish-success',
                    '已发布',
                ]
                page_text = self._page.text_content("body") or ""
                for indicator in success_indicators:
                    if indicator in page_text:
                        logger.info("Note published successfully!")
                        return True

                # If URL changed away from publish page, likely success
                current_url = self._page.url
                if "publish" not in current_url:
                    logger.info("Redirected to %s — likely published!", current_url)
                    return True

                logger.info("Publish button clicked, assuming success")
                return True

        raise RuntimeError(
            "Cannot find publish button on the page. "
            "The page structure may have changed."
        )

    # ===== Internal: Interaction helpers =====

    def _navigate_to_note(self, note_id: str, xsec_token: str = ""):
        """Navigate to note detail page."""
        url = f"https://www.xiaohongshu.com/explore/{note_id}"
        if xsec_token:
            url += f"?xsec_token={xsec_token}&xsec_source=pc_feed"
        self._page.goto(url, wait_until="domcontentloaded", timeout=20000)
        self._human_wait(1.5, 3)
        self._wait_for_initial_state()

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

        return True

    # ===== Internal helpers =====

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
            except Exception:
                pass
            time.sleep(0.3)
        logger.warning("__INITIAL_STATE__ not found after %.1fs", timeout)

    def _human_wait(self, min_sec: float = 1.0, max_sec: float = 3.0):
        """Wait a random human-like interval."""
        time.sleep(random.uniform(min_sec, max_sec))

