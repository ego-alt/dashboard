"""Tool behaviour that lives in the server rather than the apps: merging
partial updates, keeping lengths, tag maths, looping single-item endpoints."""

import httpx
import pytest

from mcp import Client

from homehub_mcp.server import build_server

from .conftest import body

pytestmark = pytest.mark.anyio


async def run(config, backend, tool, **args):
    async with Client(build_server(config, backend)) as client:
        result = await client.call_tool(tool, args)
    return result.is_error, result.content[0].text


@pytest.fixture
def entry(fake):
    """One stored entry (#7) with a moment, and a PUT that applies the body."""
    state = {
        "id": 7, "name": "Dinner", "start_time": "2026-10-16 19:30", "end_time": "2026-10-16 22:00",
        "notes": "ramen", "with_who": "Sam", "where": "Soho", "subevents": [],
    }

    fake.on("GET", "calendar", r"/events/7")(lambda r, m: httpx.Response(200, json={"event": state}))

    @fake.on("PUT", "calendar", r"/events/7")
    def put(request, m):
        b = body(request)
        state.update(
            name=b["name"], notes=b["notes"], with_who=b["with_who"], where=b["where"],
            start_time=f"{b['start_date']} {b['start_time']}", end_time=f"{b['end_date']} {b['end_time']}",
        )
        return httpx.Response(200, json={"status": "success"})

    return state


async def test_update_moving_start_keeps_length_and_moves_moments(config, backend, fake, entry):
    err, text = await run(config, backend, "calendar_update_entry", id=7, start_date="2026-10-17",
                          start_time="20:00")
    assert not err, text
    sent = body(fake.last("PUT"))
    assert (sent["start_date"], sent["start_time"]) == ("2026-10-17", "20:00")
    assert (sent["end_date"], sent["end_time"]) == ("2026-10-17", "22:30")  # 2½ h kept
    assert sent["move_moments"] is True
    assert "Sat 17 Oct 2026 20:00–22:30" in text


async def test_update_keeps_blank_fields_and_clears_dash(config, backend, fake, entry):
    await run(config, backend, "calendar_update_entry", id=7, where="-", end_time="23:00")
    sent = body(fake.last("PUT"))
    assert sent["name"] == "Dinner" and sent["notes"] == "ramen" and sent["with_who"] == "Sam"
    assert sent["where"] == ""
    assert (sent["start_time"], sent["end_time"]) == ("19:30", "23:00")
    assert "move_moments" not in sent  # start unchanged


async def test_create_validates_before_calling(config, backend, fake):
    err, text = await run(config, backend, "calendar_create_entry", name="X", start_date="tomorrow")
    assert err and "YYYY-MM-DD" in text
    err, text = await run(config, backend, "calendar_create_entry", name="X", start_date="2026-10-16",
                          start_time="7pm")
    assert err and "HH:MM" in text
    assert fake.requests == []


async def test_get_day_hides_marker(config, backend, fake):
    fake.on("GET", "calendar", r"/events/")(lambda r, m: httpx.Response(200, json={
        "status": "success", "events": [], "mood": "good", "has_marker": True}))
    err, text = await run(config, backend, "calendar_get_day", date="2026-10-16")
    assert not err and "mood: good" in text
    assert "marker" not in text.lower()


async def test_set_mood_clear_sends_null(config, backend, fake):
    fake.on("POST", "calendar", r"/mood/update")(
        lambda r, m: httpx.Response(200, json={"status": "success", "previous": "low"}))
    err, text = await run(config, backend, "calendar_set_mood", date="2026-10-16", mood="clear")
    assert body(fake.last())["mood"] is None
    assert "cleared (was low)" in text


async def test_library_update_merges_tags(config, backend, fake):
    meta = {"title": "Piranesi", "author": "Clarke", "tags": ["fantasy", "Fave"], "status": "Unread",
            "filename": "a b.epub", "created_at": "2026-01-01 00:00:00"}

    @fake.on("POST", "library", r"/book_metadata/a b\.epub")
    def save(request, m):
        b = body(request)
        meta["tags"] = b["tags"]
        meta["status"] = b.get("status", meta["status"])
        return httpx.Response(200, json={"message": "Saved"})

    fake.on("GET", "library", r"/book_metadata/a b\.epub")(lambda r, m: httpx.Response(200, json=meta))
    err, text = await run(config, backend, "library_update_book", filename="a b.epub", status="finished",
                          add_tags=["FANTASY", "re-read"], remove_tags=["fave"])
    assert not err, text
    assert fake.last("POST").url.raw_path == b"/book_metadata/a%20b.epub"
    assert meta["tags"] == ["fantasy", "re-read"]
    assert meta["status"] == "Finished"


async def test_tapes_add_loops_and_reports(config, backend, fake):
    @fake.on("POST", "tapes", r"/api/playlists/3/tracks")
    def add(request, m):
        tid = body(request)["track_id"]
        if tid == 9:
            return httpx.Response(404, json={"error": "That song isn't in the library any more."})
        return httpx.Response(200, json={"added": tid != 2, "tape": "Mix"})

    err, text = await run(config, backend, "tapes_add_to_playlist", playlist_id=3, track_ids=[1, 2, 9])
    assert not err
    assert text.startswith("Added 1 song(s) to 'Mix', 1 already on it.")
    assert "#9" in text


async def test_tapes_add_to_missing_playlist_is_an_error(config, backend, fake):
    fake.on("POST", "tapes", r"/api/playlists/3/tracks")(
        lambda r, m: httpx.Response(404, json={"error": "The requested URL was not found on the server."}))
    err, text = await run(config, backend, "tapes_add_to_playlist", playlist_id=3, track_ids=[1])
    assert err and "Not found." in text
