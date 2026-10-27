"""The per-IP limit on password guesses: signing in and changing your password.
Tunable via env, so it can be relaxed for a household behind one address or
tightened if abuse shows up in login_events."""
import os

from slowapi import Limiter
from slowapi.util import get_remote_address

LOGIN_RATE_LIMIT = os.environ.get("LOGIN_RATE_LIMIT", "5/minute")
limiter = Limiter(key_func=get_remote_address)
