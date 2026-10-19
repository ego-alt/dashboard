"""The contract between an app repo and the home stack.

Any repo can join the stack, in any language or framework, if it has:

  Dockerfile         at the root; the image serves HTTP on `port`
  homestack.toml     this manifest
  .github/workflows/ci.yml
                     the Pi deploys a commit only after this workflow passes

homestack.toml (everything but `title` is optional):

    title = "Situation"              # the Services tile and the Deploy tab
    description = "World news on a map"
    icon = "icon.svg"                # an SVG in the repo, drawn in one colour like
                                     # the other tiles (stroke or fill="currentColor")
    port = 8000                      # the port the container listens on
    health = "/healthz"              # a path that answers 2xx when the app is up
    data = "/app/instance"           # a folder kept across deploys
                                     # (on the Pi: <stack>/<name>/instance)

    [env]                            # extra environment; "${VAR}" reads the Pi's .env
    NTFY_TOPIC = "${NTFY_TOPIC}"

The app is served at /<name>/ (its repo's name) behind the dashboard's
sign-in. Every request carries X-Forwarded-User (who) and X-Forwarded-Prefix
(/<name>), and the container gets APPLICATION_ROOT=/<name> and
AUTH_PROXY_HEADER=X-Forwarded-User.

Standard library only: the Pi's deploy script imports this too.
"""
import re
import tomllib

NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
# Routes the stack already uses, and containers it already runs.
RESERVED = {"dashboard", "library", "calendar", "music", "tapes", "mcp", "nginx", "home-nginx",
            "api", "auth", "login", "logout", "oauth", "static", "assets", "admin", "settings",
            "monitor", "users", "me", "backups", "deploy", "healthz", "ping", "authorize", "token",
            "register", "revoke"}
REQUIRED_FILES = ("Dockerfile", "homestack.toml", ".github/workflows/ci.yml")
ICON_MAX_BYTES = 64 * 1024
_ENV_KEY = re.compile(r"^[A-Z_][A-Z0-9_]*$")


class ManifestError(ValueError):
    """A manifest that can't be used; the message says what to fix."""


def app_name(repo: str) -> str:
    """owner/Repo-Name → repo-name (the route and container name)."""
    return repo.rsplit("/", 1)[-1].lower()


def name_problem(name: str) -> str | None:
    if not NAME_RE.match(name):
        return "The repo name must be lowercase letters, digits and dashes, starting with a letter."
    if name in RESERVED:
        return f"/{name}/ is already used by the stack; rename the repo."
    return None


def parse(text: str) -> dict:
    """homestack.toml → a complete manifest with defaults, or ManifestError."""
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ManifestError(f"homestack.toml isn't valid TOML: {e}") from None
    title = str(raw.get("title") or "").strip()
    if not title:
        raise ManifestError("homestack.toml needs a title.")
    port = raw.get("port", 8000)
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise ManifestError("port must be a number between 1 and 65535.")
    health = str(raw.get("health", "/healthz"))
    if not health.startswith("/"):
        raise ManifestError("health must be a path starting with /.")
    data = raw.get("data")
    if data is not None and not (isinstance(data, str) and data.startswith("/")):
        raise ManifestError("data must be an absolute path inside the container, like /app/instance.")
    icon = str(raw.get("icon", "")).strip()
    if icon and not (icon.endswith(".svg") and not icon.startswith("/") and ".." not in icon.split("/")):
        raise ManifestError("icon must be the path of an .svg file in the repo, like icon.svg.")
    env = raw.get("env", {})
    if not isinstance(env, dict) or not all(_ENV_KEY.match(k) for k in env):
        raise ManifestError("env keys must be UPPER_CASE names.")
    return {
        "title": title,
        "description": str(raw.get("description", "")).strip(),
        "icon": icon,
        "port": port,
        "health": health,
        "data": data,
        "env": {k: str(v) for k, v in env.items()},
    }
