"""The CA bundle Postgres and HTTP clients trust must not include the compromised eMudhra root."""
from __future__ import annotations

from pathlib import Path

import certifi


def test_certifi_drops_the_compromised_emsign_root():
    """GHSA-6q48-6c7w-9gw2: emSign ECC Root CA - G3 signed eight eMudhra intermediates whose keys were
    generated with almost no randomness. Certifi 2026.10.19 removes that root and keeps the unaffected
    emSign roots."""
    parts = tuple(int(part) for part in certifi.__version__.split("."))
    assert parts >= (2026, 10, 19)
    bundle = Path(certifi.where()).read_text(encoding="utf-8")
    assert "emSign ECC Root CA - G3" not in bundle
