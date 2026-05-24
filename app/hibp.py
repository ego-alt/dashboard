"""Have-I-Been-Pwned k-anonymity password check.

Sends the first 5 hex chars of the password's SHA-1 to the public range API,
which returns all known-pwned suffixes sharing that prefix. The full hash never
leaves the box. Fail-open on network error — we'd rather let a legitimate
operator set a password than lock them out because of a transient DNS hiccup.
"""

import hashlib
import urllib.error
import urllib.request

PWNED_RANGE_URL = "https://api.pwnedpasswords.com/range/{prefix}"
_USER_AGENT = "home-dashboard-hibp-check"


def password_breach_count(password: str, *, timeout: float = 3.0) -> int:
    """Return how many breach corpora list this password.

    0 means clean (or the API was unreachable — caller can't distinguish).
    A nonzero count is the figure reported by HIBP for that hash suffix.
    """
    sha1 = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
    prefix, suffix = sha1[:5], sha1[5:]
    req = urllib.request.Request(
        PWNED_RANGE_URL.format(prefix=prefix),
        headers={"User-Agent": _USER_AGENT, "Add-Padding": "true"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("ascii", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0  # fail open
    for line in body.splitlines():
        parts = line.split(":", 1)
        if len(parts) != 2:
            continue
        if parts[0].strip().upper() == suffix:
            try:
                return int(parts[1].strip())
            except ValueError:
                return 1
    return 0


def is_password_pwned(password: str, *, timeout: float = 3.0) -> bool:
    return password_breach_count(password, timeout=timeout) > 0
