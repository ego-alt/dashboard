"""The contract between an app repo and the home stack.

Any repo can join the stack, in any language or framework, if it has:

  Dockerfile         at the root; the image serves HTTP on `port`
  homestack.toml     this manifest
  .github/workflows/ci.yml
                     the Pi deploys a commit only after this workflow passes

A phone app (kind = "android") needs no Dockerfile: its CI publishes a signed
APK as a GitHub release, and the dashboard offers it under Services (see
app/routes/phone_apps.py).

homestack.toml (everything but `title` is optional):

    title = "Situation"              # the Services tile and the Deploy tab
    kind = "web"                     # or "android": a phone app, installed from Services
    package = "com.scanner.app"      # android only: the app's package name
    description = "World news on a map"
    icon = "icon.svg"                # an SVG in the repo, drawn in one colour like
                                     # the other tiles (stroke or fill="currentColor")
    accent = "#ffb020"               # the icon's colour on its tile; must read on the dark tile
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
KINDS = ("web", "android")
_PACKAGE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$")
ICON_MAX_BYTES = 64 * 1024
TILE_BG = "#141d28"                  # the dashboard's --color-bg-inset, behind every tile icon
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_ENV_KEY = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio of two #rrggbb colours."""
    def lum(h: str) -> float:
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


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


def required_files(kind: str) -> tuple[str, ...]:
    """What a repo of this kind needs: a phone app has no container to build."""
    return REQUIRED_FILES if kind == "web" else ("homestack.toml", ".github/workflows/ci.yml")


def parse(text: str) -> dict:
    """homestack.toml → a complete manifest with defaults, or ManifestError."""
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ManifestError(f"homestack.toml isn't valid TOML: {e}") from None
    title = str(raw.get("title") or "").strip()
    if not title:
        raise ManifestError("homestack.toml needs a title.")
    kind = str(raw.get("kind", "web")).strip().lower()
    if kind not in KINDS:
        raise ManifestError('kind must be "web" (the default) or "android".')
    package = str(raw.get("package", "")).strip()
    if kind == "android" and not _PACKAGE.match(package):
        raise ManifestError('A phone app needs its package name, like package = "com.scanner.app".')
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
    accent = str(raw.get("accent", "")).strip().lower()
    if accent and not _HEX.match(accent):
        raise ManifestError('accent must be a colour like "#ffb020".')
    if accent and contrast(accent, TILE_BG) < 3:
        raise ManifestError(f"accent {accent} is too dark to see on the tile; pick a lighter colour.")
    env = raw.get("env", {})
    if not isinstance(env, dict) or not all(_ENV_KEY.match(k) for k in env):
        raise ManifestError("env keys must be UPPER_CASE names.")
    return {
        "title": title,
        "kind": kind,
        "package": package if kind == "android" else "",
        "description": str(raw.get("description", "")).strip(),
        "icon": icon,
        "accent": accent,
        "port": port,
        "health": health,
        "data": data,
        "env": {k: str(v) for k, v in env.items()},
    }
