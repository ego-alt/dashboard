# homehub-mcp

A [Model Context Protocol](https://modelcontextprotocol.io) server for the home
stack. It lets any MCP-capable assistant use the **calendar**, **tapes**
(music) and **library** as you: Claude, ChatGPT, Gemini, Cursor, VS Code, or a
local model in LM Studio, Goose or Open WebUI.

> "Log dinner with Sam on Friday at 7:30", "how was my mood in March?",
> "download this album and put it on Road trip", "do I own *Piranesi*?"

The design is in [`../docs/mcp-plan.md`](../docs/mcp-plan.md). Known gaps and
follow-ups are in [`AUDIT.md`](AUDIT.md).

## Two ways to connect

| | **Local (stdio)** | **Remote (HTTP + OAuth)** |
|---|---|---|
| Runs | on your laptop, launched by the client | in the `mcp` container on the Pi |
| Reaches the apps | through nginx, with your API token | directly on the compose network |
| You sign in with | a dashboard API token | the dashboard login (+ TOTP / passkey), in the browser |
| Good for | Claude Desktop / Code, Cursor, VS Code, Gemini CLI, local models | clients that take a URL; anything on the LAN |

### Local (stdio)

1. Make an API token: dashboard → **Settings → API tokens**. It is shown once.
2. Tell your client to launch the server. For Claude Desktop, add this to
   `claude_desktop_config.json`. GUI apps don't see your shell's PATH, so give
   `uv` as a full path (`which uv`):

   ```json
   {
     "mcpServers": {
       "homehub": {
         "command": "/Users/you/.local/bin/uv",
         "args": ["run", "--directory", "/path/to/dashboard/mcp", "homehub-mcp"],
         "env": {
           "HOMEHUB_URL": "https://home.local",
           "HOMEHUB_TOKEN": "<the token>",
           "HOMEHUB_CA": "/path/to/dashboard/tls/home.crt"
         }
       }
     }
   }
   ```

   Other clients use the same command and env:
   - **Claude Code:**
     `claude mcp add homehub -e HOMEHUB_URL=… -e HOMEHUB_TOKEN=… -e HOMEHUB_CA=… -- uv run --directory /path/to/dashboard/mcp homehub-mcp`
   - **Cursor:** `~/.cursor/mcp.json`, same shape as above.
   - **Gemini CLI:** `~/.gemini/settings.json`, under `mcpServers`.
   - **VS Code:** `.vscode/mcp.json`, under `servers` with `"type": "stdio"`.

   These formats change, so check each client's docs.

`HOMEHUB_CA` is the home's self-signed certificate. Set it to `0` to skip
verification, but only on a network you trust.

### Remote (streamable HTTP)

Point the client at **`https://home.local/mcp`**. A client that speaks MCP OAuth
(Claude Code: `claude mcp add --transport http homehub https://home.local/mcp`)
then does the following:

1. It registers itself and opens the dashboard login in your browser.
2. It shows **Allow … to use your home apps?** You approve.
3. It gets a 1-hour access token that refreshes on its own.

A client that only takes a static header can send
`Authorization: Bearer <dashboard API token>` instead.

You can see and disconnect apps, and their recent activity, at
**`https://home.local/oauth/connections`**.

Two caveats:

- **TLS.** Remote clients check the certificate. Node-based clients (Claude
  Code, Cursor, VS Code) accept the home's self-signed cert with
  `NODE_EXTRA_CA_CERTS=/path/to/home.crt`. Others need a trusted cert (e.g.
  Tailscale's) or stdio.
- **Cloud clients** (claude.ai connectors, ChatGPT) connect from the vendor's
  servers, so they can't reach `home.local`. See AUDIT.md §1 for the options.

## Tools (35)

The day marker is intentionally absent: it is never read, shown or set.

| Calendar | Tapes | Library |
|---|---|---|
| `calendar_get_day` | `tapes_download` | `library_find_book` |
| `calendar_list_entries` | `tapes_list_downloads` | `library_list_books` |
| `calendar_get_entry` | `tapes_dismiss_download` | `library_get_book` |
| `calendar_search` | `tapes_search_tracks` | `library_update_book` |
| `calendar_create_entry` | `tapes_list_playlists` | `library_list_tags` |
| `calendar_update_entry` | `tapes_get_playlist` | `library_delete_book` ⚠ |
| `calendar_delete_entry` ⚠ | `tapes_create_playlist` | `library_restore_book` |
| `calendar_restore_entry` | `tapes_rename_playlist` | |
| `calendar_set_mood` | `tapes_delete_playlist` ⚠ | |
| `calendar_stats` | `tapes_add_to_playlist` | |
| | `tapes_remove_from_playlist` | |
| | `tapes_update_track` | |
| | `tapes_delete_track` ⚠ | |
| | `tapes_restore_track` | |
| | `tapes_list_podcasts` | |
| | `tapes_add_podcast` | |
| | `tapes_list_episodes` | |

There is also `homehub_now`, which gives today's date and time at home, for
models that don't know it.

⚠ marks a tool flagged `destructiveHint`, so clients that confirm before
destructive calls will ask. All deletes go to a 30-day trash and have a
restore tool, **except `tapes_delete_playlist`**, which is permanent (the app
has no playlist trash yet).

### Why the tools look the way they do

The aim is to work across models, including weak local tool-callers:

- **Tools only.** No resources or prompts, which many clients ignore.
- **Flat schemas.** There is no `anyOf`, `oneOf` or `null` anywhere. Optional
  text defaults to `''` and optional numbers to `0`.
- **Plain formats.** Dates are `YYYY-MM-DD` and times are 24-hour `HH:MM`.
  Moods are an enum.
- **Short text results** with ids inline.
- **App errors pass through verbatim** ("The end is before the start."), so the
  model can fix its call.

## Configuration

| Variable | Mode | Default |
|---|---|---|
| `HOMEHUB_URL`, `HOMEHUB_TOKEN`, `HOMEHUB_CA` | stdio | (none) |
| `MCP_PUBLIC_URL` | http | (required) How clients reach nginx; sets the OAuth issuer. |
| `DASHBOARD_URL` | http | `http://dashboard:8000` |
| `CALENDAR_URL`, `TAPES_URL`, `LIBRARY_URL` | http | the compose service names |
| `INTERNAL_AUTH_SECRET` | http | (none) Sent as `X-Internal-Auth`. See AUDIT.md §3.1. |
| `MCP_DB` | http | `/data/mcp.db` (OAuth grants + activity log) |
| `TZ` | both | `Europe/London`. Calendar times are local. |

## Development

```sh
cd mcp
uv sync --all-groups
uv run pytest -q             # fakes for the apps and the dashboard; no services needed
uvx ruff@0.9.7 check .
uv run homehub-mcp --http    # needs MCP_PUBLIC_URL; serves :8100
```

The tests drive the real HTTP app: discovery, registration, consent with
CSRF, PKCE, single-use codes, refresh rotation, revocation, API-token
fallback, audit. They also run every tool's own logic against fake apps.
