"""Independent recovery and policy-application checks, including interrupted file copies."""
import shutil
import sqlite3
import subprocess
import sys

import pytest

from scp import backup as backups
from scp.companies.store import Companies
from scp.versions.store import Store

from .factory import base


def database(path, name):
    store = Store(path)
    companies = Companies(store)
    account = companies.signup("recovery@example.test", "Recovery", "recovery-test-password")
    data = base()
    data["settings"]["company_name"] = name
    companies.create(account.user, data)
    store.db.close()


def company_name(path):
    db = sqlite3.connect(path)
    try:
        return db.execute("SELECT name FROM companies").fetchone()[0]
    finally:
        db.close()


def test_restore_can_restore_the_previous_database_copy(tmp_path):
    live = tmp_path / "live.sqlite"
    source = tmp_path / "source.sqlite"
    database(live, "Before")
    database(source, "After")
    kept = backups.restore(source, live)
    assert company_name(live) == "After"
    assert company_name(kept) == "Before"
    backups.restore(kept, live)
    assert company_name(live) == "Before"


def test_interrupted_restore_leaves_the_current_database_intact(tmp_path, monkeypatch):
    live = tmp_path / "live.sqlite"
    source = tmp_path / "source.sqlite"
    database(live, "Current")
    database(source, "Replacement")
    before = live.read_bytes()
    original_copy = shutil.copy2

    def interrupted(src, dst, *args, **kwargs):
        if str(src) == str(source.resolve()):
            with open(dst, "wb") as stream:
                stream.write(b"partial database")
            raise OSError("simulated full disk during copy")
        return original_copy(src, dst, *args, **kwargs)

    monkeypatch.setattr(shutil, "copy2", interrupted)
    with pytest.raises(OSError, match="simulated full disk"):
        backups.restore(source, live)
    assert live.read_bytes() == before
    assert company_name(live) == "Current"


def test_restore_into_a_new_server_directory(tmp_path):
    source = tmp_path / "source.sqlite"
    database(source, "Recovered")
    live = tmp_path / "new-server" / "state" / "scp.sqlite"
    backups.restore(source, live)
    assert company_name(live) == "Recovered"


def test_invalid_backup_leaves_the_current_database_intact(tmp_path):
    live = tmp_path / "live.sqlite"
    source = tmp_path / "invalid.sqlite"
    database(live, "Current")
    source.write_bytes(b"invalid database")
    before = live.read_bytes()
    with pytest.raises(sqlite3.DatabaseError):
        backups.restore(source, live)
    assert live.read_bytes() == before


def test_backup_check_accepts_uri_punctuation_in_file_names(tmp_path):
    path = tmp_path / "company #1.sqlite"
    database(path, "Punctuation")
    assert backups.check(path) == ["1 accounts", "Punctuation (revision 1)"]


def test_restore_of_the_current_file_is_refused_without_changes(tmp_path):
    live = tmp_path / "live.sqlite"
    database(live, "Current")
    before = live.read_bytes()
    with pytest.raises(ValueError, match="different files"):
        backups.restore(live, live)
    assert live.read_bytes() == before


def test_recovery_copy_includes_committed_wal_pages(tmp_path):
    live = tmp_path / "live.sqlite"
    source = tmp_path / "source.sqlite"
    database(live, "Before")
    database(source, "Replacement")
    # An abruptly stopped writer leaves committed data in the WAL; no live server is touched.
    subprocess.run([sys.executable, "-c", """
import os, sqlite3, sys
db = sqlite3.connect(sys.argv[1])
db.execute('PRAGMA journal_mode=WAL')
db.execute('PRAGMA wal_autocheckpoint=0')
db.execute("UPDATE companies SET name='Committed'")
db.commit()
os._exit(0)
""", str(live)], check=True)
    assert live.with_name(live.name + "-wal").exists()
    kept = backups.restore(source, live)
    assert company_name(live) == "Replacement"
    assert company_name(kept) == "Committed"


def test_failed_install_keeps_current_database_and_cleans_staging(tmp_path, monkeypatch):
    live = tmp_path / "live.sqlite"
    source = tmp_path / "source.sqlite"
    database(live, "Current")
    database(source, "Replacement")
    original_replace = backups.os.replace

    def refused(src, dst):
        if str(dst) == str(live):
            raise PermissionError("simulated locked destination")
        return original_replace(src, dst)

    monkeypatch.setattr(backups.os, "replace", refused)
    with pytest.raises(PermissionError, match="locked destination"):
        backups.restore(source, live)
    assert company_name(live) == "Current"
    assert company_name(live.with_name(live.name + ".before-restore")) == "Current"
    assert not list(tmp_path.glob(".*.restore"))
