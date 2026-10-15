"""Library (the EPUB app): find books, read and change metadata, tags and
reading status. Books are identified by their filename."""

from __future__ import annotations

import asyncio
from typing import Annotated, Literal
from urllib.parse import quote

from pydantic import Field

from mcp.server.mcpserver import MCPServer

from ..common import IDEMPOTENT, READ, Deps, current_user

PAGE = 30  # books per library_list_books page (the app's own batch is 30 too)
STATUS = {"unread": "Unread", "reading": "In Progress", "finished": "Finished"}

FilenameArg = Annotated[
    str, Field(description="The book's filename, as returned by library_find_book/list_books.")
]


def _f(filename: str) -> str:
    return quote(filename.strip(), safe="")


def register(server: MCPServer, deps: Deps) -> None:
    async def call(method: str, path: str, **kw):
        return await deps.backend.request("library", method, path, user=current_user(), **kw)

    @server.tool(
        name="library_find_book",
        annotations=READ,
        description=(
            "Does the user own a book? Fuzzy-matches title and/or author (tolerates "
            "subtitles, editions and name order) and returns the closest books, best first."
        ),
    )
    async def library_find_book(title: str = "", author: str = "") -> str:
        res = await call("GET", "/books", params={"title": title or None, "author": author or None})
        if not res["matches"]:
            return "No book in the library matches."
        return "\n".join(
            f"{m['title']} · {m['author']} · filename={m['filename']} · match {m['score']}"
            for m in res["matches"]
        )

    @server.tool(
        name="library_list_books",
        annotations=READ,
        description=(
            f"Browse the library {PAGE} books at a time, newest first, optionally filtered "
            "by reading status and a title/author search."
        ),
    )
    async def library_list_books(
        query: Annotated[str, Field(description="Title/author words, or ''.")] = "",
        status: Literal["all", "unread", "reading", "finished"] = "all",
        page: Annotated[int, Field(ge=1)] = 1,
    ) -> str:
        offset = (page - 1) * PAGE
        books, headers = await deps.backend.request(
            "library", "GET", f"/load_more/{offset}", user=current_user(),
            params={"q": query or None, "view": status}, with_headers=True,
        )
        total = int(headers.get("X-Total-Count", len(books)))
        if not books:
            return "No books." if page == 1 else f"No books on page {page} (there are {total})."
        lines = [f"{b['title']} · {b['author']} · filename={b['filename']}" for b in books]
        pages = -(-total // PAGE)
        return f"Page {page} of {pages} ({total} books)\n" + "\n".join(lines)

    @server.tool(
        name="library_get_book",
        annotations=READ,
        description="A book's details: title, author, genre, the user's tags, reading status and place.",
    )
    async def library_get_book(filename: FilenameArg) -> str:
        m, b = await asyncio.gather(
            call("GET", f"/book_metadata/{_f(filename)}"), call("GET", f"/bookmark/{_f(filename)}")
        )
        lines = [
            f"{m['title']} · {m.get('author_display') or m['author']}",
            f"filename={m['filename']} · added {m['created_at'][:10]}",
            f"status: {m['status']}" + (
                f" (chapter {b['chapter_index'] + 1})" if b.get("chapter_index") else ""
            ),
        ]
        if m.get("genre"):
            lines.append(f"genre: {m['genre']}")
        lines.append("tags: " + (", ".join(m["tags"]) or "none"))
        return "\n".join(lines)

    @server.tool(
        name="library_update_book",
        annotations=IDEMPOTENT,
        description=(
            "Change a book's reading status or the user's own tags. Title, author and genre "
            "are shared by everyone and only admins can change them. Leave a field '' (or "
            "the tag lists empty) to keep it as is."
        ),
    )
    async def library_update_book(
        filename: FilenameArg,
        status: Literal["", "unread", "reading", "finished"] = "",
        add_tags: list[str] = [],
        remove_tags: list[str] = [],
        title: str = "",
        author: str = "",
        genre: str = "",
    ) -> str:
        cur = await call("GET", f"/book_metadata/{_f(filename)}")
        drop = {t.strip().lower() for t in remove_tags}
        tags = [t for t in cur["tags"] if t.lower() not in drop]
        for t in add_tags:
            if t.strip() and t.strip().lower() not in {x.lower() for x in tags}:
                tags.append(t.strip())
        body: dict = {"tags": tags}
        if status:
            body["status"] = STATUS[status]
        if title:
            body["title"] = title
        if author:
            body["author"] = author
        if genre:
            body["genre"] = genre
        await call("POST", f"/book_metadata/{_f(filename)}", json=body)
        if title or author or genre:
            # Shared fields are admin-only and silently kept for others: read
            # back to tell the model which happened.
            new = await call("GET", f"/book_metadata/{_f(filename)}")
        else:
            new = {**cur, "tags": tags, "status": STATUS.get(status, cur["status"])}
        note = ""
        if (title and new["title"] != title) or (author and new["author"] != author):
            note = " (Title/author unchanged: only admins can edit them.)"
        return (
            f"Saved {new['title']}: status {new['status']}, "
            f"tags {', '.join(new['tags']) or 'none'}.{note}"
        )

    @server.tool(name="library_list_tags", annotations=READ,
                 description="All tags the user has put on books.")
    async def library_list_tags() -> str:
        tags = await call("GET", "/tags")
        return ", ".join(tags) or "No tags yet."

    @server.tool(name="library_restore_book", annotations=IDEMPOTENT,
                 description="Bring back a book someone deleted in the library app (admins only, within 30 days).")
    async def library_restore_book(filename: FilenameArg) -> str:
        res = await call("POST", f"/book/{_f(filename)}/restore")
        return f"Restored '{res.get('title', filename)}'."
