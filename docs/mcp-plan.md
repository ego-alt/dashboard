# MCP server: design

Give any AI assistant hands on the home stack. For example: "log dinner with
Sam on Friday", "how was my mood in March?", "download this album", "add it to
Road trip", "have I got *Piranesi*?".

The server speaks the open Model Context Protocol, so it is **model-agnostic**.
Claude, ChatGPT, Gemini, Cursor, VS Code, or a local model behind an
MCP-capable client all get the same tools. Nothing in it is tied to one vendor.

Other docs:
- setup and client configuration: [`mcp/README.md`](../mcp/README.md);
- findings, open items, missing endpoints and the request path:
  [`mcp/AUDIT.md`](../mcp/AUDIT.md).

---

## 1. What the server is

It is a small, separate process (`dashboard/mcp/`, the `mcp` container) that
holds three things:

1. **A list of tools.** Each tool has a name, a plain-English description and a
   JSON schema for its arguments. The assistant reads these and decides what to
   call.
2. **A thin adapter per app.** Each tool becomes one or two calls to an app
   endpoint, and the adapter shapes the reply into compact text.
3. **Auth.** It works out *who* is asking, and only ever acts as that user.

The apps keep owning their data and rules. Their validation errors ("The end is
before the start.") reach the model verbatim, so it can correct itself.

It lives in the dashboard repo because the dashboard owns identity and
routing. It runs as its own container because it is a different kind of server
with its own SDK, and a bug in it can't take down login. nginx resolves it per
request, so the stack starts without it.

---

## 2. Design rules (what makes it work across models)

Smaller and non-Claude models are much less forgiving of clever tool design.

- **Tools only.** No MCP resources, prompts or sampling, which many clients
  ignore. Anything a model needs to know goes in a tool description.
- **Flat, explicit schemas.**
  - Dates are `YYYY-MM-DD` and times are 24-hour `HH:MM`.
  - Fixed sets are enums.
  - There is no `anyOf`, `oneOf`, `$ref` or `null` (a test enforces this).
    Optional text defaults to `''` and optional numbers to `0`.
- **Prefixed, verb-first names** (`calendar_create_entry`): no collisions when a
  client loads several servers.
- **Descriptions carry the guidance**: time zone, what an empty field means,
  "check calendar_get_day first to avoid duplicates".
- **Short text results with ids inline**, e.g.
  `#412 Dinner with Sam · Fri 17 Oct 19:30–22:00`. Lists are capped and say how
  to narrow them.
- **No deletes.** Deleting stays with the user, in the apps. Text the model
  reads, such as RSS titles and YouTube metadata, comes from strangers, and an
  instruction planted there must not be able to remove anything. Restore tools
  remain: they bring back what the user deleted in an app within its 30-day
  trash. A test fails if any tool is named for deletion or marked
  destructive.
- **The day marker is never exposed**: not in output, and no tool for it.
- **`homehub_now`** gives today's date, for models that don't know it.

---

## 3. Tools (31)

### Calendar

| Tool | Does | App endpoint |
|---|---|---|
| `calendar_get_day(date)` | Entries + mood for one day | `GET /events/?year&month&day` |
| `calendar_list_entries(from_date, to_date)` | Entries in a range (≤ 366 days) | `GET /events/range` |
| `calendar_get_entry(id, kind)` | One entry with its moments, or one moment | `GET /events/<id>`, `GET /events/subevents/<id>` |
| `calendar_search(query, from_date, to_date, mood, who, where, limit)` | Full-text + filtered search | `GET /search/data` |
| `calendar_create_entry(name, start_date, start_time, end_date, end_time, notes, with_who, where, parent_id)` | New entry, or a moment inside one | `POST /events/`, `POST /events/<id>/subevents` |
| `calendar_update_entry(id, kind, …)` | Change only the fields given; moving keeps the length and moves the moments | `GET` + `PUT` (`move_moments`) |
| `calendar_restore_entry(id, kind)` | Bring back a deleted entry or moment | `POST …/restore` |
| `calendar_set_mood(date, mood)` | `great`…`rough`, or `clear` | `POST /mood/update` |
| `calendar_stats(year)` | Mood mix, streaks, weekdays, people/places | `GET /stats/data` |

Here `kind` is `entry | moment`.

### Tapes

| Tool | Does | App endpoint |
|---|---|---|
| `tapes_download(url)` | Queue a rip; a playlist link expands to every track | `POST /api/downloads` |
| `tapes_list_downloads()` / `tapes_dismiss_download(job_id)` | Queue and recent results; hide a finished job | `GET`, `DELETE /api/downloads/…` |
| `tapes_search_tracks(query, limit)` | Every word in title, artist or album | `GET /api/tracks?q=` |
| `tapes_list_playlists()` / `tapes_get_playlist(key)` | Shelf with counts; one page of a playlist | `GET /api/playlists`, `GET …/<key>/tracks?limit=` |
| `tapes_create_playlist` / `tapes_rename_playlist` | | `POST` / `PATCH /api/playlists` |
| `tapes_add_to_playlist(playlist_id, track_ids)` / `tapes_remove_from_playlist` | Songs on or off a playlist (they stay in the library) | `POST` / `DELETE /api/playlists/<id>/tracks` |
| `tapes_update_track(track_id, title, artist, album, track_no)` | Fix metadata, shared by everyone | `PATCH /api/tracks/<id>` |
| `tapes_restore_track(track_id)` | Bring back a deleted song (admins) | `POST /api/tracks/<id>/restore` |
| `tapes_list_podcasts` / `tapes_add_podcast(url)` / `tapes_list_episodes(show_id)` | | `/api/podcast/…` |

`tapes_download` takes a **link**. Tapes doesn't search the web; the assistant
brings its own search tool to find one.

### Library

| Tool | Does | App endpoint |
|---|---|---|
| `library_find_book(title, author)` | "Do I own this?", fuzzy match | `GET /books` |
| `library_list_books(query, status, page)` | Browse or search, 30 per page | `GET /load_more/<offset>` |
| `library_get_book(filename)` | Details, tags, status, place | `GET /book_metadata/<f>` + `GET /bookmark/<f>` |
| `library_update_book(filename, status, add_tags, remove_tags, title, author, genre)` | Status and the user's tags; shared fields are admin-only | `GET` + `POST /book_metadata/<f>` |
| `library_list_tags()` | | `GET /tags` |
| `library_restore_book(filename)` | Bring back a deleted book (admins) | `POST /book/<f>/restore` |

**Left out on purpose:**
- uploading books or photos (binary payloads over MCP are poorly supported
  across clients);
- streaming audio;
- the dashboard's own admin (containers, users, backups).

---

## 4. Auth

### 4.1 Who the server acts as

Every request resolves to one dashboard user. In the container, the server
calls the apps **directly on the compose network** with
`X-Forwarded-User: <username>`, which is what nginx does after `auth_request`.
It also sends `X-Internal-Auth` when `INTERNAL_AUTH_SECRET` is set.

It never forwards the client's token to the apps (the MCP spec forbids "token
passthrough"). A token minted for the MCP server is only accepted by the MCP
server.

### 4.2 Local: stdio + an API token

Desktop clients launch the server as a subprocess, with `HOMEHUB_URL` and
`HOMEHUB_TOKEN` (a dashboard API token from Settings) and, for the self-signed
cert, `HOMEHUB_CA`.

It can't reach the compose network from a laptop. Instead it calls the apps
through nginx with `Authorization: Bearer <token>`, which `/auth/verify`
already accepts. This is the user's own token for their own stack, so it isn't
passthrough.

### 4.3 Remote: streamable HTTP + OAuth 2.1

`https://home.local/mcp` uses the standard MCP authorization flow:

- **Discovery.** `/mcp` answers `401` with
  `WWW-Authenticate: Bearer resource_metadata=…`. It serves
  `/.well-known/oauth-protected-resource/mcp` and
  `/.well-known/oauth-authorization-server`.
- **The authorization server is the `mcp` container**, using the SDK's
  implementation of `/register` (dynamic client registration), `/authorize`,
  `/token` and `/revoke`, with PKCE S256 only.
- **The dashboard stays the identity source.** `/authorize` sends the browser to
  `/oauth/consent`. That page asks the dashboard who is signed in by
  forwarding the session cookie to `/auth/verify`, and sends the user through
  the normal dashboard login (TOTP or passkey) if needed.
  - Arriving from another site, the browser withholds the
    `SameSite=strict` cookie, so the page reloads itself once, same-site.
  - The page shows the client's name and where it will redirect, and is
    protected by a CSRF token. It can't be framed.
- **Registration rules.** Plain `http` redirect URIs are allowed only to
  localhost. App schemes (`cursor://`) are fine.
- **Tokens.**
  - Codes are single-use and live 5 minutes.
  - Access tokens live 1 hour; refresh tokens 30 days, and they rotate.
  - All are stored as SHA-256 hashes.
  - Unused registrations are pruned after 7 days.
- **Static header.** `/mcp` also accepts a dashboard API token as the bearer,
  for clients that only take a fixed header. It is checked with the
  dashboard's `/auth/verify` and cached for 60 seconds.
- **Rate limit.** nginx limits `/authorize`, `/token`, `/register` and
  `/revoke` to 20 requests a minute per IP.

### 4.4 Activity and revocation

Every tool call is logged in the container's SQLite: user, client, tool,
trimmed arguments, success or error. Rows are kept 90 days.
`/oauth/connections` shows the signed-in user their connected apps, with
connection and last-used times, a **Disconnect** button (which kills that
grant's tokens), and recent activity.

---

## 5. Clients

| Client | Transport | Auth |
|---|---|---|
| Claude Desktop / Claude Code | stdio, or remote | API token, or OAuth |
| Cursor, VS Code | stdio, or remote | API token (header), or OAuth |
| Gemini CLI | stdio, or remote | API token, or OAuth |
| Local models (LM Studio, Open WebUI, Goose…) | mostly stdio | API token |
| claude.ai / ChatGPT connectors | remote only | OAuth; **needs public reachability** (AUDIT §1.1) |
| A future home assistant on the Pi | remote, LAN | API token |

Remote-HTTP clients must trust the home's certificate (see the README).
Client MCP support changes month to month; check each one's docs.

---

## 6. Layout + deployment

```
dashboard/mcp/
  pyproject.toml, uv.lock, Dockerfile
  homehub_mcp/
    server.py      # MCPServer, transports, audit middleware, entry point
    backend.py     # internal (header) vs external (bearer) app client
    oauth.py       # provider + consent / connections pages
    store.py       # SQLite: clients, grants, codes, tokens, audit
    tools/         # calendar.py, tapes.py, library.py
  tests/           # fakes for the apps + dashboard; no services needed
```

- **Compose:** the `mcp` service on port 8100, with a named volume for
  `/data`, and depends on the dashboard being healthy. It has no
  `homehub.enable` label, so it doesn't show as a tile.
- **nginx:** routes `/mcp`, the four OAuth endpoints, `/.well-known/oauth-*`
  and `/oauth/` to it, without `auth_request`. Buffering is off on `/mcp`.
- **CI:** an `mcp` job runs its tests and ruff.
- **`deploy.sh`:** after a dashboard deploy it rebuilds `mcp` best-effort. A
  broken `mcp` is recorded, never a reason to roll the dashboard back.

---

## 7. Testing

- **Unit and HTTP tests** (`mcp/tests`) drive the real ASGI app:
  - discovery, registration rules, consent (bounce, login redirect, CSRF,
    deny), PKCE, single-use codes, refresh rotation, revocation, API-token
    fallback, audit;
  - per-tool logic against fake apps: partial updates, keeping lengths, tag
    merging, the marker never showing, flat schemas, no deletes.
- **A live run against all three real apps** (throwaway data, proxy mode)
  covered the full OAuth flow, every tool, a standard user via an API token,
  and stdio.
- **Still worth doing:** a scripted cross-model check (~15 requests through at
  least one Claude, one OpenAI and one local model) to catch description
  problems that only weaker tool-callers hit.
