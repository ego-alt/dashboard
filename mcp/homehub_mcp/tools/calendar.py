"""Calendar: diary entries ("entries"), the moments inside them, and daily mood.

Words match the app: an *entry* spans a time range (it can run over several
days); a *moment* is a smaller timed note inside an entry. The app calls them
events and subevents.

The day marker is deliberately absent here. It is never read, shown or set.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from mcp.server.mcpserver import MCPServer

from ..backend import AppError
from ..common import (
    IDEMPOTENT,
    READ,
    WRITE,
    Deps,
    capped,
    current_user,
    parse_date,
    parse_time,
)

Kind = Literal["entry", "moment"]
MAX_LIST_DAYS = 366
LIST_LIMIT = 60

DateArg = Annotated[str, Field(description="Date as YYYY-MM-DD.")]
KindArg = Annotated[
    Kind, Field(description="'entry' for a diary entry, 'moment' for a moment inside one.")
]


def _dt(value: str | None) -> datetime | None:
    return datetime.strptime(value, "%Y-%m-%d %H:%M") if value else None


def _span(start: datetime, end: datetime | None) -> str:
    day = start.strftime("%a %-d %b %Y")
    if end is None:
        return f"{day} {start:%H:%M}"
    all_day = start.time() == datetime.min.time() and end.strftime("%H:%M") == "23:59"
    if start.date() == end.date():
        return f"{day}, all day" if all_day else f"{day} {start:%H:%M}–{end:%H:%M}"
    if all_day:
        return f"{day} – {end:%a %-d %b %Y}"
    return f"{day} {start:%H:%M} – {end:%a %-d %b %Y} {end:%H:%M}"


def _entry_line(e: dict, prefix: str = "#") -> str:
    parts = [f"{prefix}{e['id']} {e['name']}", _span(_dt(e["start_time"]), _dt(e["end_time"]))]
    if e.get("with_who"):
        parts.append(f"with {e['with_who']}")
    if e.get("where"):
        parts.append(f"at {e['where']}")
    line = " · ".join(parts)
    if e.get("notes"):
        notes = " ".join(e["notes"].split())
        line += f"\n    notes: {notes[:400]}{'…' if len(notes) > 400 else ''}"
    return line


def _entry_block(e: dict) -> str:
    lines = [_entry_line(e)]
    for s in e.get("subevents") or []:
        lines.append("  - " + _entry_line(s, prefix="moment #").replace("\n", "\n  "))
    return "\n".join(lines)


def _payload(name, start_date, start_time, end_date, end_time, notes, with_who, where) -> dict:
    """The app's entry body. Times are optional: no start time is the start of
    the day, no end time the end of the end day."""
    parse_date(start_date, "start_date")
    if end_date:
        parse_date(end_date, "end_date")
    return {
        "name": name,
        "start_date": start_date,
        "start_time": parse_time(start_time, "start_time") if start_time else None,
        "end_date": end_date or start_date,
        "end_time": parse_time(end_time, "end_time") if end_time else None,
        "notes": notes,
        "with_who": with_who,
        "where": where,
    }


def _as_saved(entry_id: int, body: dict) -> dict:
    """The entry as the app stores it, built from the body it just accepted:
    a missing start time is 00:00, a missing end time 23:59 (``read_entry``).
    Saves a read-back round trip after every write."""
    end_date = body.get("end_date") or body["start_date"]
    return {
        "id": entry_id,
        "name": body["name"].strip(),
        "start_time": f"{body['start_date']} {body.get('start_time') or '00:00'}",
        "end_time": f"{end_date} {body.get('end_time') or '23:59'}",
        "notes": body.get("notes"),
        "with_who": body.get("with_who"),
        "where": body.get("where"),
    }


def register(server: MCPServer, deps: Deps) -> None:
    tz = deps.config.timezone

    async def call(method: str, path: str, **kw):
        return await deps.backend.request("calendar", method, path, user=current_user(), **kw)

    async def fetch(entry_id: int, kind: str) -> dict:
        if kind == "moment":
            return (await call("GET", f"/events/subevents/{entry_id}"))["subevent"]
        return (await call("GET", f"/events/{entry_id}"))["event"]

    @server.tool(
        name="calendar_get_day",
        annotations=READ,
        description=(
            "Everything logged on one day: diary entries (with their moments) and the "
            f"day's mood. Times are local ({tz})."
        ),
    )
    async def calendar_get_day(date: DateArg) -> str:
        d = parse_date(date, "date")
        data = await call("GET", "/events/", params={"year": d.year, "month": d.month, "day": d.day})
        head = f"{d:%A %-d %B %Y} · mood: {data.get('mood') or 'not set'}"
        if not data["events"]:
            return head + "\nNo entries."
        return head + "\n" + "\n".join(_entry_block(e) for e in data["events"])

    @server.tool(
        name="calendar_list_entries",
        annotations=READ,
        description=(
            "Diary entries overlapping a date range (both ends inclusive, at most 366 days), "
            "oldest first, with their moments. Use calendar_search to find entries by "
            "content, person or place instead."
        ),
    )
    async def calendar_list_entries(from_date: DateArg, to_date: DateArg) -> str:
        start, end = parse_date(from_date, "from_date"), parse_date(to_date, "to_date")
        if (end - start).days >= MAX_LIST_DAYS:
            raise AppError(f"Ask for at most {MAX_LIST_DAYS} days at a time.")
        data = await call("GET", "/events/range", params={"from": from_date, "to": to_date})
        if not data["events"]:
            return f"No entries between {start} and {end}."
        blocks = [_entry_block(e) for e in data["events"]]
        return capped(blocks, LIST_LIMIT, "Narrow the date range to see the rest.")

    @server.tool(
        name="calendar_get_entry",
        annotations=READ,
        description="One diary entry (with its moments) or one moment, by id.",
    )
    async def calendar_get_entry(id: int, kind: KindArg = "entry") -> str:
        e = await fetch(id, kind)
        if kind == "moment":
            return _entry_line(e, prefix="moment #") + f"\n  inside entry #{e['event_id']}"
        return _entry_block(e)

    @server.tool(
        name="calendar_search",
        annotations=READ,
        description=(
            "Search the diary. `query` is free text and may include plain-English filters "
            "the calendar understands, e.g. 'ramen with Sam last spring' or 'great days in "
            "March'. The explicit filters below override what the query implies. Returns "
            "newest matches first with their ids."
        ),
    )
    async def calendar_search(
        query: Annotated[str, Field(description="Words to look for, or '' for filters only.")] = "",
        from_date: Annotated[str, Field(description="YYYY-MM-DD, or '' for no lower bound.")] = "",
        to_date: Annotated[str, Field(description="YYYY-MM-DD inclusive, or ''.")] = "",
        mood: Annotated[
            Literal["", "great", "good", "okay", "low", "rough"],
            Field(description="Only days with this mood, or '' for any."),
        ] = "",
        who: Annotated[str, Field(description="A person the entry was with, or ''.")] = "",
        where: Annotated[str, Field(description="A place, or ''.")] = "",
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> str:
        if from_date:
            parse_date(from_date, "from_date")
        if to_date:
            parse_date(to_date, "to_date")
        params = {
            "q": query, "from": from_date or None, "to": to_date or None, "mood": mood or None,
            "who": who or None, "where": where or None, "limit": limit,
        }
        data = await call("GET", "/search/data", params=params)
        labels = (data.get("parsed") or {}).get("labels") or []
        head = f"Understood as: {', '.join(labels)}\n" if labels else ""
        if not data["results"]:
            return head + "No matching entries."
        lines = []
        for e in data["results"]:
            line = _entry_line(e)
            if e.get("mood"):
                line = line.replace(" · ", f" · day mood {e['mood']['name'].lower()} · ", 1)
            lines.append(line)
        more = "\n(more matches exist; narrow the search or raise limit)" if data.get("more") else ""
        return head + "\n".join(lines) + more

    @server.tool(
        name="calendar_create_entry",
        annotations=WRITE,
        description=(
            "Add a diary entry, or a moment inside an existing entry when parent_id is given "
            f"(a moment dated outside its entry stretches the entry to fit). Times are local ({tz}), "
            "24-hour HH:MM. Leave start_time empty to start at the beginning of the day and "
            "end_time empty to run to the end of the end day; leave end_date empty for "
            "the same day. Check calendar_get_day first if the user may mean an existing "
            "entry, to avoid duplicates."
        ),
    )
    async def calendar_create_entry(
        name: Annotated[str, Field(min_length=1, max_length=200, description="Short title.")],
        start_date: DateArg,
        start_time: Annotated[str, Field(description="HH:MM, or ''.")] = "",
        end_date: Annotated[str, Field(description="YYYY-MM-DD, or '' for start_date.")] = "",
        end_time: Annotated[str, Field(description="HH:MM, or ''.")] = "",
        notes: Annotated[str, Field(description="Free-text diary notes.")] = "",
        with_who: Annotated[str, Field(description="People, comma-separated.")] = "",
        where: Annotated[str, Field(description="Place.")] = "",
        parent_id: Annotated[
            int, Field(description="Entry id to add this as a moment of, or 0 for a new entry.")
        ] = 0,
    ) -> str:
        body = _payload(name, start_date, start_time, end_date, end_time, notes, with_who, where)
        if parent_id:
            res = await call("POST", f"/events/{parent_id}/subevents", json=body)
            e = _as_saved(res["id"], body)
            stretched = f" {res['stretched']}" if res.get("stretched") else ""
            return "Added " + _entry_line(e, prefix="moment #") + f" to entry #{parent_id}.{stretched}"
        res = await call("POST", "/events/", json=body)
        return "Added " + _entry_line(_as_saved(res["id"], body))

    @server.tool(
        name="calendar_update_entry",
        annotations=IDEMPOTENT,
        description=(
            "Change an entry or moment. Only the fields you pass change; pass '' to leave a "
            "field as it is. To clear notes, with_who or where, pass a single '-'. Moving "
            "the start without giving a new end keeps the entry's length, and an entry's moments "
            "move with it."
        ),
    )
    async def calendar_update_entry(
        id: int,
        kind: KindArg = "entry",
        name: str = "",
        start_date: Annotated[str, Field(description="YYYY-MM-DD, or ''.")] = "",
        start_time: Annotated[str, Field(description="HH:MM, or ''.")] = "",
        end_date: Annotated[str, Field(description="YYYY-MM-DD, or ''.")] = "",
        end_time: Annotated[str, Field(description="HH:MM, or ''.")] = "",
        notes: str = "",
        with_who: str = "",
        where: str = "",
    ) -> str:
        cur = await fetch(id, kind)
        old_start, old_end = _dt(cur["start_time"]), _dt(cur["end_time"])

        new_start = old_start
        if start_date:
            d = parse_date(start_date, "start_date")
            new_start = new_start.replace(year=d.year, month=d.month, day=d.day)
        if start_time:
            t = datetime.strptime(parse_time(start_time, "start_time"), "%H:%M")
            new_start = new_start.replace(hour=t.hour, minute=t.minute)

        new_end = old_end
        if new_end is not None and not end_date and not end_time:
            new_end = new_end + (new_start - old_start)  # keep the length
        if end_date or end_time:
            new_end = new_end or new_start
            if end_date:
                d = parse_date(end_date, "end_date")
                new_end = new_end.replace(year=d.year, month=d.month, day=d.day)
            if end_time:
                t = datetime.strptime(parse_time(end_time, "end_time"), "%H:%M")
                new_end = new_end.replace(hour=t.hour, minute=t.minute)

        def keep(value: str, old):
            if value == "-":
                return ""
            return value or old

        body = {
            "name": name or cur["name"],
            "start_date": f"{new_start:%Y-%m-%d}",
            "start_time": f"{new_start:%H:%M}",
            "end_date": f"{new_end:%Y-%m-%d}" if new_end else None,
            "end_time": f"{new_end:%H:%M}" if new_end else None,
            "notes": keep(notes, cur.get("notes")),
            "with_who": keep(with_who, cur.get("with_who")),
            "where": keep(where, cur.get("where")),
        }
        if kind == "entry" and new_start != old_start:
            body["move_moments"] = True
        path = f"/events/subevents/{id}" if kind == "moment" else f"/events/{id}"
        res = await call("PUT", path, json=body)
        e = _as_saved(id, body)
        stretched = f" {res['stretched']}" if isinstance(res, dict) and res.get("stretched") else ""
        return "Updated " + (_entry_line(e, prefix="moment #") if kind == "moment" else _entry_line(e)) + stretched

    @server.tool(
        name="calendar_restore_entry",
        annotations=IDEMPOTENT,
        description=(
            "Bring back an entry or moment deleted in the calendar app (within 30 days). "
            "Assistants can't delete; the user does that in the app."
        ),
    )
    async def calendar_restore_entry(id: int, kind: KindArg = "entry") -> str:
        path = f"/events/subevents/{id}/restore" if kind == "moment" else f"/events/{id}/restore"
        await call("POST", path)
        e = await fetch(id, kind)
        return "Restored " + (_entry_line(e, prefix="moment #") if kind == "moment" else _entry_line(e))

    @server.tool(
        name="calendar_set_mood",
        annotations=IDEMPOTENT,
        description=(
            "Set the mood for a day: great, good, okay, low or rough (best to worst), or "
            "'clear' to remove it. Only set a mood the user stated; don't infer one."
        ),
    )
    async def calendar_set_mood(
        date: DateArg, mood: Literal["great", "good", "okay", "low", "rough", "clear"]
    ) -> str:
        d = parse_date(date, "date")
        res = await call(
            "POST",
            "/mood/update",
            json={"year": d.year, "month": d.month, "day": d.day,
                  "mood": None if mood == "clear" else mood},
        )
        was = res.get("previous") or "not set"
        now = "cleared" if mood == "clear" else f"set to {mood}"
        return f"Mood for {d:%a %-d %b %Y} {now} (was {was})."

    @server.tool(
        name="calendar_stats",
        annotations=READ,
        description=(
            "Mood and activity summary: how many days were logged, the mood mix, streaks, "
            "mood by weekday, and which people and places go with better or worse days. "
            "Covers the last 12 months, or one calendar year."
        ),
    )
    async def calendar_stats(
        year: Annotated[int, Field(description="A year like 2025, or 0 for the last 12 months.")] = 0,
    ) -> str:
        s = await call("GET", "/stats/data", params={"year": year or None})
        t = s["tiles"]
        out = [
            f"{s['range_start']} to {s['range_end']}: {t['logged']} of {t['total']} days have a mood.",
            f"Longest streak {t['longest_streak']} days"
            + (f", current streak {t['current_streak']}." if t.get("current_streak") is not None else "."),
        ]
        if s["distribution"]:
            out.append("Mix: " + ", ".join(f"{d['name']} {d['pct']}%" for d in s["distribution"]))
        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        wk = []
        for name, mix in zip(days, s.get("weekday") or []):
            if mix:
                top = max(mix, key=lambda m: m["count"])
                wk.append(f"{name} mostly {top['name'].lower()}")
        if wk:
            out.append("By weekday: " + ", ".join(wk))
        mw = s.get("mood_with") or {}
        if mw.get("overall") is not None:
            out.append(f"Average mood score {mw['overall']} (5 great … 1 rough).")
            for label, rows in (("People", mw.get("people")), ("Places", mw.get("places"))):
                if rows:
                    out.append(
                        f"{label} (min {mw['min_days']} days): "
                        + ", ".join(f"{r['name']} {r['delta']:+.2f} over {r['days']}d" for r in rows[:8])
                    )
        epm = s.get("events_per_month")
        if epm:
            out.append("Days with entries: " + ", ".join(f"{m['label']} {m['count']}" for m in epm))
        if s.get("years"):
            out.append(f"Years with data: {', '.join(str(y) for y in s['years'])}")
        return "\n".join(out)
