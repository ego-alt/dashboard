# __TITLE__

__DESCRIPTION__

Part of the home stack: served at `/__NAME__/` behind the [dashboard](https://github.com/ego-alt/dashboard), which signs people in. Commits to `main` that pass CI deploy to the Pi on their own.

## Run it

```sh
uv sync
uv run flask --app app:create_app run --port 8000   # http://127.0.0.1:8000
```

Tests and lint: `uv run pytest` and `uvx ruff check .`
