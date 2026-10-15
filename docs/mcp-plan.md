# MCP server: plan

Give any AI assistant hands on the home stack. For example: "log dinner with
Sam on Friday", "how was my mood in March?", "download this album", "add it to
Road trip", "have I got *Piranesi*?".

The server speaks the open Model Context Protocol, so it is **model-agnostic**.
Claude, ChatGPT, Gemini, Cursor, VS Code, or a local model behind an
MCP-capable client all get the same tools. Nothing in it is tied to one vendor.

This is a plan, not a spec. Open questions are in §9.

**Status (2026-10-15).** Phases 1–4 are built on the `mcp-server` branch. Setup
is in [`mcp/README.md`](../mcp/README.md); findings and missing endpoints are in
[`mcp/AUDIT.md`](../mcp/AUDIT.md). The build differs from this plan in four ways:

- **The OAuth server lives in the `mcp` container, not the dashboard.** The
  MCP SDK already implements the protocol endpoints (metadata, dynamic
  registration, PKCE, refresh, revoke), so we keep the dashboard unchanged.
  The dashboard stays the identity source: the consent page asks it who is
  signed in by forwarding the session cookie to `/auth/verify`, and login
  (with TOTP or a passkey) happens on the dashboard as usual.
- **The activity log and "Connected apps" page live in the `mcp` container**
  too, at `/oauth/connections`. The dashboard needed no migration.
- **Results are short text only**, with no `structuredContent`. That is the
  form every client handles the same way.
- **There are 35 tools.** Compared with §3:
  - added: `calendar_get_entry`, `tapes_update_track`,
    `tapes_delete_track` / `tapes_restore_track`, and `homehub_now` (today's
    date, for models that don't know it);
  - renamed: `tapes_cancel_download` is now `tapes_dismiss_download` (that is
    what the endpoint does);
  - replaced: `library_mark_finished` is folded into `library_update_book`
    (`status`).

---

## 1. What "the MCP server" actually is

It is a small, separate process. It does not add a pile of new endpoints to
each app. It holds:

1. **A list of tools.** Each tool has a name, a plain-English description and a
   JSON-schema for its arguments, for example
   `calendar_create_entry(name, start_date, …)`. The assistant reads these and
   decides what to call.
2. **A thin adapter per app.** Each tool becomes a call to an existing app
   endpoint, such as `POST /calendar/events/` or `POST /music/api/downloads`.
   The adapter then shapes the reply into something compact a model can read.
3. **Auth.** It works out *who* is asking, and only acts as that user.

The apps keep owning their data and rules. Validation errors like "The end is
before the start." flow back to the model verbatim, which helps it self-correct.

**Where it lives:** `dashboard/mcp/` is its own Python package and its own
container, `mcp`, in this compose file.

- It belongs here because the dashboard already owns identity (users, TOTP,
  API tokens) and the routing.
- It is a separate process because it is a different kind of server
  (long-lived streaming connections, a different SDK). A bug in it can't take
  down login.

---

## 2. Design rules (what makes it work across models)

Smaller and non-Claude models are much less forgiving of clever tool design.
So the server follows these rules:

- **Tools only.** No reliance on MCP resources, prompts or sampling, which many
  clients ignore. Anything a model needs to know goes in a tool description.
- **Flat, explicit schemas.**
  - Dates are ISO `YYYY-MM-DD` and times are `HH:MM` (24h).
  - Fixed sets are enums, for example mood is `great | good | okay | low | rough`.
  - There are no nested objects where a couple of fields will do, and no
    `oneOf` or `anyOf`, which several clients mishandle.
- **Prefixed, verb-first names**, such as `calendar_create_entry` and
  `tapes_download`. This avoids collisions when a client loads several MCP
  servers. Names stay under 64 characters, using `[a-z_]` only.
- **Descriptions carry the guidance.** For example: "Times are local
  (Europe/London). Omit `end_time` for a point-in-time entry. Call
  `calendar_get_day` first if the user refers to an existing entry by name."
- **Compact text results.** Each result is a short readable summary with ids
  inline (for example `#412 Dinner with Sam · Fri 17 Oct 19:30–22:00`). It is
  also returned as `structuredContent` for clients that use it. Lists are
  capped and say "N more; narrow with from_date/to_date".
- **Annotations.** Every tool sets `readOnlyHint` or `destructiveHint`, so
  clients that support confirmation prompts ask before deletes.
- **Deletes are soft.** All three apps already soft-delete with a 30-day undo,
  and each delete tool has a matching restore tool. Each delete result says
  "Undo with `calendar_restore_entry(412)`". That is the safety net behind
  "everything including delete".

---

## 3. Tools (first cut, about 28)

**"No app change"** means the tool maps onto an endpoint that exists today.

### Calendar (`calendar_*`)

| Tool | Does | Backed by |
|---|---|---|
| `calendar_get_day(date)` | Entries + mood for one day | `GET /events/?year&month&day`. No app change. |
| `calendar_list_entries(from_date, to_date)` | Entries in a range (≤ 92 days) | Loops `GET /events/month`. No app change. |
| `calendar_search(query?, from_date?, to_date?, mood?, who?, where?, limit?)` | Full-text + filtered search | `GET /search/data`. No app change. |
| `calendar_create_entry(name, start_date, start_time?, end_date?, end_time?, notes?, with_who?, where?, parent_id?)` | New entry, or a sub-moment if `parent_id` is given | `POST /events/` or `POST /events/<id>/subevents`. No app change. |
| `calendar_update_entry(id, kind, …fields)` | Edit an entry or sub-moment | `PUT`. Merges with the current values, because the app expects a full payload. |
| `calendar_delete_entry(id, kind)` | Soft delete (destructive) | `DELETE` |
| `calendar_restore_entry(id, kind)` | Undo a delete | `POST …/restore` |
| `calendar_set_mood(date, mood \| null)` | Set or clear a day's mood | `POST /mood/update`. No app change. |
| `calendar_stats(year?)` | Mood distribution, "mood with…" and so on | `GET /stats/data`. No app change. |

Here `kind` is the enum `entry | moment`.

**Deliberately left out:** the day marker. It never appears in tool output, and
there is no tool to toggle it (§9.1).

### Tapes (`tapes_*`)

| Tool | Does | Backed by |
|---|---|---|
| `tapes_download(url)` | Queue a rip; playlist links expand to every track plus a new playlist | `POST /api/downloads`. No app change. |
| `tapes_list_downloads()` | Queue + recent results, with failure reasons | `GET /api/downloads` |
| `tapes_cancel_download(job_id)` | Cancel or dismiss a job (destructive) | `DELETE /api/downloads/<id>` |
| `tapes_search_tracks(query, limit?)` | Find tracks by title, artist or album | **Gap:** filters `GET /api/playlists/all/tracks` inside the server for now. A proper `?q=` on the app later. |
| `tapes_list_playlists()` | Shelves + user playlists with counts | `GET /api/playlists` |
| `tapes_get_playlist(key)` | Tracks in a playlist | `GET /api/playlists/<key>/tracks` |
| `tapes_create_playlist(name)` | | `POST /api/playlists` |
| `tapes_rename_playlist(playlist_id, name)` | | `PATCH /api/playlists/<id>` |
| `tapes_delete_playlist(playlist_id)` | Destructive | `DELETE /api/playlists/<id>` |
| `tapes_add_to_playlist(playlist_id, track_ids[])` | | `POST /api/playlists/<id>/tracks` |
| `tapes_remove_from_playlist(playlist_id, track_id)` | | `DELETE …/tracks/<id>` |
| `tapes_list_podcasts()` / `tapes_add_podcast(feed_url)` | Shows; subscribe to a feed | `/api/podcast/shows`, `/api/podcast/add` |
| `tapes_list_episodes(show_id)` | | `/api/podcast/shows/<id>/episodes` |

`tapes_download` takes a **link**. Tapes doesn't search YouTube itself, so
"download music I like" works when the assistant has a web-search tool of its
own to find the link. The tool description says so.

### Library (`library_*`)

| Tool | Does | Backed by |
|---|---|---|
| `library_find_book(title?, author?)` | "Do I own this?": fuzzy match | `GET /books`. No app change. |
| `library_list_books(query?, view?, offset?)` | Browse or search the shelf | `GET /load_more/<offset>?q=` |
| `library_get_book(filename)` | Metadata, tags, reading position | `GET /book_metadata/<f>` + `GET /bookmark/<f>` |
| `library_update_book(filename, title?, author?, tags?)` | Edit metadata or tags | `POST /book_metadata/<f>` |
| `library_mark_finished(filename)` | | `POST /tag_finished/<f>` |
| `library_list_tags()` | | `GET /tags` |
| `library_delete_book(filename)` / `library_restore_book(filename)` | Soft delete or undo (destructive) | `DELETE /book/<f>`, `POST …/restore` |

**Not in the first cut:**
- uploading books or photos (binary payloads over MCP are poorly supported
  across clients);
- streaming audio;
- the dashboard's own admin (containers, users, backups). Tokens never grant
  dashboard control today, and that stays true.

Tool count matters for smaller models. If ~28 is too many, the easy trims are:
- the podcast tools;
- `tapes_rename_playlist`;
- folding `library_list_tags` into `library_get_book`.

---

## 4. Auth

### 4.1 Who the server acts as

Every request resolves to one dashboard user. The server then calls the apps
**directly on the Docker network** (`http://calendar:5002/…`) with
`X-Forwarded-User: <username>`. That is exactly what nginx does after
`auth_request`.

It does **not** forward the client's token on to the apps. The MCP spec forbids
that "token passthrough", and this way an OAuth token minted for the MCP server
is only ever accepted by the MCP server.

Trust note: the apps already believe `X-Forwarded-User` from any container on
the compose network. The ports are only `expose`d, never published. Adding
`mcp` doesn't widen that, but it is one more process holding that power. A
cheap hardening for later is a shared `INTERNAL_AUTH_SECRET` header the apps
also require (§9.4).

### 4.2 Local Mac: stdio + personal access token

These clients launch the server as a subprocess: Claude Desktop, Claude Code,
Cursor, VS Code, Gemini CLI, LM Studio and others.

```
uvx --from ./mcp homehub-mcp --stdio
  env HOMEHUB_URL=https://home.local  HOMEHUB_TOKEN=<token from /auth/tokens>
```

- In stdio mode it can't reach the Docker network. Instead it calls the apps
  **through nginx** with `Authorization: Bearer <PAT>`.
- `/auth/verify` already accepts API tokens (`current_user_cookie_or_token`).
- This is the user's own token for their own stack, not a token issued to the
  MCP server, so it isn't passthrough.
- The code is one adapter with two transports: internal header, or external
  bearer.
- `HOMEHUB_CA` points at the self-signed cert.
- **Zero dashboard changes needed.** This is phase 1.

### 4.3 Remote: streamable HTTP + OAuth

`https://home.local/mcp` uses the standard MCP authorization flow (OAuth 2.1).
The dashboard acts as the authorization server, because it already has the
login, TOTP and passkey screens.

- The MCP server returns `401` with
  `WWW-Authenticate: Bearer resource_metadata=…`, and serves
  `/.well-known/oauth-protected-resource`, which points at the dashboard.
- The dashboard gains these endpoints:
  - `/.well-known/oauth-authorization-server` (metadata);
  - `/oauth/register` (dynamic client registration, which ChatGPT and
    claude.ai connectors need);
  - `/oauth/authorize`: the existing login, then a one-screen "Allow *Claude*
    to use your calendar, music and library?" consent;
  - `/oauth/token`: authorization code + PKCE (S256 only), plus refresh tokens.
- Access tokens are short-lived (1 h) and bound to the MCP resource
  (`aud`/`resource`). Refresh tokens rotate.
- They're stored hashed, like `ApiToken`. The tokens page lists them as
  "Connected apps" with last-used time and a Revoke button.
- The MCP endpoint **also accepts a PAT** as a bearer. Some clients, such as
  Cursor, VS Code and several local-model front-ends, let you paste a static
  header but don't do OAuth.
- Library choice: `authlib` for the AS pieces, rather than hand-rolling the
  OAuth state machine.

### 4.4 Permissions

Per the decision, the tokens are **full access, including delete**, scoped to
that user's own data. A `read` / `write` scope split is reserved in the token
model (and checked per tool through the annotations), so a read-only token for
a less-trusted assistant is a later toggle, not a redesign.

### 4.5 Audit

Every tool call is logged to a dashboard table: user, client name, tool,
arguments with notes and bodies truncated, and result status. The log is
visible in the dashboard, so you can see what an assistant did.

---

## 5. Clients

| Client | Transport | Auth | Notes |
|---|---|---|---|
| Claude Code / Claude Desktop | stdio, or remote | PAT, or OAuth | Both work on day one with stdio |
| claude.ai / ChatGPT connectors | remote only | OAuth + DCR | **Needs public reachability** (§9.2) |
| Cursor, VS Code, Windsurf | stdio, or remote | PAT header, or OAuth | |
| Gemini CLI | stdio, or remote | PAT, or OAuth | |
| Local models (LM Studio, Open WebUI, Goose…) | mostly stdio | PAT | Benefits most from the §2 rules |
| A future home assistant on the Pi | remote, on the LAN | PAT | Your own agent loop, any model |

Check each client's current MCP support at build time; it changes month to
month.

---

## 6. Layout + deployment

```
dashboard/
  mcp/
    pyproject.toml          # mcp (official Python SDK), httpx, pydantic
    Dockerfile
    homehub_mcp/
      server.py             # FastMCP app, transports, auth middleware
      backend.py            # internal (header) vs external (bearer) app client
      tools/calendar.py
      tools/tapes.py
      tools/library.py
    tests/                  # spins the real Flask apps in-process (test clients) per tool
```

The deployment changes are:

- **Compose:** a new `mcp` service, `expose: 8100`, on the same network, with
  a healthcheck. It gets no `homehub.enable` label, so it doesn't show as a
  tile.
- **nginx:** `location /mcp` has no `auth_request`, because the MCP server must
  answer its own 401 with the `resource_metadata` header. Buffering is off and
  there are long timeouts for streaming. The `/.well-known/…` paths route
  appropriately.
- **CI + `deploy.sh`:** the new service is picked up like the others.

---

## 7. Phases

| # | Ships | Dashboard changes | App changes |
|---|---|---|---|
| 1 | Server core, stdio + PAT, calendar tools, tests | none | none |
| 2 | Tapes + library tools | none | none (optional `?q=` on tapes tracks) |
| 3 | `mcp` container, streamable HTTP, PAT bearer, nginx route, audit log | audit table + page | none |
| 4 | OAuth AS (DCR, consent, refresh, revoke) | `/oauth/*`, metadata, consent screen, "Connected apps" | none |
| 5 | Remote exposure for cloud clients | depends on §9.2 | none |

After phase 1 you can already say "log lunch with Sam tomorrow at 1" in Claude
Desktop, Cursor or a local model.

---

## 8. Testing

- **Unit tests per tool:** argument validation, result shaping, and
  error-message passthrough.
- **Integration tests:** the real calendar, tapes and library apps run in
  process with throwaway SQLite, so no real data is touched.
- **Protocol smoke test:** run the official MCP Inspector against both
  transports.
- **Cross-model check:** a scripted set of ~15 requests ("move Friday's dinner
  to 8", "what did I do with Alex last month?"), run through at least one
  Claude model, one OpenAI model and one local model. It catches schema and
  description problems that only show up with weaker tool-callers.

---

## 9. Open questions

1. **Marker privacy.** The plan is to keep it out entirely: never in output, no
   tool. Alternatively, it could be readable but not writable. Recommendation:
   keep it out; an assistant has no need for it, and transcripts end up in
   vendor logs.
2. **Cloud clients can't reach `home.local`.**
   - claude.ai and ChatGPT connectors run from the vendor's servers, so
     phase 5 needs a public route to `/mcp` and `/oauth` only:
     - Tailscale Funnel;
     - or a Cloudflare Tunnel;
     - or skip, and use only local or desktop clients plus Tailscale on your
       devices.
   - Recommendation: start LAN/Tailscale-only (phases 1–4). Decide on Funnel
     once you actually want phone-ChatGPT access.
3. **Notes in transcripts.** Diary notes and `with_who` will be sent to whatever
   model you use. That's inherent, but it could argue for a per-token "no
   notes" read mode later.
4. **Internal header hardening.** Add a shared secret the apps require
   alongside `X-Forwarded-User`? It is cheap and closes the "any container can
   impersonate" gap. Recommendation: yes, in phase 3.
5. **Time zone.** Calendar times are naive local. The server will state the
   zone in the descriptions and assume the Pi's TZ. Is that correct, or should
   there be a `TZ` setting?
