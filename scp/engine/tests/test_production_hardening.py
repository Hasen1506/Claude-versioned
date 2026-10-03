"""Account isolation, payment/stock boundaries and recovery checks from the production audit."""
from datetime import UTC, datetime

import pytest

from scp.backup import backup
from scp.companies import CompanyError, get_companies
from scp.api.companies import require_signin, signup_policy
from scp.purchasing import PurchasingError, act
from scp.sales import (
    SalesError, create_deliveries, create_invoices, create_return, credit_return, issue, pay, receive_return,
)

from .test_connections import client, company, h, setup
from .test_order_to_cash import taken
from .test_procure_to_pay import received


def billed():
    x, _ = taken()
    x, _ = create_deliveries(x)
    x, _ = issue(x, "DL-00001")
    return create_invoices(x)[0]


def test_company_owner_cannot_reset_an_account_with_access_to_another_company():
    owner, cid, _ = setup()
    victim = client.post("/api/auth/signup", json={"email": "victim@example.com", "name": "Victim",
                                                 "password": "correct horse"}).json()["token"]
    private = client.post("/api/companies", headers=h(victim), json={"dataset": company()}).json()["id"]
    r = client.post(f"/api/companies/{cid}/members", headers=h(owner), json={"email": "victim@example.com", "role": "viewer"})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/companies/{cid}/members/victim@example.com/reset", headers=h(owner))
    assert r.status_code == 403, "Company membership must not grant a reset link for a global account"
    assert client.get(f"/api/companies/{private}", headers=h(victim)).status_code == 200


def test_password_change_revokes_other_sessions_and_pending_reset_links_but_keeps_current_session():
    owner, _, _ = setup()
    other = client.post("/api/auth/signin", json={"email": "owner@example.com", "password": "correct horse"}).json()["token"]
    reset = get_companies().reset_token("owner@example.com")
    r = client.post("/api/auth/password", headers=h(owner), json={"old": "correct horse", "new": "another horse"})
    assert r.status_code == 200, r.text
    assert client.get("/api/auth/me", headers=h(owner)).status_code == 200
    assert client.get("/api/auth/me", headers=h(other)).status_code == 401
    assert client.post("/api/auth/reset", json={"token": reset, "password": "stolen password"}).status_code == 410


def test_passwordless_sso_accounts_cannot_get_password_reset_tokens():
    setup()
    c = get_companies()
    c.sso_session("issuer:subject", "sso@example.com", "SSO user", "open")
    assert c.reset_token("sso@example.com") is None


@pytest.mark.parametrize("kind", ["session", "reset"])
def test_auth_tokens_are_expired_at_the_exact_expiry_instant(monkeypatch, kind):
    import scp.companies.store as store
    owner, _, _ = setup()
    c = get_companies()
    now = datetime(2026, 10, 3, 12, tzinfo=UTC)
    monkeypatch.setattr(store, "_now", lambda: now)
    if kind == "session":
        c.db.execute("UPDATE sessions SET expires_at = ?", (now.isoformat(),))
        with pytest.raises(CompanyError):
            c.whoami(owner)
    else:
        token = c.reset_token("owner@example.com", hours=0)
        with pytest.raises(CompanyError):
            c.reset_password(token, "another horse")


@pytest.mark.parametrize("variable,value,check", [
    ("SCP_SIGNUP", "invte", signup_policy), ("SCP_REQUIRE_SIGNIN", "ture", require_signin),
])
def test_invalid_security_configuration_does_not_silently_enable_public_access(monkeypatch, variable, value, check):
    monkeypatch.setenv(variable, value)
    with pytest.raises(CompanyError, match=variable):
        check()


def test_duplicate_delivery_lines_cannot_exceed_the_order_quantity():
    x, _ = taken()
    with pytest.raises(SalesError, match="still to deliver"):
        create_deliveries(x, [{"order": "SO-00001/10", "qty": 20}, {"order": "SO-00001/10", "qty": 20}])


def test_a_delivery_can_split_an_order_into_batches_within_its_total_quantity():
    x, _ = taken()
    x, _ = create_deliveries(x, [{"order": "SO-00001/10", "qty": 10}, {"order": "SO-00001/10", "qty": 15}])
    assert sum(ln.qty for dl in x.deliveries for ln in dl.lines) == 25


@pytest.mark.parametrize("quantity", [0, -1, float("nan"), float("inf")])
def test_invalid_explicit_delivery_quantities_are_domain_errors(quantity):
    x, _ = taken()
    with pytest.raises(SalesError):
        create_deliveries(x, [{"order": "SO-00001/10", "qty": quantity}])


def test_partial_return_receipt_releases_the_unreceived_balance_for_another_return():
    x = billed()
    x, _ = create_return(x, "K", "A", 10, order="SO-00001/10")
    x, _ = receive_return(x, "RET-00001", qty=3)
    x, _ = credit_return(x, "RET-00001")
    x, _ = create_return(x, "K", "A", 22, order="SO-00001/10")
    assert x.returns[-1].qty == 22
    with pytest.raises(SalesError):
        create_return(x, "K", "A", 1, order="SO-00001/10")  # the new outstanding return reserves its quantity


@pytest.mark.parametrize("supplier", [False, True])
def test_nonfinite_payment_amounts_are_domain_errors(supplier):
    if supplier:
        x, _ = act(received(), "enter_invoice", "PO-00001")
        with pytest.raises(PurchasingError):
            act(x, "pay_invoice", "SI-00001", amount=float("nan"))
    else:
        with pytest.raises(SalesError):
            pay(billed(), "INV-00001", amount=float("nan"))


def test_nonfinite_nested_quantities_are_rejected_at_the_http_boundary():
    x, _ = taken()
    r = client.post("/api/sales/act", json={"dataset": x.model_dump(mode="json"), "action": "create_deliveries",
                                          "lines": [{"order": "SO-00001/10", "qty": "NaN"}]})
    assert r.status_code == 422, r.text


def test_password_change_rolls_back_if_session_revocation_fails():
    import sqlite3
    owner, _, _ = setup()
    c = get_companies()
    user = c.whoami(owner)
    reset = c.reset_token(user.email)
    c.db.execute("CREATE TRIGGER fail_revoke BEFORE DELETE ON sessions BEGIN SELECT RAISE(ABORT, 'simulated'); END")
    with pytest.raises(sqlite3.IntegrityError):
        c.change_password(user, "correct horse", "another horse")
    c.db.execute("DROP TRIGGER fail_revoke")
    assert c.signin(user.email, "correct horse").user.id == user.id
    assert c.reset_password(reset, "third password").user.id == user.id  # recovery link was not invalidated


def test_backups_taken_in_the_same_second_do_not_overwrite_each_other(tmp_path):
    setup()
    c = get_companies()
    now = datetime(2026, 10, 3, 12, tzinfo=UTC)
    first = backup(c.db, tmp_path, keep=2, now=now)
    original = first.read_bytes()
    c.db.execute("UPDATE companies SET name = 'Changed after first backup'")
    second = backup(c.db, tmp_path, keep=2, now=now)
    assert first != second
    assert first.read_bytes() == original
    assert len(list(tmp_path.glob("scp-*.sqlite"))) == 2


def test_failed_backup_does_not_publish_a_partial_file(tmp_path):
    class BrokenDatabase:
        def backup(self, _target):
            raise OSError("simulated interrupted copy")
    with pytest.raises(OSError):
        backup(BrokenDatabase(), tmp_path)
    assert not list(tmp_path.iterdir())


def test_return_spanning_partial_invoices_credits_each_original_rate_and_only_once():
    from scp.sales import cancel_invoice
    x, _ = taken()
    x, _ = create_deliveries(x, [{"order": "SO-00001/10", "qty": 5}])
    x, _ = issue(x, "DL-00001")
    x, _ = create_invoices(x)
    x = x.model_copy(update={"customers": [c.model_copy(update={"tax_rate": 0.2}) for c in x.customers]})
    x, _ = create_deliveries(x, [{"order": "SO-00001/10", "qty": 20}])
    x, _ = issue(x, "DL-00002")
    x, _ = create_invoices(x)
    x, _ = create_return(x, "K", "A", 20, order="SO-00001/10")
    x, _ = receive_return(x, "RET-00001")
    x, report = credit_return(x, "RET-00001")
    credits = [i for i in x.invoices if i.kind == "credit_note"]
    assert [(i.reference, sum(ln.qty for ln in i.lines), i.tax_rate) for i in credits] == [
        ("INV-00001", 5, 0.1), ("INV-00002", 15, 0.2)]
    assert sum(i.tax for i in credits) == pytest.approx(266)
    assert report.documents == ["CN-00001", "CN-00002", "RET-00001"]
    x, _ = cancel_invoice(x, "CN-00001")
    x, _ = credit_return(x, "RET-00001")
    active = [i for i in x.invoices if i.kind == "credit_note" and not i.cancelled]
    assert sum(ln.qty for i in active for ln in i.lines) == 20  # only the cancelled five are credited again
    with pytest.raises(SalesError, match="already been credited"):
        credit_return(x, "RET-00001")
