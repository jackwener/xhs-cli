"""CLI entry point for xhs-cli.

Usage:
    xhs login
    xhs status
    xhs search "咖啡"
    xhs search "咖啡" --json
    xhs read <note_id> [--xsec-token <token>] [--json]
    xhs user <user_id> [--json]
    xhs user-posts <user_id> [--json]
    xhs feed [--json]
    xhs topics <keyword> [--json]
"""

from __future__ import annotations

import json
import logging
import sys

import click
from rich.console import Console
from rich.table import Table

from .auth import clear_cookies, get_cookie_string, load_xsec_token, qrcode_login, save_token_cache
from .exceptions import XhsError
from . import __version__

console = Console()


def _setup_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _parse_cookie_dict(cookie: str) -> dict[str, str]:
    """Parse cookie string into dict."""
    result = {}
    for item in cookie.split(";"):
        item = item.strip()
        if "=" in item:
            k, v = item.split("=", 1)
            result[k.strip()] = v.strip()
    return result


def _get_client():
    """Create an authenticated browser-based XhsClient."""
    from .client import XhsClient

    cookie = get_cookie_string()
    if not cookie:
        console.print("[red]Not logged in. Run `xhs login` first.[/red]")
        sys.exit(1)

    cookie_dict = _parse_cookie_dict(cookie)
    client = XhsClient(cookie_dict)
    client.start()
    return client


@click.group()
@click.version_option(version=__version__, prog_name="xhs-cli")
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
def cli(verbose: bool):
    """xhs — Xiaohongshu CLI tool 🍰"""
    _setup_logging(verbose)


# ===== Login =====

@cli.command()
@click.option("--qrcode", is_flag=True, help="Force QR code login")
@click.option("--cookie", "cookie_str", default=None, help="Manually provide cookie string")
def login(qrcode: bool, cookie_str: str | None):
    """Login to Xiaohongshu."""
    if cookie_str:
        from .auth import save_cookies
        save_cookies(cookie_str)
        console.print("[green]✅ Cookie saved![/green]")
        return

    if not qrcode:
        cookie = get_cookie_string()
        if cookie:
            # Validate by actually loading the page and checking user data
            cookie_dict = _parse_cookie_dict(cookie)
            if _verify_cookies(cookie_dict):
                console.print("[green]✅ Logged in (from browser cookies)[/green]")
                return
            else:
                console.print("[yellow]⚠️  Found cookies but session is invalid/expired.[/yellow]")
                # Clear stale cookies so they don't get reused
                clear_cookies()

    # QR code login
    console.print("[dim]Falling back to QR code login...[/dim]")
    try:
        cookie = qrcode_login()
        console.print("[green]✅ Login successful! Cookie saved.[/green]")
    except Exception as e:
        console.print(f"[red]❌ Login failed: {e}[/red]")
        sys.exit(1)


def _verify_cookies(cookie_dict: dict[str, str]) -> bool:
    """Quick check: load homepage with cookies and see if we get a valid user.

    Returns True if the session is valid (has a real user), False otherwise.
    """
    from .client import XhsClient

    try:
        client = XhsClient(cookie_dict)
        client.start()
        info = client.get_self_info()
        client.close()

        # Check if we got a real nickname (not "Unknown")
        basic = info.get("basicInfo", info.get("basic_info", {}))
        user_page = info.get("userPageData", {})
        if user_page:
            basic = user_page.get("basicInfo", user_page.get("basic_info", basic))
        if not basic or not isinstance(basic, dict):
            basic = info

        nickname = basic.get("nickname", basic.get("nick_name", ""))
        return bool(nickname and nickname != "Unknown")
    except Exception:
        return False


@cli.command()
def logout():
    """Logout and clear saved cookies."""
    removed = clear_cookies()
    if removed:
        console.print(f"[green]✅ Logged out. Removed: {', '.join(removed)}[/green]")
    else:
        console.print("[yellow]No saved cookies to clear.[/yellow]")


@cli.command()
def status():
    """Check login status (lightweight, no browser needed)."""
    from .auth import COOKIE_FILE

    cookie = get_cookie_string()
    if not cookie:
        console.print("[red]❌ Not logged in. Run `xhs login` to authenticate.[/red]")
        sys.exit(1)

    # Check if cookie file exists (saved session)
    source = "saved cookies" if COOKIE_FILE.exists() else "browser cookies"
    console.print(f"[green]✅ Logged in[/green] [dim](from {source})[/dim]")
    console.print("[dim]Run `xhs whoami` to see your profile details.[/dim]")


@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON")
def whoami(as_json: bool):
    """Show current user's profile info."""
    try:
        client = _get_client()
        info = client.get_self_info()

        if as_json:
            click.echo(json.dumps(info, indent=2, ensure_ascii=False))
            client.close()
            return

        # Extract user details from various data paths
        basic = info.get("basicInfo", info.get("basic_info", {}))
        user_page = info.get("userPageData", {})
        if user_page:
            basic = user_page.get("basicInfo", user_page.get("basic_info", basic))

        user_info = info.get("userInfo", {})
        if user_info and not basic:
            basic = user_info

        if not basic or not isinstance(basic, dict):
            basic = info

        nickname = basic.get("nickname", basic.get("nick_name", "Unknown"))

        if nickname == "Unknown":
            console.print("[red]❌ Session expired or invalid. Run `xhs login` to re-authenticate.[/red]")
            client.close()
            sys.exit(1)

        red_id = basic.get("redId", basic.get("red_id", ""))
        ip_location = basic.get("ipLocation", basic.get("ip_location", ""))
        desc = basic.get("desc", basic.get("description", ""))
        gender = basic.get("gender", "")
        user_id = basic.get("userId", basic.get("user_id", basic.get("id", "")))

        # Interaction stats (fans, following, note count)
        interactions = (user_page.get("interactions", []) or
                        info.get("interactions", []))

        stats = {}
        if isinstance(interactions, list):
            for item in interactions:
                if isinstance(item, dict):
                    name = item.get("name", item.get("type", ""))
                    count = item.get("count", item.get("value", ""))
                    if name and count is not None:
                        stats[name] = str(count)

        table = Table(title=f"👤 {nickname}")
        table.add_column("Field", style="cyan")
        table.add_column("Value", style="green")
        if red_id:
            table.add_row("Red ID", red_id)
        if user_id:
            table.add_row("User ID", str(user_id))
        if desc:
            table.add_row("Bio", desc[:80])
        if ip_location:
            table.add_row("IP Location", ip_location)
        if gender:
            gender_label = {"0": "🚹", "1": "🚺", 0: "🚹", 1: "🚺"}.get(gender, str(gender))
            table.add_row("Gender", gender_label)

        # Show stats from interactions
        stat_labels = {
            "fans": "Followers", "粉丝": "Followers",
            "follows": "Following", "关注": "Following",
            "interaction": "Likes & Favs", "获赞与收藏": "Likes & Favs",
        }
        for key, label in stat_labels.items():
            if key in stats:
                table.add_row(label, stats[key])

        console.print(table)
        client.close()

    except SystemExit:
        raise
    except Exception as e:
        console.print(f"[red]❌ Failed to get profile: {e}[/red]")
        sys.exit(1)


# ===== Search =====

@cli.command()
@click.argument("keyword")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON")
def search(keyword: str, as_json: bool):
    """Search notes by keyword."""
    try:
        client = _get_client()
        feeds = client.search_notes(keyword)

        # Cache note_id -> xsec_token mapping so subsequent commands
        # (note, like, favorite, comment) can auto-resolve tokens.
        token_map = {}
        for item in feeds:
            nid = item.get("id", "")
            xsec = item.get("xsec_token", item.get("xsecToken", ""))
            if nid and xsec:
                token_map[nid] = xsec
        if token_map:
            save_token_cache(token_map)

        if as_json:
            click.echo(json.dumps(feeds, indent=2, ensure_ascii=False))
            client.close()
            return

        if not feeds:
            console.print("[yellow]No results found.[/yellow]")
            client.close()
            return

        table = Table(title=f"Search: {keyword} ({len(feeds)} results)")
        table.add_column("#", style="dim", width=3)
        table.add_column("Title", style="cyan", max_width=40)
        table.add_column("Author", style="green", max_width=15)
        table.add_column("Likes", style="red", justify="right")
        table.add_column("Note ID", style="dim")

        for i, item in enumerate(feeds, 1):
            card = item.get("note_card", item.get("noteCard", {}))
            user = card.get("user", {})
            interact = card.get("interact_info", card.get("interactInfo", {}))
            note_id = item.get("id", "")
            table.add_row(
                str(i),
                card.get("display_title", card.get("displayTitle", ""))[:40],
                user.get("nickname", user.get("nick_name", ""))[:15],
                str(interact.get("liked_count", interact.get("likedCount", "0"))),
                note_id,
            )

        console.print(table)
        # xsec_token is cached automatically, no need to show it in the table
        console.print(f"\n[dim]Use `xhs read <Note ID>` to view details (xsec_token auto-resolved)[/dim]")
        client.close()

    except Exception as e:
        console.print(f"[red]❌ Search failed: {e}[/red]")
        sys.exit(1)


# ===== Read Note Detail =====

@cli.command()
@click.argument("note_id")
@click.option("--xsec-token", default="", help="xsec_token from search results")
@click.option("--comments", is_flag=True, help="Include comments")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON")
def read(note_id: str, xsec_token: str, comments: bool, as_json: bool):
    """Get note detail by ID."""
    # Auto-resolve xsec_token from cache if not provided
    if not xsec_token:
        xsec_token = load_xsec_token(note_id)
    try:
        client = _get_client()
        detail = client.get_note_detail(note_id, xsec_token)

        output = {"note": detail.get("note", detail)}

        if comments:
            output["comments"] = client.get_note_comments(note_id, xsec_token)

        if as_json:
            click.echo(json.dumps(output, indent=2, ensure_ascii=False))
            client.close()
            return

        note_data = output["note"]
        interact = note_data.get("interactInfo", note_data.get("interact_info", {}))
        user = note_data.get("user", {})
        console.print(f"\n[bold cyan]{note_data.get('title', 'Untitled')}[/bold cyan]")
        console.print(f"[dim]by {user.get('nickname', '')} · {note_data.get('ipLocation', note_data.get('ip_location', ''))}[/dim]")
        console.print(f"\n{note_data.get('desc', '')}")
        console.print(f"\n❤️  {interact.get('likedCount', interact.get('liked_count', 0))}  "
                       f"⭐ {interact.get('collectedCount', interact.get('collected_count', 0))}  "
                       f"💬 {interact.get('commentCount', interact.get('comment_count', 0))}  "
                       f"🔗 {interact.get('shareCount', interact.get('share_count', 0))}")

        if "comments" in output and output["comments"]:
            clist = output["comments"]
            if isinstance(clist, dict):
                clist = clist.get("comments", [])
            console.print(f"\n[bold]Comments ({len(clist)}):[/bold]")
            for c in clist[:20]:
                u = c.get("userInfo", c.get("user_info", {}))
                console.print(f"  [green]{u.get('nickname', '')}[/green]: {c.get('content', '')}")

        client.close()

    except Exception as e:
        console.print(f"[red]❌ Failed to get note: {e}[/red]")
        sys.exit(1)


# ===== User =====

@cli.command()
@click.argument("user_id")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON")
def user(user_id: str, as_json: bool):
    """Get user profile."""
    try:
        client = _get_client()
        info = client.get_user_info(user_id)

        if as_json:
            click.echo(json.dumps(info, indent=2, ensure_ascii=False))
        else:
            console.print_json(json.dumps(info, ensure_ascii=False))

        client.close()

    except Exception as e:
        console.print(f"[red]❌ Failed to get user: {e}[/red]")
        sys.exit(1)


# ===== User Posts =====

@cli.command("user-posts")
@click.argument("user_id")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON")
def user_posts(user_id: str, as_json: bool):
    """List a user's published notes."""
    try:
        client = _get_client()
        posts = client.get_user_posts(user_id)

        if as_json:
            click.echo(json.dumps(posts, indent=2, ensure_ascii=False))
            client.close()
            return

        if not posts:
            console.print("[yellow]No posts found.[/yellow]")
            client.close()
            return

        table = Table(title=f"User {user_id} Posts ({len(posts)} notes)")
        table.add_column("#", style="dim", width=3)
        table.add_column("Title", style="cyan", max_width=40)
        table.add_column("Likes", style="red", justify="right")
        table.add_column("Type", style="magenta", width=6)
        table.add_column("Note ID", style="dim")

        # Cache xsec_tokens from user posts for later use
        token_map = {}
        for i, item in enumerate(posts, 1):
            # Handle different data shapes from __INITIAL_STATE__
            note_card = item.get("note_card", item.get("noteCard", item))
            interact = note_card.get("interact_info", note_card.get("interactInfo", {}))
            note_id = item.get("id", item.get("note_id", item.get("noteId", "")))
            xsec = item.get("xsec_token", item.get("xsecToken", ""))
            note_type = note_card.get("type", "")
            # "normal" = image post, "video" = video post
            type_label = "📹" if note_type == "video" else "📷"

            if note_id and xsec:
                token_map[note_id] = xsec

            table.add_row(
                str(i),
                note_card.get("display_title", note_card.get("displayTitle", ""))[:40],
                str(interact.get("liked_count", interact.get("likedCount", "0"))),
                type_label,
                note_id,
            )

        if token_map:
            save_token_cache(token_map)

        console.print(table)
        console.print(f"\n[dim]Use `xhs read <Note ID>` to view details[/dim]")
        client.close()

    except Exception as e:
        console.print(f"[red]❌ Failed to get user posts: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.argument("user_id")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON")
def followers(user_id: str, as_json: bool):
    """List a user's followers."""
    try:
        client = _get_client()
        users = client.get_followers(user_id)

        if as_json:
            click.echo(json.dumps(users, indent=2, ensure_ascii=False))
            client.close()
            return

        if not users:
            console.print("[yellow]No followers found.[/yellow]")
            client.close()
            return

        table = Table(title=f"Followers ({len(users)})")
        table.add_column("#", style="dim", width=4)
        table.add_column("Nickname", style="bold", max_width=20)
        table.add_column("Red ID", style="dim")
        table.add_column("User ID", style="dim")

        for i, u in enumerate(users, 1):
            nickname = u.get("nickname", u.get("nick_name", ""))
            red_id = u.get("redId", u.get("red_id", ""))
            uid = u.get("userId", u.get("user_id", u.get("id", "")))
            table.add_row(str(i), nickname, red_id, uid)

        console.print(table)
        client.close()

    except Exception as e:
        console.print(f"[red]❌ Failed to get followers: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.argument("user_id")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON")
def following(user_id: str, as_json: bool):
    """List a user's following."""
    try:
        client = _get_client()
        users = client.get_following(user_id)

        if as_json:
            click.echo(json.dumps(users, indent=2, ensure_ascii=False))
            client.close()
            return

        if not users:
            console.print("[yellow]No following found.[/yellow]")
            client.close()
            return

        table = Table(title=f"Following ({len(users)})")
        table.add_column("#", style="dim", width=4)
        table.add_column("Nickname", style="bold", max_width=20)
        table.add_column("Red ID", style="dim")
        table.add_column("User ID", style="dim")

        for i, u in enumerate(users, 1):
            nickname = u.get("nickname", u.get("nick_name", ""))
            red_id = u.get("redId", u.get("red_id", ""))
            uid = u.get("userId", u.get("user_id", u.get("id", "")))
            table.add_row(str(i), nickname, red_id, uid)

        console.print(table)
        client.close()

    except Exception as e:
        console.print(f"[red]❌ Failed to get following: {e}[/red]")
        sys.exit(1)


# ===== Feed =====

@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON")
def feed(as_json: bool):
    """Get recommended feed from explore page."""
    try:
        client = _get_client()
        feeds = client.get_feed()

        # Cache xsec_tokens from feed for later use
        token_map = {}
        for item in feeds:
            nid = item.get("id", "")
            xsec = item.get("xsec_token", item.get("xsecToken", ""))
            if nid and xsec:
                token_map[nid] = xsec
        if token_map:
            save_token_cache(token_map)

        if as_json:
            click.echo(json.dumps(feeds, indent=2, ensure_ascii=False))
            client.close()
            return

        if not feeds:
            console.print("[yellow]No feed items found.[/yellow]")
            client.close()
            return

        table = Table(title=f"Explore Feed ({len(feeds)} items)")
        table.add_column("#", style="dim", width=3)
        table.add_column("Title", style="cyan", max_width=40)
        table.add_column("Author", style="green", max_width=15)
        table.add_column("Likes", style="red", justify="right")
        table.add_column("Note ID", style="dim")

        for i, item in enumerate(feeds, 1):
            card = item.get("note_card", item.get("noteCard", {}))
            u = card.get("user", {})
            interact = card.get("interact_info", card.get("interactInfo", {}))
            note_id = item.get("id", "")
            table.add_row(
                str(i),
                card.get("display_title", card.get("displayTitle", ""))[:40],
                u.get("nickname", u.get("nick_name", ""))[:15],
                str(interact.get("liked_count", interact.get("likedCount", "0"))),
                note_id,
            )

        console.print(table)
        console.print(f"\n[dim]Use `xhs read <Note ID>` to view details[/dim]")
        client.close()

    except Exception as e:
        console.print(f"[red]❌ Failed to get feed: {e}[/red]")
        sys.exit(1)


# ===== Topics =====

@cli.command()
@click.argument("keyword")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON")
def topics(keyword: str, as_json: bool):
    """Search for topics/hashtags."""
    try:
        client = _get_client()
        results = client.search_topics(keyword)

        if as_json:
            click.echo(json.dumps(results, indent=2, ensure_ascii=False))
            client.close()
            return

        if not results:
            console.print("[yellow]No topics found.[/yellow]")
            client.close()
            return

        table = Table(title=f"Topics: {keyword} ({len(results)} results)")
        table.add_column("#", style="dim", width=3)
        table.add_column("Topic", style="cyan", max_width=30)
        table.add_column("View Count", style="yellow", justify="right")
        table.add_column("Note Count", style="green", justify="right")
        table.add_column("ID", style="dim")

        for i, item in enumerate(results, 1):
            # Topics may have different structure than notes
            name = (item.get("name", "") or
                    item.get("title", "") or
                    item.get("display_title", item.get("displayTitle", "")))
            topic_id = item.get("id", item.get("topicId", item.get("topic_id", "")))
            view_count = item.get("view_count", item.get("viewCount",
                         item.get("view_num", item.get("viewNum", ""))))
            note_count = item.get("note_count", item.get("noteCount",
                         item.get("note_num", item.get("noteNum", ""))))
            table.add_row(
                str(i),
                str(name)[:30],
                str(view_count) if view_count else "-",
                str(note_count) if note_count else "-",
                str(topic_id),
            )

        console.print(table)
        client.close()

    except Exception as e:
        console.print(f"[red]❌ Failed to search topics: {e}[/red]")
        sys.exit(1)


# ===== Interactions =====

@cli.command()
@click.argument("note_id")
@click.option("--xsec-token", default="", help="xsec_token from search results")
@click.option("--undo", is_flag=True, help="Unlike instead of like")
def like(note_id: str, xsec_token: str, undo: bool):
    """Like or unlike a note."""
    # Auto-resolve xsec_token from cache if not provided
    if not xsec_token:
        xsec_token = load_xsec_token(note_id)
    try:
        client = _get_client()
        if undo:
            client.unlike_note(note_id, xsec_token)
            console.print(f"[green]✅ Unliked {note_id}[/green]")
        else:
            client.like_note(note_id, xsec_token)
            console.print(f"[green]✅ Liked {note_id}[/green]")
        client.close()
    except Exception as e:
        console.print(f"[red]❌ Like failed: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.argument("note_id")
@click.option("--xsec-token", default="", help="xsec_token from search results")
def unlike(note_id: str, xsec_token: str):
    """Unlike a note."""
    if not xsec_token:
        xsec_token = load_xsec_token(note_id)
    try:
        client = _get_client()
        client.unlike_note(note_id, xsec_token)
        console.print(f"[green]✅ Unliked {note_id}[/green]")
        client.close()
    except Exception as e:
        console.print(f"[red]❌ Unlike failed: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.argument("note_id")
@click.option("--xsec-token", default="", help="xsec_token from search results")
@click.option("--undo", is_flag=True, help="Unfavorite instead of favorite")
def favorite(note_id: str, xsec_token: str, undo: bool):
    """Favorite or unfavorite a note."""
    # Auto-resolve xsec_token from cache if not provided
    if not xsec_token:
        xsec_token = load_xsec_token(note_id)
    try:
        client = _get_client()
        if undo:
            client.unfavorite_note(note_id, xsec_token)
            console.print(f"[green]✅ Unfavorited {note_id}[/green]")
        else:
            client.favorite_note(note_id, xsec_token)
            console.print(f"[green]✅ Favorited {note_id}[/green]")
        client.close()
    except Exception as e:
        console.print(f"[red]❌ Favorite failed: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.argument("note_id")
@click.option("--xsec-token", default="", help="xsec_token from search results")
def unfavorite(note_id: str, xsec_token: str):
    """Unfavorite (uncollect) a note."""
    if not xsec_token:
        xsec_token = load_xsec_token(note_id)
    try:
        client = _get_client()
        client.unfavorite_note(note_id, xsec_token)
        console.print(f"[green]✅ Unfavorited {note_id}[/green]")
        client.close()
    except Exception as e:
        console.print(f"[red]❌ Unfavorite failed: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.argument("note_id")
@click.argument("content")
@click.option("--xsec-token", default="", help="xsec_token from search results")
def comment(note_id: str, content: str, xsec_token: str):
    """Post a comment on a note."""
    # Auto-resolve xsec_token from cache if not provided
    if not xsec_token:
        xsec_token = load_xsec_token(note_id)
    try:
        client = _get_client()
        ok = client.post_comment(note_id, content, xsec_token)
        if ok:
            console.print(f"[green]✅ Comment posted on {note_id}[/green]")
        else:
            console.print(f"[red]❌ Comment failed[/red]")
        client.close()
    except Exception as e:
        console.print(f"[red]❌ Comment failed: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.option("--max", "max_count", default=50, help="Maximum number of favorites to fetch")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON")
def favorites(max_count: int, as_json: bool):
    """List your collected (favorited) notes."""
    try:
        client = _get_client()
        notes = client.get_favorites(max_count=max_count)

        if as_json:
            click.echo(json.dumps(notes, indent=2, ensure_ascii=False))
            client.close()
            return

        if not notes:
            console.print("[yellow]No favorites found.[/yellow]")
            client.close()
            return

        # Cache xsec_tokens for later use
        token_map = {}
        for note in notes:
            nid = note.get("noteId", note.get("note_id", note.get("id", "")))
            token = note.get("xsecToken", note.get("xsec_token", ""))
            if nid and token:
                token_map[nid] = token
        if token_map:
            save_token_cache(token_map)

        table = Table(title=f"⭐ Favorites ({len(notes)} items)")
        table.add_column("#", style="dim", width=4)
        table.add_column("Title", style="bold", max_width=40)
        table.add_column("Author", max_width=16)
        table.add_column("Likes", justify="right", width=6)
        table.add_column("Note ID", style="dim")

        for i, note in enumerate(notes, 1):
            nid = note.get("noteId", note.get("note_id", note.get("id", "")))
            title = note.get("displayTitle", note.get("display_title", note.get("title", "")))
            # Extract author name
            user = note.get("user", note.get("noteUser", {}))
            author = user.get("nickname", user.get("nick_name", "")) if isinstance(user, dict) else ""
            # Extract likes
            interact = note.get("interactInfo", note.get("interact_info", {}))
            likes = interact.get("likedCount", interact.get("liked_count", "")) if isinstance(interact, dict) else ""
            # Note type indicator
            note_type = note.get("type", note.get("noteType", ""))
            type_icon = "📹" if note_type in ("video", "1") else "📷"

            table.add_row(str(i), f"{type_icon} {title}", author, str(likes), nid)

        console.print(table)
        console.print("\nUse `xhs read <Note ID>` to view details")
        client.close()

    except Exception as e:
        console.print(f"[red]❌ Failed to get favorites: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.argument("title")
@click.option("--image", "images", multiple=True, required=True,
              type=click.Path(exists=True), help="Image file to upload (can be repeated)")
@click.option("--content", default="", help="Note body/description text")
def post(title: str, images: tuple[str, ...], content: str):
    """Publish a new image note.

    \b
    Examples:
        xhs post "今日咖啡" --image coffee.jpg
        xhs post "旅行日记" --image d1.jpg --image d2.jpg --content "好开心！"
    """
    import os

    # Resolve to absolute paths
    abs_paths = [os.path.abspath(p) for p in images]

    console.print(f"[dim]Publishing note: {title}[/dim]")
    console.print(f"[dim]Images: {', '.join(os.path.basename(p) for p in abs_paths)}[/dim]")
    if content:
        console.print(f"[dim]Content: {content[:50]}{'...' if len(content) > 50 else ''}[/dim]")

    try:
        client = _get_client()
        ok = client.publish_note(title=title, image_paths=abs_paths, content=content)
        if ok:
            console.print("[green]✅ Note published successfully![/green]")
        else:
            console.print("[red]❌ Publish may have failed. Check your profile.[/red]")
        client.close()
    except FileNotFoundError as e:
        console.print(f"[red]❌ {e}[/red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]❌ Publish failed: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    cli()

