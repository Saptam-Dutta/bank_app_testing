"""API / backend testing: auth, accounts, transactions, admin, security (API-xxx).

Merged from: test_api_auth.py, test_api_accounts.py, test_api_transactions.py, test_api_admin.py, test_api_security.py.
"""
import base64
import config
import json
import jwt
import pytest
import time
from api_client import parallel
from decimal import Decimal
from helpers import audit_count, balance, one, rows, run, scalar, total_balance


# ============================================================================
# api auth
# ============================================================================

NEW_USER = {"name": "Carol White", "email": "carol@example.com", "password": "Secret123!", "phone": "9123456780"}


# ---------------------------------------------------------------- register
@pytest.mark.api
def test_API_AUT_01_register_with_valid_data(api, db):
    r = api.post("/api/auth/register", json=NEW_USER)
    assert r.status_code == 201
    uid = r.json()["user_id"]
    row = one(db, "SELECT name, email, role FROM users WHERE user_id = %s", (uid,))
    assert row == {"name": "Carol White", "email": "carol@example.com", "role": "customer"}


@pytest.mark.api
def test_API_AUT_02_new_user_can_log_in_straight_away(api):
    api.post("/api/auth/register", json=NEW_USER)
    r = api.post("/api/auth/login", json={"email": NEW_USER["email"], "password": NEW_USER["password"]})
    assert r.status_code == 200 and r.json()["token"]


@pytest.mark.api
def test_API_AUT_03_phone_is_optional(api):
    body = {k: v for k, v in NEW_USER.items() if k != "phone"}
    assert api.post("/api/auth/register", json=body).status_code == 201


@pytest.mark.api
@pytest.mark.parametrize("missing", ["name", "email", "password"])
def test_API_AUT_04_missing_required_field_returns_400(api, missing):
    body = {k: v for k, v in NEW_USER.items() if k != missing}
    assert api.post("/api/auth/register", json=body).status_code == 400


@pytest.mark.api
def test_API_AUT_05_empty_body_returns_400(api):
    assert api.post("/api/auth/register", json={}).status_code == 400


@pytest.mark.api
def test_API_AUT_06_duplicate_email_returns_409(api):
    r = api.post("/api/auth/register", json={**NEW_USER, "email": "alice@example.com"})
    assert r.status_code == 409


@pytest.mark.api
def test_API_AUT_07_duplicate_email_is_case_insensitive(api):
    r = api.post("/api/auth/register", json={**NEW_USER, "email": "ALICE@Example.com"})
    assert r.status_code == 409


@pytest.mark.api
@pytest.mark.parametrize("email", ["plainaddress", "no-at-sign.com", "a@b", "a b@c.com", "@example.com", ""])
def test_API_AUT_08_invalid_email_format_returns_400(api, email):
    assert api.post("/api/auth/register", json={**NEW_USER, "email": email}).status_code == 400


@pytest.mark.api
def test_API_AUT_09_password_shorter_than_8_returns_400(api):
    assert api.post("/api/auth/register", json={**NEW_USER, "password": "1234567"}).status_code == 400


@pytest.mark.api
def test_API_AUT_10_password_of_exactly_8_is_accepted(api):
    """Boundary value."""
    assert api.post("/api/auth/register", json={**NEW_USER, "password": "12345678"}).status_code == 201


@pytest.mark.api
def test_API_AUT_11_password_longer_than_72_bytes_returns_400(api):
    """bcrypt silently ignores everything after 72 bytes, so longer passwords are refused."""
    assert api.post("/api/auth/register", json={**NEW_USER, "password": "a" * 73}).status_code == 400


@pytest.mark.api
def test_API_AUT_12_name_longer_than_100_returns_400(api):
    assert api.post("/api/auth/register", json={**NEW_USER, "name": "N" * 101}).status_code == 400


@pytest.mark.api
def test_API_AUT_13_name_of_exactly_100_is_accepted(api):
    assert api.post("/api/auth/register", json={**NEW_USER, "name": "N" * 100}).status_code == 201


@pytest.mark.api
@pytest.mark.parametrize("phone", ["12345", "abcdefghij", "9" * 16, "98765 43210", 9876543210])
def test_API_AUT_14_invalid_phone_returns_400(api, phone):
    assert api.post("/api/auth/register", json={**NEW_USER, "phone": phone}).status_code == 400


@pytest.mark.api
@pytest.mark.parametrize("field,value", [("name", 123), ("email", {"a": 1}), ("password", ["x"]), ("name", True)])
def test_API_AUT_15_wrong_data_types_return_400_not_500(api, field, value):
    assert api.post("/api/auth/register", json={**NEW_USER, field: value}).status_code == 400


@pytest.mark.api
def test_API_AUT_16_password_is_stored_as_bcrypt_hash_not_plaintext(api, db):
    api.post("/api/auth/register", json=NEW_USER)
    stored = scalar(db, "SELECT password_hash FROM users WHERE email = %s", (NEW_USER["email"],))
    assert stored != NEW_USER["password"] and stored.startswith("$2") and len(stored) == 60


@pytest.mark.api
def test_API_AUT_17_same_password_gets_different_hashes(api, db):
    api.post("/api/auth/register", json=NEW_USER)
    api.post("/api/auth/register", json={**NEW_USER, "email": "dave@example.com"})
    hashes = [r["password_hash"] for r in rows(db, "SELECT password_hash FROM users WHERE user_id > 3")]
    assert len(hashes) == 2 and hashes[0] != hashes[1]       # per-user salt


@pytest.mark.api
def test_API_AUT_18_cannot_register_as_admin(api, db):
    r = api.post("/api/auth/register", json={**NEW_USER, "role": "admin"})
    assert r.status_code == 201
    assert scalar(db, "SELECT role FROM users WHERE user_id = %s", (r.json()["user_id"],)) == "customer"


@pytest.mark.api
def test_API_AUT_19_simultaneous_duplicate_registrations_give_one_201_and_rest_409(api, db):
    """Race condition: 6 identical registrations at once must never produce a 500."""
    results = parallel([lambda: api.post("/api/auth/register", json=NEW_USER).status_code for _ in range(6)])
    assert results.count(201) == 1
    assert results.count(409) == 5
    assert scalar(db, "SELECT COUNT(*) FROM users WHERE email = %s", (NEW_USER["email"],)) == 1


@pytest.mark.api
def test_API_AUT_20_malformed_json_returns_400(api):
    r = api.post("/api/auth/register", data="{not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 400 and "error" in r.json()


@pytest.mark.api
def test_API_AUT_21_email_is_stored_in_lower_case(api, db):
    api.post("/api/auth/register", json={**NEW_USER, "email": "Carol@Example.COM"})
    assert scalar(db, "SELECT email FROM users WHERE user_id > 3") == "carol@example.com"


# ------------------------------------------------------------------- login
@pytest.mark.api
def test_API_AUT_22_login_with_valid_credentials(api):
    r = api.post("/api/auth/login", json={"email": "alice@example.com", "password": "password123"})
    body = r.json()
    assert r.status_code == 200
    assert body["token"] and body["user"]["email"] == "alice@example.com" and body["user"]["role"] == "customer"


@pytest.mark.api
def test_API_AUT_23_admin_login_returns_admin_role(api):
    r = api.post("/api/auth/login", json={"email": "admin@example.com", "password": "password123"})
    assert r.status_code == 200 and r.json()["user"]["role"] == "admin"


@pytest.mark.api
def test_API_AUT_24_wrong_password_returns_401(api):
    r = api.post("/api/auth/login", json={"email": "alice@example.com", "password": "wrong-password"})
    assert r.status_code == 401


@pytest.mark.api
def test_API_AUT_25_unknown_email_returns_same_401_as_wrong_password(api):
    wrong_pw = api.post("/api/auth/login", json={"email": "alice@example.com", "password": "nope"})
    no_user = api.post("/api/auth/login", json={"email": "nobody@example.com", "password": "nope"})
    assert no_user.status_code == 401
    assert no_user.json() == wrong_pw.json()          # no hint about which emails exist


@pytest.mark.api
@pytest.mark.parametrize("body", [{}, {"email": "alice@example.com"}, {"password": "password123"},
                                  {"email": "", "password": ""}])
def test_API_AUT_26_missing_credentials_return_400(api, body):
    assert api.post("/api/auth/login", json=body).status_code == 400


@pytest.mark.api
def test_API_AUT_27_login_email_is_case_insensitive(api):
    r = api.post("/api/auth/login", json={"email": "ALICE@EXAMPLE.COM", "password": "password123"})
    assert r.status_code == 200


@pytest.mark.api
@pytest.mark.parametrize("body", [{"email": {"$ne": None}, "password": "x"},
                                  {"email": "alice@example.com", "password": {"$ne": None}},
                                  {"email": ["alice@example.com"], "password": "password123"}])
def test_API_AUT_28_non_string_credentials_return_400(api, body):
    assert api.post("/api/auth/login", json=body).status_code == 400


@pytest.mark.api
def test_API_AUT_29_token_contains_identity_and_expires_in_two_hours(api):
    token = api.login("alice@example.com")
    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["user_id"] == 1 and claims["email"] == "alice@example.com" and claims["role"] == "customer"
    assert claims["exp"] - claims["iat"] == 2 * 60 * 60


@pytest.mark.api
def test_API_AUT_30_login_response_never_contains_password_data(api):
    r = api.post("/api/auth/login", json={"email": "alice@example.com", "password": "password123"})
    assert "password" not in r.text.lower() and "$2b$" not in r.text


# ---------------------------------------------------------------- profile
@pytest.mark.api
def test_API_AUT_31_me_returns_the_logged_in_user(api, alice):
    r = api.get("/api/auth/me", alice)
    assert r.status_code == 200
    assert r.json()["email"] == "alice@example.com" and "password_hash" not in r.json()


@pytest.mark.api
def test_API_AUT_32_me_without_token_returns_401(api):
    assert api.get("/api/auth/me").status_code == 401


@pytest.mark.api
def test_API_AUT_33_me_with_garbage_token_returns_401(api):
    assert api.get("/api/auth/me", "not.a.token").status_code == 401


@pytest.mark.api
def test_API_AUT_34_update_profile_changes_name_and_phone(api, alice, db):
    r = api.put("/api/auth/me", alice, {"name": "Alice Updated", "phone": "9000000001"})
    assert r.status_code == 200 and r.json()["user"]["name"] == "Alice Updated"
    assert one(db, "SELECT name, phone FROM users WHERE user_id = 1") == {"name": "Alice Updated", "phone": "9000000001"}


@pytest.mark.api
def test_API_AUT_35_update_profile_without_name_returns_400(api, alice):
    assert api.put("/api/auth/me", alice, {"phone": "9000000001"}).status_code == 400


@pytest.mark.api
def test_API_AUT_36_update_profile_cannot_change_email_or_role(api, alice, db):
    api.put("/api/auth/me", alice, {"name": "Alice", "email": "evil@example.com", "role": "admin"})
    assert one(db, "SELECT email, role FROM users WHERE user_id = 1") == {"email": "alice@example.com", "role": "customer"}


@pytest.mark.api
def test_API_AUT_37_update_profile_with_overlong_name_returns_400(api, alice):
    assert api.put("/api/auth/me", alice, {"name": "N" * 101}).status_code == 400


@pytest.mark.api
def test_API_AUT_38_update_profile_with_invalid_phone_returns_400(api, alice):
    assert api.put("/api/auth/me", alice, {"name": "Alice", "phone": "abc"}).status_code == 400


@pytest.mark.api
def test_API_AUT_39_update_profile_only_affects_the_logged_in_user(api, alice, db):
    api.put("/api/auth/me", alice, {"name": "Changed"})
    assert scalar(db, "SELECT name FROM users WHERE user_id = 2") == "Bob Smith"

# ============================================================================
# api accounts
# ============================================================================

def D(value):
    return Decimal(str(value))


@pytest.mark.api
def test_API_ACC_01_list_returns_only_my_accounts_with_branch_details(api, alice):
    r = api.get("/api/accounts", alice)
    assert r.status_code == 200
    data = r.json()
    assert [a["account_id"] for a in data] == [1]
    assert data[0]["branch_name"] == "Main Street Branch" and data[0]["ifsc_code"] == "BANK0001234"
    assert D(data[0]["balance"]) == 5000


@pytest.mark.api
def test_API_ACC_02_another_user_sees_only_their_own_accounts(api, bob):
    assert [a["account_id"] for a in api.get("/api/accounts", bob).json()] == [2]


@pytest.mark.api
def test_API_ACC_03_list_requires_login(api):
    assert api.get("/api/accounts").status_code == 401


@pytest.mark.api
def test_API_ACC_04_get_own_account_by_id(api, alice):
    r = api.get("/api/accounts/1", alice)
    assert r.status_code == 200 and r.json()["account_id"] == 1 and D(r.json()["balance"]) == 5000


@pytest.mark.api
def test_API_ACC_05_cannot_read_someone_elses_account(api, alice):
    assert api.get("/api/accounts/2", alice).status_code == 404


@pytest.mark.api
def test_API_ACC_06_nonexistent_account_returns_404(api, alice):
    assert api.get("/api/accounts/99999", alice).status_code == 404


@pytest.mark.api
@pytest.mark.parametrize("bad_id", ["abc", "0", "-1", "1.5", "1%20OR%201=1", "99999999999"])
def test_API_ACC_07_invalid_account_id_returns_400(api, alice, bad_id):
    assert api.get(f"/api/accounts/{bad_id}", alice).status_code == 400


@pytest.mark.api
def test_API_ACC_08_create_savings_account(api, alice, db):
    r = api.post("/api/accounts", alice, {"branch_id": 2, "account_type": "savings"})
    assert r.status_code == 201
    row = one(db, "SELECT user_id, branch_id, account_type, balance, status FROM accounts WHERE account_id = %s",
              (r.json()["account_id"],))
    assert row["user_id"] == 1 and row["branch_id"] == 2 and row["account_type"] == "savings"
    assert row["balance"] == 0 and row["status"] == "active"


@pytest.mark.api
def test_API_ACC_09_create_current_account(api, alice):
    assert api.post("/api/accounts", alice, {"branch_id": 1, "account_type": "current"}).status_code == 201


@pytest.mark.api
def test_API_ACC_10_new_account_appears_in_my_list(api, alice):
    new_id = api.post("/api/accounts", alice, {"branch_id": 3, "account_type": "savings"}).json()["account_id"]
    assert new_id in [a["account_id"] for a in api.get("/api/accounts", alice).json()]


@pytest.mark.api
@pytest.mark.parametrize("body", [{}, {"branch_id": 1}, {"account_type": "savings"}])
def test_API_ACC_11_missing_fields_return_400(api, alice, body):
    assert api.post("/api/accounts", alice, body).status_code == 400


@pytest.mark.api
@pytest.mark.parametrize("account_type", ["checking", "SAVINGS", "", 5, None])
def test_API_ACC_12_invalid_account_type_returns_400(api, alice, account_type):
    assert api.post("/api/accounts", alice, {"branch_id": 1, "account_type": account_type}).status_code == 400


@pytest.mark.api
def test_API_ACC_13_nonexistent_branch_returns_404(api, alice):
    assert api.post("/api/accounts", alice, {"branch_id": 999, "account_type": "savings"}).status_code == 404


@pytest.mark.api
@pytest.mark.parametrize("branch_id", ["abc", -1, 1.5, {"a": 1}, [1]])
def test_API_ACC_14_invalid_branch_id_returns_400(api, alice, branch_id):
    assert api.post("/api/accounts", alice, {"branch_id": branch_id, "account_type": "savings"}).status_code == 400


@pytest.mark.api
def test_API_ACC_15_create_requires_login(api):
    assert api.post("/api/accounts", None, {"branch_id": 1, "account_type": "savings"}).status_code == 401


@pytest.mark.api
def test_API_ACC_16_cannot_open_an_account_in_someone_elses_name(api, alice, db):
    r = api.post("/api/accounts", alice, {"branch_id": 1, "account_type": "savings", "user_id": 2})
    assert scalar(db, "SELECT user_id FROM accounts WHERE account_id = %s", (r.json()["account_id"],)) == 1


@pytest.mark.api
def test_API_ACC_17_new_account_cannot_be_created_with_a_starting_balance(api, alice, db):
    r = api.post("/api/accounts", alice, {"branch_id": 1, "account_type": "savings", "balance": 1000000})
    assert scalar(db, "SELECT balance FROM accounts WHERE account_id = %s", (r.json()["account_id"],)) == 0


# --------------------------------------------------------------- statements
@pytest.mark.api
def test_API_ACC_18_statement_totals_match_activity(api, alice):
    api.deposit(alice, 1, 100)
    api.withdraw(alice, 1, 30.25)
    r = api.get("/api/accounts/1/statement", alice)
    body = r.json()
    assert r.status_code == 200
    assert D(body["current_balance"]) == D("5069.75")
    assert body["summary"] == {"total_credits": "100.00", "total_debits": "30.25", "transaction_count": 2}
    assert {t["direction"] for t in body["transactions"]} == {"credit", "debit"}


@pytest.mark.api
def test_API_ACC_19_statement_of_unused_account_is_empty(api, alice):
    body = api.get("/api/accounts/1/statement", alice).json()
    assert body["summary"] == {"total_credits": "0.00", "total_debits": "0.00", "transaction_count": 0}
    assert body["transactions"] == []


@pytest.mark.api
def test_API_ACC_20_statement_shows_transfer_as_debit_and_credit(api, alice, bob):
    api.transfer(alice, 1, 2, 250)
    a = api.get("/api/accounts/1/statement", alice).json()["transactions"][0]
    b = api.get("/api/accounts/2/statement", bob).json()["transactions"][0]
    assert a["direction"] == "debit" and b["direction"] == "credit" and D(a["amount"]) == 250


@pytest.mark.api
def test_API_ACC_21_cannot_read_someone_elses_statement(api, alice):
    assert api.get("/api/accounts/2/statement", alice).status_code == 404


@pytest.mark.api
@pytest.mark.parametrize("bad_id", ["abc", "0", "-5"])
def test_API_ACC_22_statement_with_invalid_id_returns_400(api, alice, bad_id):
    assert api.get(f"/api/accounts/{bad_id}/statement", alice).status_code == 400


@pytest.mark.api
def test_API_ACC_23_statement_requires_login(api):
    assert api.get("/api/accounts/1/statement").status_code == 401


@pytest.mark.api
def test_API_ACC_24_statement_lists_newest_first(api, alice):
    for amount in (10, 20, 30):
        api.deposit(alice, 1, amount)
    amounts = [D(t["amount"]) for t in api.get("/api/accounts/1/statement", alice).json()["transactions"]]
    assert amounts == [30, 20, 10]


# ------------------------------------------------------------------ branches
@pytest.mark.api
def test_API_ACC_25_branches_are_listed_for_logged_in_users(api, alice):
    r = api.get("/api/branches", alice)
    assert r.status_code == 200 and len(r.json()) == 3
    assert {"branch_id", "branch_name", "ifsc_code", "address"} <= set(r.json()[0])


@pytest.mark.api
def test_API_ACC_26_branches_require_login(api):
    assert api.get("/api/branches").status_code == 401

# ============================================================================
# api transactions
# ============================================================================

def txn_count(db):
    return scalar(db, "SELECT COUNT(*) FROM transactions")


# ------------------------------------------------------------------ deposit
@pytest.mark.api
def test_API_TXN_01_deposit_increases_balance_and_records_transaction(api, alice, db):
    r = api.deposit(alice, 1, 250.50)
    assert r.status_code == 201 and r.json()["transaction_id"]
    assert balance(db, 1) == D("5250.50")
    t = rows(db, "SELECT * FROM transactions")[0]
    assert (t["type"], t["status"], t["from_account_id"], t["to_account_id"]) == ("deposit", "success", None, 1)
    assert t["amount"] == D("250.50")


@pytest.mark.api
def test_API_TXN_02_deposit_writes_an_audit_log_entry(api, alice, db):
    api.deposit(alice, 1, 100)
    assert audit_count(db, 1) == 1


@pytest.mark.api
def test_API_TXN_03_deposit_accepts_amount_as_a_string(api, alice, db):
    assert api.deposit(alice, 1, "10.25").status_code == 201
    assert balance(db, 1) == D("5010.25")


@pytest.mark.api
def test_API_TXN_04_smallest_valid_deposit_is_one_paisa(api, alice, db):
    """Boundary value."""
    assert api.deposit(alice, 1, 0.01).status_code == 201
    assert balance(db, 1) == D("5000.01")


BAD_AMOUNTS = [0, -5, "abc", "", None, 0.001, "10.999", "1e3", "0x10", [5], {"a": 1}, True, " ", "--5"]


@pytest.mark.api
@pytest.mark.parametrize("amount", BAD_AMOUNTS)
def test_API_TXN_05_deposit_with_invalid_amount_returns_400_and_changes_nothing(api, alice, db, amount):
    assert api.deposit(alice, 1, amount).status_code == 400
    assert balance(db, 1) == 5000 and txn_count(db) == 0


@pytest.mark.api
def test_API_TXN_06_deposit_without_amount_returns_400(api, alice):
    assert api.post("/api/transactions/deposit", alice, {"account_id": 1}).status_code == 400


BAD_IDS = ["abc", 0, -1, 1.5, None, {"$gt": 0}, [1], "1 OR 1=1", "1; DROP TABLE accounts"]


@pytest.mark.api
@pytest.mark.parametrize("account_id", BAD_IDS)
def test_API_TXN_07_deposit_with_invalid_account_id_returns_400(api, alice, account_id):
    assert api.deposit(alice, account_id, 10).status_code == 400


@pytest.mark.api
def test_API_TXN_08_cannot_deposit_into_someone_elses_account(api, alice, db):
    assert api.deposit(alice, 2, 100).status_code == 404
    assert balance(db, 2) == 3000


@pytest.mark.api
def test_API_TXN_09_deposit_into_nonexistent_account_returns_404(api, alice):
    assert api.deposit(alice, 99999, 10).status_code == 404


@pytest.mark.api
@pytest.mark.parametrize("status", ["frozen", "closed"])
def test_API_TXN_10_deposit_into_inactive_account_returns_400(api, alice, db, status):
    run(db, "UPDATE accounts SET status = %s WHERE account_id = 1", (status,))
    assert api.deposit(alice, 1, 10).status_code == 400
    assert balance(db, 1) == 5000


@pytest.mark.api
def test_API_TXN_11_deposit_requires_login(api):
    assert api.deposit(None, 1, 10).status_code == 401


@pytest.mark.api
def test_API_TXN_12_deposit_that_would_overflow_the_balance_column_returns_4xx(api, alice, db):
    """DECIMAL(15,2) holds at most 9,999,999,999,999.99. Overflowing it must be a clean
    client error, not a 500."""
    r = api.deposit(alice, 1, "9999999999999.99")
    assert 400 <= r.status_code < 500, f"got {r.status_code}: {r.text}"
    assert balance(db, 1) == 5000


# --------------------------------------------------------------- withdrawal
@pytest.mark.api
def test_API_TXN_13_withdraw_decreases_balance_and_records_transaction(api, alice, db):
    r = api.withdraw(alice, 1, 1200.75)
    assert r.status_code == 201
    assert balance(db, 1) == D("3799.25")
    t = rows(db, "SELECT * FROM transactions")[0]
    assert (t["type"], t["status"], t["from_account_id"], t["to_account_id"]) == ("withdrawal", "success", 1, None)


@pytest.mark.api
def test_API_TXN_14_withdraw_entire_balance_leaves_zero(api, alice, db):
    """Boundary value: balance == amount is allowed."""
    assert api.withdraw(alice, 1, 5000).status_code == 201
    assert balance(db, 1) == 0


@pytest.mark.api
def test_API_TXN_15_withdraw_one_paisa_more_than_balance_is_refused(api, alice, db):
    """Boundary value."""
    assert api.withdraw(alice, 1, "5000.01").status_code == 400
    assert balance(db, 1) == 5000 and txn_count(db) == 0


@pytest.mark.api
def test_API_TXN_16_withdraw_from_empty_account_is_refused(api, alice, db):
    run(db, "UPDATE accounts SET balance = 0 WHERE account_id = 1")
    assert api.withdraw(alice, 1, 1).status_code == 400


@pytest.mark.api
@pytest.mark.parametrize("amount", BAD_AMOUNTS)
def test_API_TXN_17_withdraw_with_invalid_amount_returns_400(api, alice, db, amount):
    assert api.withdraw(alice, 1, amount).status_code == 400
    assert balance(db, 1) == 5000


@pytest.mark.api
@pytest.mark.parametrize("account_id", BAD_IDS)
def test_API_TXN_18_withdraw_with_invalid_account_id_returns_400(api, alice, account_id):
    assert api.withdraw(alice, account_id, 10).status_code == 400


@pytest.mark.api
def test_API_TXN_19_cannot_withdraw_from_someone_elses_account(api, alice, db):
    assert api.withdraw(alice, 2, 100).status_code == 404
    assert balance(db, 2) == 3000


@pytest.mark.api
@pytest.mark.parametrize("status", ["frozen", "closed"])
def test_API_TXN_20_withdraw_from_inactive_account_returns_400(api, alice, db, status):
    run(db, "UPDATE accounts SET status = %s WHERE account_id = 1", (status,))
    assert api.withdraw(alice, 1, 10).status_code == 400
    assert balance(db, 1) == 5000


@pytest.mark.api
def test_API_TXN_21_withdraw_requires_login(api):
    assert api.withdraw(None, 1, 10).status_code == 401


# ----------------------------------------------------------------- transfer
@pytest.mark.api
def test_API_TXN_22_transfer_moves_money_between_accounts(api, alice, db):
    r = api.transfer(alice, 1, 2, 500, description="Rent")
    assert r.status_code == 201
    assert balance(db, 1) == 4500 and balance(db, 2) == 3500
    t = rows(db, "SELECT * FROM transactions")[0]
    assert (t["type"], t["status"], t["from_account_id"], t["to_account_id"], t["description"]) == \
           ("transfer", "success", 1, 2, "Rent")


@pytest.mark.api
def test_API_TXN_23_transfer_uses_default_description(api, alice, db):
    api.transfer(alice, 1, 2, 10)
    assert scalar(db, "SELECT description FROM transactions") == "Fund transfer"


@pytest.mark.api
def test_API_TXN_24_transfer_keeps_total_money_constant(api, alice, db):
    before = total_balance(db)
    api.transfer(alice, 1, 2, "123.45")
    assert total_balance(db) == before


@pytest.mark.api
def test_API_TXN_25_transfer_creates_audit_entries_for_both_accounts(api, alice, db):
    api.transfer(alice, 1, 2, 100)
    assert audit_count(db, 1) == 1 and audit_count(db, 2) == 1


@pytest.mark.api
def test_API_TXN_26_transfer_between_own_accounts(api, alice, db):
    new_id = api.post("/api/accounts", alice, {"branch_id": 1, "account_type": "current"}).json()["account_id"]
    assert api.transfer(alice, 1, new_id, 1000).status_code == 201
    assert balance(db, new_id) == 1000 and balance(db, 1) == 4000


@pytest.mark.api
def test_API_TXN_27_transfer_to_the_same_account_is_refused(api, alice, db):
    assert api.transfer(alice, 1, 1, 10).status_code == 400
    assert txn_count(db) == 0


@pytest.mark.api
@pytest.mark.parametrize("src,dst", [("1", 1), (1, "1"), ("1", "1")])
def test_API_TXN_28_same_account_check_works_across_string_and_number_ids(api, alice, db, src, dst):
    """Previously '1' !== 1 slipped past a strict-equality check."""
    assert api.transfer(alice, src, dst, 10).status_code == 400
    assert txn_count(db) == 0 and balance(db, 1) == 5000


@pytest.mark.api
def test_API_TXN_29_insufficient_funds_changes_nothing(api, alice, db):
    assert api.transfer(alice, 1, 2, 5000.01).status_code == 400
    assert balance(db, 1) == 5000 and balance(db, 2) == 3000
    assert txn_count(db) == 0 and audit_count(db) == 0


@pytest.mark.api
def test_API_TXN_30_transfer_of_entire_balance_is_allowed(api, alice, db):
    assert api.transfer(alice, 1, 2, 5000).status_code == 201
    assert balance(db, 1) == 0 and balance(db, 2) == 8000


@pytest.mark.api
def test_API_TXN_31_cannot_transfer_from_someone_elses_account(api, alice, db):
    assert api.transfer(alice, 2, 1, 100).status_code == 404
    assert balance(db, 2) == 3000 and balance(db, 1) == 5000


@pytest.mark.api
def test_API_TXN_32_transfer_to_nonexistent_account_returns_404(api, alice, db):
    assert api.transfer(alice, 1, 99999, 10).status_code == 404
    assert balance(db, 1) == 5000


@pytest.mark.api
def test_API_TXN_33_transfer_from_nonexistent_account_returns_404(api, alice):
    assert api.transfer(alice, 99999, 1, 10).status_code == 404


@pytest.mark.api
@pytest.mark.parametrize("status", ["frozen", "closed"])
def test_API_TXN_34_transfer_from_inactive_account_returns_400(api, alice, db, status):
    run(db, "UPDATE accounts SET status = %s WHERE account_id = 1", (status,))
    assert api.transfer(alice, 1, 2, 10).status_code == 400


@pytest.mark.api
@pytest.mark.parametrize("status", ["frozen", "closed"])
def test_API_TXN_35_transfer_to_inactive_account_returns_400(api, alice, db, status):
    run(db, "UPDATE accounts SET status = %s WHERE account_id = 2", (status,))
    assert api.transfer(alice, 1, 2, 10).status_code == 400
    assert balance(db, 1) == 5000 and balance(db, 2) == 3000


@pytest.mark.api
@pytest.mark.parametrize("amount", BAD_AMOUNTS)
def test_API_TXN_36_transfer_with_invalid_amount_returns_400(api, alice, db, amount):
    assert api.transfer(alice, 1, 2, amount).status_code == 400
    assert balance(db, 1) == 5000 and balance(db, 2) == 3000


@pytest.mark.api
@pytest.mark.parametrize("src,dst", [(None, 2), (1, None), ("abc", 2), (1, "abc"), (0, 2), (1, -2), ({"a": 1}, 2)])
def test_API_TXN_37_transfer_with_invalid_account_ids_returns_400(api, alice, src, dst):
    assert api.transfer(alice, src, dst, 10).status_code == 400


@pytest.mark.api
def test_API_TXN_38_transfer_description_of_255_chars_is_accepted(api, alice):
    """Boundary value."""
    assert api.transfer(alice, 1, 2, 1, description="d" * 255).status_code == 201


@pytest.mark.api
@pytest.mark.parametrize("description", ["d" * 256, 123, {"a": 1}, ["x"]])
def test_API_TXN_39_invalid_description_returns_400(api, alice, db, description):
    assert api.transfer(alice, 1, 2, 1, description=description).status_code == 400
    assert balance(db, 1) == 5000


@pytest.mark.api
def test_API_TXN_40_transfer_requires_login(api):
    assert api.transfer(None, 1, 2, 10).status_code == 401


@pytest.mark.api
def test_API_TXN_41_sql_injection_in_description_is_stored_as_plain_text(api, alice, db):
    payload = "x'); DROP TABLE accounts; --"
    assert api.transfer(alice, 1, 2, 1, description=payload).status_code == 201
    assert scalar(db, "SELECT description FROM transactions") == payload
    assert scalar(db, "SELECT COUNT(*) FROM accounts") == 2


# ------------------------------------------------------------------ history
@pytest.mark.api
def test_API_TXN_42_history_shows_only_my_transactions(api, alice, bob):
    api.deposit(alice, 1, 10)
    api.deposit(bob, 2, 20)
    mine = api.get("/api/transactions", alice).json()
    assert len(mine) == 1 and mine[0]["to_account_id"] == 1


@pytest.mark.api
def test_API_TXN_43_history_includes_incoming_and_outgoing_transfers(api, alice, bob):
    api.transfer(alice, 1, 2, 100)
    api.transfer(bob, 2, 1, 50)
    assert len(api.get("/api/transactions", alice).json()) == 2
    assert len(api.get("/api/transactions", bob).json()) == 2


@pytest.mark.api
def test_API_TXN_44_history_is_newest_first(api, alice):
    for amount in (1, 2, 3):
        api.deposit(alice, 1, amount)
    amounts = [D(t["amount"]) for t in api.get("/api/transactions", alice).json()]
    assert amounts == [3, 2, 1]


@pytest.mark.api
def test_API_TXN_45_history_is_empty_for_a_user_with_no_activity(api, alice):
    assert api.get("/api/transactions", alice).json() == []


@pytest.mark.api
def test_API_TXN_46_history_requires_login(api):
    assert api.get("/api/transactions").status_code == 401


@pytest.mark.api
def test_API_TXN_47_failed_attempts_do_not_appear_in_history(api, alice):
    api.withdraw(alice, 1, 999999)
    assert api.get("/api/transactions", alice).json() == []


# -------------------------------------------------------------- concurrency
@pytest.mark.api
def test_API_TXN_48_simultaneous_withdrawals_cannot_overdraw(api, alice, db):
    """10 withdrawals of 1000 fired at once against a 5000 balance: exactly 5 succeed."""
    codes = parallel([lambda: api.withdraw(alice, 1, 1000).status_code for _ in range(10)])
    assert codes.count(201) == 5 and codes.count(400) == 5, codes
    assert balance(db, 1) == 0
    assert txn_count(db) == 5 and audit_count(db, 1) == 5


@pytest.mark.api
def test_API_TXN_49_simultaneous_transfers_cannot_overdraw(api, alice, db):
    """4 transfers of 3000 from a 5000 account at once: exactly one can succeed."""
    codes = parallel([lambda: api.transfer(alice, 1, 2, 3000).status_code for _ in range(4)])
    assert codes.count(201) == 1 and codes.count(400) == 3, codes
    assert balance(db, 1) == 2000 and balance(db, 2) == 6000


@pytest.mark.api
def test_API_TXN_50_simultaneous_deposits_lose_no_updates(api, alice, db):
    codes = parallel([lambda: api.deposit(alice, 1, 10).status_code for _ in range(15)])
    assert codes == [201] * 15
    assert balance(db, 1) == 5150 and txn_count(db) == 15


@pytest.mark.api
def test_API_TXN_51_opposite_direction_transfers_do_not_deadlock(api, alice, bob, db):
    """A->B and B->A at the same moment, 8 each. Locks are taken lowest-id-first, so no
    request may fail with 500 and the money must balance exactly."""
    before = total_balance(db)
    calls = [(lambda: api.transfer(alice, 1, 2, 10).status_code) if i % 2 == 0
             else (lambda: api.transfer(bob, 2, 1, 10).status_code) for i in range(16)]
    codes = parallel(calls)
    assert codes == [201] * 16, codes
    assert total_balance(db) == before
    assert balance(db, 1) == 5000 and balance(db, 2) == 3000


@pytest.mark.api
def test_API_TXN_52_mixed_simultaneous_operations_keep_totals_consistent(api, alice, bob, db):
    """Deposits, withdrawals and transfers all at once; the ledger must reconcile."""
    calls = ([lambda: api.deposit(alice, 1, 100).status_code] * 5 +
             [lambda: api.withdraw(bob, 2, 100).status_code] * 5 +
             [lambda: api.transfer(alice, 1, 2, 50).status_code] * 5)
    codes = parallel(calls)
    assert 500 not in codes and all(c == 201 for c in codes), codes
    assert balance(db, 1) == 5000 + 500 - 250
    assert balance(db, 2) == 3000 - 500 + 250


@pytest.mark.api
@pytest.mark.xfail(reason="KNOWN GAP (reported, not fixed): refused or failed money movements are not "
                          "recorded; the 'failed' status exists in the schema but is never written.",
                   strict=False)
def test_API_TXN_53_refused_transfer_is_recorded_with_status_failed(api, alice, db):
    api.transfer(alice, 1, 2, 999999)
    assert scalar(db, "SELECT COUNT(*) FROM transactions WHERE status = 'failed'") == 1


@pytest.mark.api
def test_API_TXN_54_transfer_that_would_overflow_the_receivers_balance_returns_4xx(api, alice, db):
    """Same limit as TXN_12, on the receiving side of a transfer."""
    run(db, "UPDATE accounts SET balance = 9999999999999.00 WHERE account_id = 2")
    r = api.transfer(alice, 1, 2, 5000)
    assert 400 <= r.status_code < 500, f"got {r.status_code}: {r.text}"
    assert balance(db, 1) == 5000 and balance(db, 2) == D("9999999999999.00")
    assert txn_count(db) == 0


@pytest.mark.api
def test_API_TXN_55_deposit_up_to_exactly_the_maximum_balance_is_allowed(api, alice, db):
    """Boundary value: 5000 + 9,999,999,994,999.99 = 9,999,999,999,999.99, the column maximum."""
    assert api.deposit(alice, 1, "9999999994999.99").status_code == 201
    assert balance(db, 1) == D("9999999999999.99")
    assert api.deposit(alice, 1, "0.01").status_code == 400

# ============================================================================
# api admin
# ============================================================================

ADMIN_GET_ROUTES = ["/api/admin/stats", "/api/admin/users", "/api/admin/accounts",
                    "/api/admin/transactions", "/api/admin/audit-log"]


@pytest.mark.api
@pytest.mark.parametrize("path", ADMIN_GET_ROUTES)
def test_API_ADM_01_admin_routes_reject_anonymous_requests(api, path):
    assert api.get(path).status_code == 401


@pytest.mark.api
@pytest.mark.parametrize("path", ADMIN_GET_ROUTES)
def test_API_ADM_02_admin_routes_reject_customers_with_403(api, alice, path):
    assert api.get(path, alice).status_code == 403


@pytest.mark.api
def test_API_ADM_03_customer_cannot_change_account_status(api, alice, db):
    r = api.patch("/api/admin/accounts/1/status", alice, {"status": "frozen"})
    assert r.status_code == 403
    assert scalar(db, "SELECT status FROM accounts WHERE account_id = 1") == "active"


@pytest.mark.api
def test_API_ADM_04_stats_match_the_database(api, admin):
    body = api.get("/api/admin/stats", admin).json()
    assert body["totalUsers"] == 3 and body["totalAccounts"] == 2 and body["totalTransactions"] == 0
    assert D(body["totalBalance"]) == 8000


@pytest.mark.api
def test_API_ADM_05_stats_update_after_activity(api, admin, alice):
    api.deposit(alice, 1, 500)
    body = api.get("/api/admin/stats", admin).json()
    assert body["totalTransactions"] == 1 and D(body["totalBalance"]) == 8500


@pytest.mark.api
def test_API_ADM_06_user_list_has_all_users_and_no_password_data(api, admin):
    r = api.get("/api/admin/users", admin)
    assert r.status_code == 200 and len(r.json()) == 3
    assert "password" not in r.text.lower() and "$2b$" not in r.text


@pytest.mark.api
def test_API_ADM_07_account_list_includes_owner_and_branch(api, admin):
    data = api.get("/api/admin/accounts", admin).json()
    assert len(data) == 2
    assert {"owner_name", "owner_email", "branch_name", "balance", "status"} <= set(data[0])


@pytest.mark.api
def test_API_ADM_08_transaction_list_is_newest_first_and_capped_at_200(api, admin, alice):
    for amount in (1, 2, 3):
        api.deposit(alice, 1, amount)
    data = api.get("/api/admin/transactions", admin).json()
    assert [D(t["amount"]) for t in data] == [3, 2, 1] and len(data) <= 200


@pytest.mark.api
def test_API_ADM_09_audit_log_records_balance_changes_with_owner(api, admin, alice):
    api.deposit(alice, 1, 100)
    log = api.get("/api/admin/audit-log", admin).json()
    assert len(log) == 1
    assert log[0]["owner_name"] == "Alice Johnson"
    assert D(log[0]["old_balance"]) == 5000 and D(log[0]["new_balance"]) == 5100


@pytest.mark.api
def test_API_ADM_10_freeze_blocks_the_customer_end_to_end(api, admin, alice, db):
    assert api.patch("/api/admin/accounts/1/status", admin, {"status": "frozen"}).status_code == 200
    assert api.deposit(alice, 1, 10).status_code == 400
    assert api.withdraw(alice, 1, 10).status_code == 400
    assert api.transfer(alice, 1, 2, 10).status_code == 400
    assert balance(db, 1) == 5000


@pytest.mark.api
def test_API_ADM_11_unfreeze_restores_normal_operation(api, admin, alice):
    api.patch("/api/admin/accounts/1/status", admin, {"status": "frozen"})
    assert api.patch("/api/admin/accounts/1/status", admin, {"status": "active"}).status_code == 200
    assert api.deposit(alice, 1, 10).status_code == 201


@pytest.mark.api
@pytest.mark.parametrize("status", ["open", "FROZEN", "", None, 1, ["active"], {"a": 1}])
def test_API_ADM_12_invalid_status_value_returns_400(api, admin, status):
    assert api.patch("/api/admin/accounts/1/status", admin, {"status": status}).status_code == 400


@pytest.mark.api
def test_API_ADM_13_status_update_with_empty_body_returns_400(api, admin):
    assert api.patch("/api/admin/accounts/1/status", admin, {}).status_code == 400


@pytest.mark.api
def test_API_ADM_14_status_update_for_unknown_account_returns_404(api, admin):
    assert api.patch("/api/admin/accounts/99999/status", admin, {"status": "frozen"}).status_code == 404


@pytest.mark.api
@pytest.mark.parametrize("bad_id", ["abc", "0", "-1", "1.5", "99999999999"])
def test_API_ADM_15_status_update_with_invalid_id_returns_400(api, admin, bad_id):
    assert api.patch(f"/api/admin/accounts/{bad_id}/status", admin, {"status": "frozen"}).status_code == 400


@pytest.mark.api
def test_API_ADM_16_account_with_money_cannot_be_closed(api, admin, db):
    r = api.patch("/api/admin/accounts/1/status", admin, {"status": "closed"})
    assert r.status_code == 400
    assert scalar(db, "SELECT status FROM accounts WHERE account_id = 1") == "active"


@pytest.mark.api
def test_API_ADM_17_empty_account_can_be_closed(api, admin, db):
    run(db, "UPDATE accounts SET balance = 0 WHERE account_id = 1")
    assert api.patch("/api/admin/accounts/1/status", admin, {"status": "closed"}).status_code == 200
    assert scalar(db, "SELECT status FROM accounts WHERE account_id = 1") == "closed"


@pytest.mark.api
@pytest.mark.parametrize("new_status", ["active", "frozen"])
def test_API_ADM_18_closed_account_cannot_be_reopened(api, admin, db, new_status):
    run(db, "UPDATE accounts SET balance = 0, status = 'closed' WHERE account_id = 1")
    assert api.patch("/api/admin/accounts/1/status", admin, {"status": new_status}).status_code == 400
    assert scalar(db, "SELECT status FROM accounts WHERE account_id = 1") == "closed"


@pytest.mark.api
def test_API_ADM_19_demoted_admin_loses_access_immediately(api, admin, db):
    """verifyToken re-reads the role from the database, not from the token."""
    assert api.get("/api/admin/stats", admin).status_code == 200
    run(db, "UPDATE users SET role = 'customer' WHERE user_id = 3")
    assert api.get("/api/admin/stats", admin).status_code == 403


@pytest.mark.api
def test_API_ADM_20_promoted_customer_gains_access_immediately(api, alice, db):
    assert api.get("/api/admin/stats", alice).status_code == 403
    run(db, "UPDATE users SET role = 'admin' WHERE user_id = 1")
    assert api.get("/api/admin/stats", alice).status_code == 200


@pytest.mark.api
def test_API_ADM_21_a_customer_cannot_become_admin_through_any_api_call(api, alice, db):
    api.put("/api/auth/me", alice, {"name": "Alice", "role": "admin"})
    api.post("/api/accounts", alice, {"branch_id": 1, "account_type": "savings", "role": "admin"})
    assert scalar(db, "SELECT role FROM users WHERE user_id = 1") == "customer"
    assert api.get("/api/admin/stats", alice).status_code == 403

# ============================================================================
# api security
# ============================================================================

SECRET = config.TEST_JWT_SECRET


def make_token(payload=None, secret=SECRET, algorithm="HS256"):
    claims = {"user_id": 1, "email": "alice@example.com", "role": "customer",
              "iat": int(time.time()), "exp": int(time.time()) + 3600}
    claims.update(payload or {})
    return jwt.encode(claims, secret, algorithm=algorithm)


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


# ----------------------------------------------------------- token handling
@pytest.mark.api
def test_API_SEC_01_a_correctly_signed_token_is_accepted(api):
    """Positive control for the forging helper: if this fails, the other token tests mean nothing."""
    assert api.get("/api/auth/me", make_token()).status_code == 200


@pytest.mark.api
def test_API_SEC_02_expired_token_is_rejected(api):
    assert api.get("/api/auth/me", make_token({"exp": int(time.time()) - 10})).status_code == 401


@pytest.mark.api
def test_API_SEC_03_token_signed_with_another_secret_is_rejected(api):
    assert api.get("/api/auth/me", make_token(secret="some-other-secret-value-0123456789abcdef")).status_code == 401


@pytest.mark.api
def test_API_SEC_04_unsigned_token_alg_none_is_rejected(api):
    header = b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    body = b64(json.dumps({"user_id": 3, "email": "admin@example.com", "role": "admin",
                           "exp": int(time.time()) + 3600}).encode())
    assert api.get("/api/admin/stats", f"{header}.{body}.").status_code == 401


@pytest.mark.api
def test_API_SEC_05_payload_edited_after_signing_is_rejected(api, alice):
    """Take Alice's real token and rewrite the payload to claim admin, keeping her signature."""
    header, _payload, signature = alice.split(".")
    forged = b64(json.dumps({"user_id": 3, "email": "admin@example.com", "role": "admin",
                             "exp": int(time.time()) + 3600}).encode())
    assert api.get("/api/admin/stats", f"{header}.{forged}.{signature}").status_code == 401


@pytest.mark.api
@pytest.mark.parametrize("token", ["garbage", "a.b.c", "....", "null", "undefined", "Bearer"])
def test_API_SEC_06_malformed_tokens_are_rejected(api, token):
    assert api.get("/api/auth/me", token).status_code == 401


@pytest.mark.api
@pytest.mark.parametrize("header", ["Basic YWxpY2U6cGFzc3dvcmQ=", "Token abc", "bearer abc", "abc"])
def test_API_SEC_07_wrong_authorization_scheme_is_rejected(api, alice, header):
    assert api.get("/api/auth/me", headers={"Authorization": header}).status_code == 401


@pytest.mark.api
def test_API_SEC_08_token_passed_in_query_string_is_ignored(api, alice):
    assert api.get(f"/api/auth/me?token={alice}").status_code == 401


@pytest.mark.api
def test_API_SEC_09_valid_token_for_a_deleted_user_is_rejected(api, alice, db):
    run(db, "SET FOREIGN_KEY_CHECKS = 0")
    run(db, "DELETE FROM users WHERE user_id = 1")
    run(db, "SET FOREIGN_KEY_CHECKS = 1")
    assert api.get("/api/auth/me", alice).status_code == 401


@pytest.mark.api
def test_API_SEC_10_validly_signed_token_for_a_nonexistent_user_is_rejected(api):
    assert api.get("/api/auth/me", make_token({"user_id": 9999})).status_code == 401


@pytest.mark.api
def test_API_SEC_11_role_claim_inside_the_token_is_not_trusted(api):
    """Signed with the real secret and claiming admin, but the database says customer."""
    token = make_token({"user_id": 1, "role": "admin"})
    assert api.get("/api/admin/stats", token).status_code == 403


@pytest.mark.api
def test_API_SEC_12_token_cannot_be_used_to_act_as_another_user(api, alice, db):
    """Changing the account_id in the request body never reaches another user's money."""
    assert api.withdraw(alice, 2, 100).status_code == 404
    assert api.transfer(alice, 2, 1, 100).status_code == 404
    assert balance(db, 2) == 3000


# ---------------------------------------------------------------- injection
SQLI = ["' OR '1'='1", "' OR 1=1 --", "admin@example.com'--", "'; DROP TABLE users; --",
        "\" OR \"\"=\"", "1' UNION SELECT * FROM users --"]


@pytest.mark.api
@pytest.mark.parametrize("payload", SQLI)
def test_API_SEC_13_sql_injection_in_login_email_does_not_log_anyone_in(api, db, payload):
    r = api.post("/api/auth/login", json={"email": payload, "password": payload})
    assert r.status_code == 401
    assert scalar(db, "SELECT COUNT(*) FROM users") == 3


@pytest.mark.api
@pytest.mark.parametrize("payload", SQLI)
def test_API_SEC_14_sql_injection_in_register_name_is_stored_as_text(api, db, payload):
    r = api.post("/api/auth/register", json={"name": payload, "email": "inj@example.com", "password": "Passw0rd!"})
    assert r.status_code == 201
    assert scalar(db, "SELECT name FROM users WHERE email = 'inj@example.com'") == payload
    assert scalar(db, "SELECT COUNT(*) FROM users") == 4


@pytest.mark.api
def test_API_SEC_15_script_tags_are_stored_and_returned_as_json_text(api, alice):
    xss = "<script>alert(1)</script>"
    api.put("/api/auth/me", alice, {"name": xss})
    r = api.get("/api/auth/me", alice)
    assert r.headers["Content-Type"].startswith("application/json")      # never rendered as HTML
    assert r.json()["name"] == xss


@pytest.mark.api
@pytest.mark.parametrize("bad_id", ["1 OR 1=1", "1;DROP TABLE accounts", "1%20UNION%20SELECT%201", "-1", "1e1"])
def test_API_SEC_16_sql_injection_in_url_ids_returns_400(api, alice, db, bad_id):
    assert api.get(f"/api/accounts/{bad_id}", alice).status_code == 400
    assert scalar(db, "SELECT COUNT(*) FROM accounts") == 2


@pytest.mark.api
def test_API_SEC_17_object_instead_of_value_cannot_change_the_query(api, alice, db):
    """mysql2's query() expands objects into SQL fragments; the validators must stop that first."""
    r = api.post("/api/transactions/withdraw", alice, {"account_id": {"user_id": 2}, "amount": 1})
    assert r.status_code == 400
    assert balance(db, 2) == 3000


# ------------------------------------------------------ input and transport
@pytest.mark.api
def test_API_SEC_18_malformed_json_returns_400_json_error(api):
    r = api.post("/api/auth/login", data='{"email": ', headers={"Content-Type": "application/json"})
    assert r.status_code == 400 and r.json() == {"error": "Malformed JSON body"}


@pytest.mark.api
def test_API_SEC_19_oversized_body_returns_413(api):
    r = api.post("/api/auth/register", json={"name": "x" * 200_000, "email": "a@b.co", "password": "Passw0rd!"})
    assert r.status_code == 413


@pytest.mark.api
def test_API_SEC_20_non_json_content_type_returns_400_not_500(api):
    r = api.post("/api/auth/login", data="email=a&password=b", headers={"Content-Type": "text/plain"})
    assert r.status_code == 400


@pytest.mark.api
def test_API_SEC_21_empty_request_body_returns_400_not_500(api):
    assert api.post("/api/auth/register").status_code == 400
    assert api.post("/api/transactions/deposit", api.login("alice@example.com")).status_code == 400


@pytest.mark.api
def test_API_SEC_22_json_array_body_returns_400_not_500(api):
    assert api.post("/api/auth/login", json=[1, 2, 3]).status_code == 400


@pytest.mark.api
def test_API_SEC_23_unknown_route_returns_json_404(api):
    r = api.get("/api/does-not-exist")
    assert r.status_code == 404 and r.json() == {"error": "Route not found"}


@pytest.mark.api
@pytest.mark.parametrize("method,path", [("DELETE", "/api/accounts/1"), ("PUT", "/api/accounts"),
                                         ("PATCH", "/api/transactions"), ("DELETE", "/api/admin/users")])
def test_API_SEC_24_unsupported_methods_are_not_available(api, alice, method, path):
    """Never a 2xx. (Under /api/admin a customer is stopped with 403 before routing, which is fine.)"""
    assert api.request(method, path, alice).status_code in (403, 404, 405)


@pytest.mark.api
def test_API_SEC_25_no_response_leaks_password_hashes(api, alice, admin):
    for path, token in [("/api/auth/me", alice), ("/api/accounts", alice), ("/api/admin/users", admin)]:
        assert "$2b$" not in api.get(path, token).text


@pytest.mark.api
def test_API_SEC_26_error_responses_do_not_expose_stack_traces_or_sql(api, alice):
    bodies = [api.post("/api/transactions/deposit", alice, {"account_id": "x", "amount": "y"}).text,
              api.get("/api/accounts/abc", alice).text,
              api.post("/api/auth/login", json=["x"]).text]
    for body in bodies:
        assert "at Object" not in body and "node_modules" not in body and "SQL" not in body.upper().split('"ERROR"')[0]


@pytest.mark.api
def test_API_SEC_27_health_endpoint_is_public_and_minimal(api):
    r = api.get("/api/health")
    assert r.status_code == 200 and set(r.json()) == {"status", "message"}


@pytest.mark.api
def test_API_SEC_28_cors_preflight_allows_the_authorization_header(api):
    r = api.request("OPTIONS", "/api/accounts", headers={
        "Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization"})
    assert r.status_code in (200, 204)
    assert "authorization" in r.headers.get("Access-Control-Allow-Headers", "").lower()


@pytest.mark.api
def test_API_SEC_29_password_check_runs_for_unknown_emails_too(api):
    """Timing-based user enumeration guard (loose check: both must take comparable time)."""
    def timed(email):
        start = time.perf_counter()
        api.post("/api/auth/login", json={"email": email, "password": "wrong-password"})
        return time.perf_counter() - start

    known = sorted(timed("alice@example.com") for _ in range(5))[2]
    unknown = sorted(timed("nobody@example.com") for _ in range(5))[2]
    assert unknown > known * 0.5, f"unknown-email login was suspiciously fast: {unknown:.3f}s vs {known:.3f}s"


# ------------------------------------------------------ known gaps (xfail)
@pytest.mark.api
@pytest.mark.xfail(reason="KNOWN GAP (reported, not fixed): Express sends 'X-Powered-By: Express', "
                          "which tells attackers which framework to target. Fix: app.disable('x-powered-by') or helmet.",
                   strict=False)
def test_API_SEC_30_server_does_not_advertise_its_framework(api):
    assert "X-Powered-By" not in api.get("/api/health").headers


@pytest.mark.api
@pytest.mark.xfail(reason="KNOWN GAP (reported, not fixed): CORS allows every origin ('*') by default. "
                          "Fix: set CORS_ORIGIN in .env to the frontend's address.",
                   strict=False)
def test_API_SEC_31_cors_is_not_open_to_every_origin(api):
    r = api.get("/api/health", headers={"Origin": "http://evil.example"})
    assert r.headers.get("Access-Control-Allow-Origin") != "*"


@pytest.mark.api
@pytest.mark.xfail(reason="KNOWN GAP (reported, not fixed): there is no rate limiting, so passwords can be "
                          "guessed without limit. Fix: express-rate-limit on /api/auth/login.",
                   strict=False)
def test_API_SEC_32_repeated_failed_logins_are_throttled(api):
    codes = [api.post("/api/auth/login", json={"email": "alice@example.com", "password": f"wrong{i}"}).status_code
             for i in range(25)]
    assert 429 in codes


@pytest.mark.api
def test_API_SEC_33_placeholder_jwt_secret_is_not_used_by_the_real_app():
    """Reads the REAL backend/.env. If this fails, change JWT_SECRET to a long random string."""
    secret = config.REAL_JWT_SECRET
    if not secret:
        pytest.skip("backend/.env not present (e.g. in CI), nothing to check")
    assert not secret.startswith("change_this") and len(secret) >= 32, \
        "JWT_SECRET in backend/.env is still the placeholder: anyone who knows it can forge admin tokens"
