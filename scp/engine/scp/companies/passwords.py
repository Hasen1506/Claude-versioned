"""Password policy (roadmap D, UX audit section 4): long enough, not a known breached or common password, not the
account's own e-mail, and not one character repeated. The breached list is a small offline list of the most common
leaked passwords (the head of public breach corpora): no network call, nothing sent anywhere.

Server setting: ``SCP_PASSWORD_MIN`` (default 12) — the shortest password accepted for a new account, a reset or a
change. Existing passwords keep working: the policy applies when a password is set.
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

from .store import CompanyError

_LIST = Path(__file__).with_name("common_passwords.txt")


def min_length() -> int:
    try:
        return max(8, int(os.environ.get("SCP_PASSWORD_MIN", "").strip() or 12))
    except ValueError:
        return 12


@lru_cache(maxsize=1)
def common() -> frozenset[str]:
    return frozenset(x.strip().lower() for x in _LIST.read_text().splitlines() if x.strip() and not x.startswith("#"))


def _squash(pw: str) -> str:
    """The password without spaces, digits and punctuation at its ends: "Password123!" → "password"."""
    return re.sub(r"^[\W\d_]+|[\W\d_]+$", "", pw.lower().replace(" ", ""))


def problem(password: str, email: str | None = None) -> str | None:
    """Why this password is refused, in words for the person typing it; None when it is fine."""
    n = min_length()
    if len(password) < n:
        return f"a password needs at least {n} characters"
    low = password.lower()
    if low in common() or _squash(password) in common() or low.replace(" ", "") in common():
        return "that password is on lists of breached passwords; choose another"
    if len(set(low)) < 4:
        return "that password repeats too few characters; choose another"
    local = (email or "").split("@")[0].lower()
    if len(local) >= 4 and local in low:
        return "a password must not contain your e-mail address"
    return None


def check(password: str, email: str | None = None) -> None:
    why = problem(password, email)
    if why:
        raise CompanyError(why, 422)
