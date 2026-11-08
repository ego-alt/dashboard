"""TOTP 2FA primitives: secret generation, code verification, recovery codes.

The ``users`` row carries the secret, an enabled flag, and a JSON list of
argon2id-hashed recovery codes (one-time use). Verification accepts both
TOTP codes and unused recovery codes — successful recovery removes the hash
so it cannot be reused.

Those three columns make one state, and only this module writes them:

  off          no secret                      start_setup →  setting-up
  setting-up   a secret, not yet confirmed     turn_on     →  on
  on           secret, enabled, codes          turn_off    →  off (from any state)

``totp_state`` is the one reading of them; nothing else looks at the columns.

The QR code is rendered server-side as SVG to avoid pulling a JS QR library
into the frontend bundle.
"""

import io
import json
import secrets
from typing import Optional, Tuple

import pyotp
import qrcode
import qrcode.image.svg

from .auth import hash_password, verify_password
from .models import User

TOTP_ISSUER = "Home Dashboard"
RECOVERY_CODE_COUNT = 10
# Tolerate ~30s of clock skew on either side. pyotp's default is 0 (exact).
TOTP_VERIFY_WINDOW = 1


def generate_secret() -> str:
    """Random base32 secret suitable for TOTP authenticators."""
    return pyotp.random_base32()


def provisioning_uri(secret: str, username: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=TOTP_ISSUER)


def render_qr_svg(uri: str) -> str:
    """Return an SVG string for the provisioning URI. No external deps used.

    One path with a viewBox: the plain ``SvgImage`` factory writes namespaced
    ``svg:rect`` elements, which don't render once the SVG is inserted into
    the page's HTML, and has no viewBox, so it can't be scaled."""
    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode("utf-8")


def verify_totp_code(secret: str, code: str) -> bool:
    """Constant-time verify against the secret with a small skew window."""
    if not secret or not code:
        return False
    code = code.strip().replace(" ", "")
    if not code.isdigit() or len(code) != 6:
        return False
    return pyotp.TOTP(secret).verify(code, valid_window=TOTP_VERIFY_WINDOW)


def generate_recovery_codes(n: int = RECOVERY_CODE_COUNT) -> list[str]:
    """Plaintext one-time recovery codes. Show once, then store only hashes."""
    return [_format_recovery(secrets.token_hex(5)) for _ in range(n)]


def _format_recovery(raw: str) -> str:
    """``abcdef0123`` → ``abcde-f0123`` for readability when typed."""
    return f"{raw[:5]}-{raw[5:]}".lower()


def hash_recovery_codes(codes: list[str]) -> str:
    """JSON-encode argon2id hashes of the codes (no plaintext at rest)."""
    return json.dumps([hash_password(_normalize_recovery(c)) for c in codes])


def _normalize_recovery(code: str) -> str:
    """Strip whitespace + dashes + casing so the user can type forgivingly."""
    return code.strip().lower().replace("-", "").replace(" ", "")


def consume_recovery_code(user: User, code: str) -> bool:
    """Try to spend a recovery code. On match, removes it from the stored list.

    Caller must ``db.commit()`` afterwards. Returns False without mutation
    when no hash matches.
    """
    if not user.totp_recovery_codes:
        return False
    normalized = _normalize_recovery(code)
    try:
        hashes: list[str] = json.loads(user.totp_recovery_codes)
    except (ValueError, TypeError):
        return False
    for i, h in enumerate(hashes):
        if verify_password(normalized, h):
            del hashes[i]
            user.totp_recovery_codes = json.dumps(hashes)
            return True
    return False


def totp_state(user: User) -> str:
    """off | setting-up | on. Enabled without a secret can't verify a code, so
    it counts as off rather than locking the account."""
    if not user.totp_secret:
        return "off"
    return "on" if user.totp_enabled else "setting-up"


def recovery_left(user: User) -> Optional[int]:
    if totp_state(user) != "on" or not user.totp_recovery_codes:
        return None
    try:
        return len(json.loads(user.totp_recovery_codes))
    except ValueError:
        return None


def start_setup(user: User) -> str:
    """off or setting-up → setting-up with a fresh secret, which is returned.
    Harmless if abandoned: nothing asks for a code until ``turn_on``."""
    user.totp_secret = generate_secret()
    user.totp_enabled = False
    user.totp_recovery_codes = None
    return user.totp_secret


def turn_on(user: User) -> list[str]:
    """setting-up → on. The caller has checked a code against the secret.
    Returns the plaintext recovery codes, shown once."""
    codes = generate_recovery_codes()
    user.totp_recovery_codes = hash_recovery_codes(codes)
    user.totp_enabled = True
    return codes


def new_recovery_codes(user: User) -> list[str]:
    """on → on, with codes that replace the old ones."""
    codes = generate_recovery_codes()
    user.totp_recovery_codes = hash_recovery_codes(codes)
    return codes


def turn_off(user: User) -> None:
    """Any state → off: turned off by its owner, or reset by an admin."""
    user.totp_secret = None
    user.totp_enabled = False
    user.totp_recovery_codes = None


def verify_totp_or_recovery(user: User, code: str) -> Tuple[bool, Optional[str]]:
    """Returns (ok, mode). ``mode`` is 'totp', 'recovery', or None on failure.

    Caller commits after a True result to persist the recovery-code removal.
    """
    if user.totp_secret and verify_totp_code(user.totp_secret, code):
        return True, "totp"
    if consume_recovery_code(user, code):
        return True, "recovery"
    return False, None
