"""Tapes (the music app): rip songs from links, search the library, manage
playlists (the app calls them tapes), and podcasts."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from mcp.server.mcpserver import MCPServer

from ..backend import AppError
from ..common import FETCH, IDEMPOTENT, READ, WRITE, Deps, capped, current_user, duration

LIST_LIMIT = 80


def _track(t: dict) -> str:
    parts = [f"track #{t['id']} {t['title']}"]
    if t.get("artist"):
        parts.append(t["artist"])
    if t.get("album"):
        parts.append(t["album"])
    parts.append(duration(t.get("duration")))
    return " · ".join(parts)


def _job(j: dict) -> str:
    line = f"job #{j['id']} {j['status']}"
    if j["status"] == "running" and j.get("progress"):
        line += f" {j['progress']}%"
    if j.get("track"):
        line += " · " + _track(j["track"])
    else:
        line += f" · {j['url']}"
    if j.get("outcome"):
        line += f" · {j['outcome']}"
    if j.get("message"):
        line += f" · {j['message']}"
    return line


def register(server: MCPServer, deps: Deps) -> None:
    async def call(method: str, path: str, **kw):
        return await deps.backend.request("tapes", method, path, user=current_user(), **kw)

    @server.tool(
        name="tapes_download",
        annotations=FETCH,
        description=(
            "Rip audio from a link (YouTube, SoundCloud, Bandcamp and other sites yt-dlp "
            "supports) into the music library. A playlist link queues every track and "
            "creates a matching playlist. Tapes can't search the web; you need the link "
            "itself, so find it with your own search tool first if you have one. Rips run "
            "in the background; check them with tapes_list_downloads. Duplicates of songs "
            "already in the library are detected and skipped."
        ),
    )
    async def tapes_download(
        url: Annotated[str, Field(description="Full https:// link to a song, album or playlist.")],
    ) -> str:
        res = await call("POST", "/api/downloads", json={"url": url})
        ids = ", ".join(f"#{i}" for i in res.get("job_ids", []))
        msg = f"Queued {res['queued']} download(s) ({ids})."
        if res.get("playlist"):
            msg += f" They'll be collected in a new playlist '{res['playlist']}'."
        return msg

    @server.tool(
        name="tapes_list_downloads",
        annotations=READ,
        description="Downloads in progress and recently finished or failed, with reasons for failures.",
    )
    async def tapes_list_downloads() -> str:
        jobs = await call("GET", "/api/downloads")
        if not jobs:
            return "No downloads queued or recently finished."
        return capped([_job(j) for j in jobs], LIST_LIMIT, "Dismiss finished ones to see more.")

    @server.tool(
        name="tapes_dismiss_download",
        annotations=IDEMPOTENT,
        description="Hide a finished or failed download from the list. Doesn't touch any song.",
    )
    async def tapes_dismiss_download(job_id: int) -> str:
        await call("DELETE", f"/api/downloads/{job_id}")
        return f"Dismissed job #{job_id}."

    @server.tool(
        name="tapes_search_tracks",
        annotations=READ,
        description=(
            "Find songs in the library. Every word must appear in the title, artist or "
            "album (case-insensitive). Returns track ids for use with playlist tools."
        ),
    )
    async def tapes_search_tracks(
        query: Annotated[str, Field(min_length=1)],
        limit: Annotated[int, Field(ge=1, le=100)] = 25,
    ) -> str:
        tracks = await call("GET", "/api/tracks", params={"q": query, "limit": limit})
        if not tracks:
            return f"No songs match '{query}'."
        return "\n".join(_track(t) for t in tracks)

    @server.tool(
        name="tapes_list_playlists",
        annotations=READ,
        description=(
            "The shelf: built-in lists (key 'all', 'singles', 'tidy') and the user's own "
            "playlists (numeric keys), with song counts."
        ),
    )
    async def tapes_list_playlists() -> str:
        shelf = await call("GET", "/api/playlists")
        lines = []
        for s in shelf:
            if s["kind"] == "browse":
                continue  # albums/artists: search instead
            label = "playlist" if s["kind"] == "user" else "built-in"
            lines.append(f"{label} key={s['key']} · {s['name']} · {s['count']} songs")
        return "\n".join(lines)

    @server.tool(
        name="tapes_get_playlist",
        annotations=READ,
        description="Songs on a playlist, in order. `key` is from tapes_list_playlists.",
    )
    async def tapes_get_playlist(
        key: Annotated[str, Field(description="A playlist id like '12', or 'all' / 'singles' / 'tidy'.")],
    ) -> str:
        # One past the cap tells us whether there's more, without fetching it all.
        tracks = await call("GET", f"/api/playlists/{key.strip()}/tracks",
                            params={"limit": LIST_LIMIT + 1})
        if not tracks:
            return "That playlist is empty."
        lines = []
        for t in tracks[:LIST_LIMIT]:
            line = _track(t)
            if t.get("issues"):
                line += f" · needs: {', '.join(t['issues'])}"
            lines.append(line)
        if len(tracks) > LIST_LIMIT:
            lines.append(f"… more after the first {LIST_LIMIT}. Use tapes_search_tracks to find specific songs.")
        return "\n".join(lines)

    @server.tool(name="tapes_create_playlist", annotations=WRITE,
                 description="Make a new, empty playlist. Returns its id.")
    async def tapes_create_playlist(name: Annotated[str, Field(min_length=1, max_length=120)]) -> str:
        p = await call("POST", "/api/playlists", json={"name": name})
        return f"Created playlist key={p['key']} '{p['name']}'."

    @server.tool(name="tapes_rename_playlist", annotations=IDEMPOTENT,
                 description="Rename one of the user's playlists.")
    async def tapes_rename_playlist(
        playlist_id: int, name: Annotated[str, Field(min_length=1, max_length=120)]
    ) -> str:
        p = await call("PATCH", f"/api/playlists/{playlist_id}", json={"name": name})
        return f"Renamed playlist {p['key']} to '{p['name']}'."

    @server.tool(
        name="tapes_add_to_playlist",
        annotations=IDEMPOTENT,
        description="Add songs to the end of a playlist. Songs already on it are skipped.",
    )
    async def tapes_add_to_playlist(
        playlist_id: int,
        track_ids: Annotated[list[int], Field(min_length=1, max_length=200)],
    ) -> str:
        added = skipped = 0
        name = ""
        problems = []
        for tid in track_ids:
            try:
                res = await call("POST", f"/api/playlists/{playlist_id}/tracks", json={"track_id": tid})
            except AppError as e:
                if not added and not skipped and "isn't in the library" not in str(e):
                    raise  # e.g. no such playlist: nothing to report per song
                problems.append(f"#{tid}: {e}")
                continue
            name = res.get("tape", name)
            added += res.get("added", False)
            skipped += not res.get("added", False)
        msg = f"Added {added} song(s) to '{name or playlist_id}'"
        msg += f", {skipped} already on it." if skipped else "."
        if problems:
            msg += " Not added: " + "; ".join(problems)
        return msg

    @server.tool(name="tapes_remove_from_playlist", annotations=IDEMPOTENT,
                 description="Take a song off a playlist. The song stays in the library.")
    async def tapes_remove_from_playlist(playlist_id: int, track_id: int) -> str:
        await call("DELETE", f"/api/playlists/{playlist_id}/tracks/{track_id}")
        return f"Removed track #{track_id} from playlist {playlist_id}."

    @server.tool(
        name="tapes_update_track",
        annotations=IDEMPOTENT,
        description=(
            "Fix a song's title, artist, album or track number, for everyone (the library "
            "is shared). Only the fields you pass change; pass '-' to clear artist or album."
        ),
    )
    async def tapes_update_track(
        track_id: int,
        title: str = "",
        artist: str = "",
        album: str = "",
        track_no: Annotated[int, Field(ge=0, description="0 to leave as is.")] = 0,
    ) -> str:
        changes: dict = {}
        if title:
            changes["title"] = title
        for key, value in (("artist", artist), ("album", album)):
            if value:
                changes[key] = "" if value == "-" else value
        if track_no:
            changes["track_no"] = track_no
        if not changes:
            raise AppError("Say what to change: title, artist, album or track_no.")
        t = await call("PATCH", f"/api/tracks/{track_id}", json=changes)
        return "Updated " + _track(t)

    @server.tool(name="tapes_restore_track", annotations=IDEMPOTENT,
                 description="Bring back a song deleted in the music app (admins only, within 30 days).")
    async def tapes_restore_track(track_id: int) -> str:
        t = await call("POST", f"/api/tracks/{track_id}/restore")
        return "Restored " + _track(t)

    @server.tool(
        name="tapes_list_podcasts",
        annotations=READ,
        description="Podcast shows the user follows, with episode and unplayed counts.",
    )
    async def tapes_list_podcasts() -> str:
        data = await call("GET", "/api/podcast/shows")
        lines = [
            f"show #{s['id']} {s['title']} · {s['count']} episodes, {s['unplayed']} unplayed"
            for s in data["shows"]
        ]
        if data.get("loose_count"):
            lines.append(f"(plus {data['loose_count']} loose episodes not in any show)")
        return "\n".join(lines) or "No podcasts yet."

    @server.tool(
        name="tapes_add_podcast",
        annotations=FETCH,
        description=(
            "Follow a podcast from its RSS feed link or a YouTube channel/playlist link; a "
            "single YouTube video is added as a loose episode."
        ),
    )
    async def tapes_add_podcast(url: Annotated[str, Field(description="https:// feed or channel link.")]) -> str:
        res = await call("POST", "/api/podcast/add", json={"url": url})
        if res.get("loose"):
            return f"Added {res.get('added', 0)} loose episode(s)."
        if res.get("assigned"):
            return f"Added {res.get('added', 0)} episode(s) to show #{res['assigned']['id']} {res['assigned']['title']}."
        verb = "Now following" if res.get("created") else "Already following; refreshed"
        return f"{verb} show #{res['id']} {res['title']} ({res.get('added', 0)} new episodes)."

    @server.tool(name="tapes_list_episodes", annotations=READ,
                 description="Episodes of one show, newest first.")
    async def tapes_list_episodes(show_id: int) -> str:
        data = await call("GET", f"/api/podcast/shows/{show_id}/episodes")
        lines = []
        for e in data["episodes"]:
            state = "played" if e["played"] else ("in progress" if e["position"] else "unplayed")
            when = (e.get("published_at") or "")[:10]
            lines.append(
                f"episode #{e['id']} {e['title']} · {when or 'undated'} · {duration(e['duration'])} · {state}"
            )
        head = f"show #{data['show']['id']} {data['show']['title']}"
        return head + "\n" + (capped(lines, LIST_LIMIT, "Older episodes omitted.") or "No episodes.")
