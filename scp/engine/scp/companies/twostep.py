"""Two-step sign-in (ENTERPRISE_PLAN 1.3): a six-digit code from an authenticator app (TOTP, RFC 6238: HMAC-SHA1,
30-second steps, the one before and after accepted for a clock that is a little off), and one-time recovery codes for
a lost phone. Only the standard library: any authenticator app (Google Authenticator, Microsoft Authenticator,
1Password, Authy …) reads the key or the ``otpauth://`` link."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP = 30                     # seconds per code
DIGITS = 6
WINDOW = 1                    # steps either side accepted
RECOVERY_CODES = 10
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"   # no 0/o, 1/l/i: read off paper


def new_secret() -> str:
    """A fresh key: 160 random bits, base32 without padding (what authenticator apps take)."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret: str) -> bytes:
    s = secret.strip().replace(" ", "").upper()
    return base64.b32decode(s + "=" * (-len(s) % 8))


def code_at(secret: str, step: int) -> str:
    """The code for time step ``step`` (RFC 4226 dynamic truncation)."""
    mac = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    o = mac[-1] & 0x0F
    n = (struct.unpack(">I", mac[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** DIGITS
    return f"{n:0{DIGITS}d}"


def now_step(at: float | None = None) -> int:
    return int((time.time() if at is None else at) // STEP)


def check(secret: str, code: str, after: int = -1, at: float | None = None) -> int | None:
    """The time step ``code`` belongs to, if it is right now (within the window) and later than ``after`` (a code is
    good once: the step last used is passed back here); else None."""
    code = "".join(ch for ch in code if ch.isdigit())
    if len(code) != DIGITS:
        return None
    here = now_step(at)
    for step in range(here - WINDOW, here + WINDOW + 1):
        if step > after and hmac.compare_digest(code_at(secret, step), code):
            return step
    return None


def uri(secret: str, account: str, issuer: str) -> str:
    """The ``otpauth://`` link an authenticator app opens (or reads from a QR code)."""
    label = quote(f"{issuer}:{account}", safe="")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer, safe='')}&algorithm=SHA1&digits={DIGITS}&period={STEP}"


def grouped(secret: str) -> str:
    """The key in groups of four, to type into an app by hand."""
    return " ".join(secret[i:i + 4] for i in range(0, len(secret), 4))


def recovery_codes(n: int = RECOVERY_CODES) -> list[str]:
    """``n`` one-time codes such as ``k7pm-x3qa-9t``: about 50 bits each."""
    def one() -> str:
        s = "".join(secrets.choice(_ALPHABET) for _ in range(10))
        return f"{s[:4]}-{s[4:8]}-{s[8:]}"
    return [one() for _ in range(n)]


def normal_recovery(code: str) -> str:
    """A recovery code as typed (any case, spaces or dashes) in the form it is kept."""
    return "".join(ch for ch in code.lower() if ch.isalnum())


def recovery_hash(code: str) -> str:
    return hashlib.sha256(("scp-recovery:" + normal_recovery(code)).encode()).hexdigest()
