"""Schema (API contract) testing (SCH-xxx).

Merged from: test_api_schema.py.
"""
import json
import pytest
import schemas as S
from jsonschema import Draft202012Validator, FormatChecker


FORMATS = FormatChecker()


def check(response, schema, status):
    assert response.status_code == status, f"expected HTTP {status}, got {response.status_code}: {response.text[:300]}"
    assert response.headers["Content-Type"].startswith("application/json"), response.headers["Content-Type"]
    errors = sorted(Draft202012Validator(schema, format_checker=FORMATS).iter_errors(response.json()),
                    key=lambda e: list(e.path))
    assert not errors, "Response does not match schema:\n" + "\n".join(
        f"  at {'/'.join(map(str, e.path)) or '(root)'}: {e.message}" for e in errors[:8])
    return response.json()


def with_activity(api, alice):
    """Give the system a deposit, a withdrawal and a transfer so history/audit lists are not empty."""
    api.deposit(alice, 1, "25.00")
    api.withdraw(alice, 1, "10.00")
    api.transfer(alice, 1, 2, "5.00")


# ------------------------------------------------------------------ public / auth
@pytest.mark.api
@pytest.mark.schema
def test_SCH_01_health_response(api):
    check(api.get("/api/health"), S.HEALTH, 200)


@pytest.mark.api
@pytest.mark.schema
def test_SCH_02_login_success_response(api):
    check(api.post("/api/auth/login", json={"email": "alice@example.com", "password": "password123"}), S.LOGIN, 200)


@pytest.mark.api
@pytest.mark.schema
def test_SCH_03_register_success_response(api):
    r = api.post("/api/auth/register", json={"name": "Carol White", "email": "carol@example.com",
                                             "password": "Secret123!", "phone": "9123456780"})
    check(r, S.REGISTER, 201)


@pytest.mark.api
@pytest.mark.schema
def test_SCH_04_profile_response(api, alice):
    check(api.get("/api/auth/me", alice), S.PROFILE, 200)


@pytest.mark.api
@pytest.mark.schema
def test_SCH_05_profile_update_response(api, alice):
    r = api.put("/api/auth/me", alice, {"name": "Alice J", "phone": "9876543210"})
    check(r, S.PROFILE_UPDATED, 200)


# ------------------------------------------------------------------ accounts
@pytest.mark.api
@pytest.mark.schema
def test_SCH_06_account_list_response(api, alice):
    check(api.get("/api/accounts", alice), S.array_of(S.ACCOUNT), 200)


@pytest.mark.api
@pytest.mark.schema
def test_SCH_07_single_account_response(api, alice):
    check(api.get("/api/accounts/1", alice), S.ACCOUNT, 200)


@pytest.mark.api
@pytest.mark.schema
def test_SCH_08_create_account_response(api, alice):
    check(api.post("/api/accounts", alice, {"branch_id": 1, "account_type": "current"}), S.ACCOUNT_CREATED, 201)


@pytest.mark.api
@pytest.mark.schema
def test_SCH_09_statement_response_with_transactions(api, alice):
    with_activity(api, alice)
    body = check(api.get("/api/accounts/1/statement", alice), S.STATEMENT, 200)
    assert body["summary"]["transaction_count"] == len(body["transactions"]) == 3


@pytest.mark.api
@pytest.mark.schema
def test_SCH_10_statement_response_when_empty(api, alice):
    body = check(api.get("/api/accounts/1/statement", alice), S.STATEMENT, 200)
    assert body["transactions"] == []


@pytest.mark.api
@pytest.mark.schema
def test_SCH_11_branch_list_response(api, alice):
    body = check(api.get("/api/branches", alice), S.array_of(S.BRANCH), 200)
    assert len(body) == 3


# ------------------------------------------------------------------ money movement
@pytest.mark.api
@pytest.mark.schema
def test_SCH_12_deposit_response(api, alice):
    check(api.deposit(alice, 1, "10.00"), S.MONEY_RESULT, 201)


@pytest.mark.api
@pytest.mark.schema
def test_SCH_13_withdrawal_response(api, alice):
    check(api.withdraw(alice, 1, "10.00"), S.MONEY_RESULT, 201)


@pytest.mark.api
@pytest.mark.schema
def test_SCH_14_transfer_response(api, alice):
    check(api.transfer(alice, 1, 2, "10.00"), S.MONEY_RESULT, 201)


@pytest.mark.api
@pytest.mark.schema
def test_SCH_15_transaction_history_response(api, alice):
    with_activity(api, alice)
    body = check(api.get("/api/transactions", alice), S.array_of(S.TRANSACTION), 200)
    assert len(body) == 3


# ------------------------------------------------------------------ admin
@pytest.mark.api
@pytest.mark.schema
def test_SCH_16_admin_stats_response(api, admin):
    check(api.get("/api/admin/stats", admin), S.ADMIN_STATS, 200)


@pytest.mark.api
@pytest.mark.schema
def test_SCH_17_admin_user_list_response(api, admin):
    body = check(api.get("/api/admin/users", admin), S.array_of(S.ADMIN_USER), 200)
    assert len(body) == 3


@pytest.mark.api
@pytest.mark.schema
def test_SCH_18_admin_account_list_response(api, admin):
    check(api.get("/api/admin/accounts", admin), S.array_of(S.ADMIN_ACCOUNT), 200)


@pytest.mark.api
@pytest.mark.schema
def test_SCH_19_admin_transaction_list_response(api, alice, admin):
    with_activity(api, alice)
    body = check(api.get("/api/admin/transactions", admin), S.array_of(S.TRANSACTION), 200)
    assert len(body) == 3


@pytest.mark.api
@pytest.mark.schema
def test_SCH_20_admin_audit_log_response(api, alice, admin):
    with_activity(api, alice)
    body = check(api.get("/api/admin/audit-log", admin), S.array_of(S.AUDIT_ROW), 200)
    assert len(body) == 4             # deposit 1, withdrawal 1, transfer 2


@pytest.mark.api
@pytest.mark.schema
def test_SCH_21_admin_status_change_response(api, admin):
    check(api.patch("/api/admin/accounts/1/status", admin, {"status": "frozen"}), S.STATUS_UPDATED, 200)


# ------------------------------------------------------------------ error responses
@pytest.mark.api
@pytest.mark.schema
def test_SCH_22_error_401_missing_token(api):
    check(api.get("/api/accounts"), S.ERROR, 401)


@pytest.mark.api
@pytest.mark.schema
def test_SCH_23_error_401_wrong_password(api):
    check(api.post("/api/auth/login", json={"email": "alice@example.com", "password": "nope-nope"}), S.ERROR, 401)


@pytest.mark.api
@pytest.mark.schema
def test_SCH_24_error_403_customer_on_admin_route(api, alice):
    check(api.get("/api/admin/stats", alice), S.ERROR, 403)


@pytest.mark.api
@pytest.mark.schema
def test_SCH_25_error_404_unknown_route(api):
    check(api.get("/api/does-not-exist"), S.ERROR, 404)


@pytest.mark.api
@pytest.mark.schema
def test_SCH_26_error_404_unknown_account(api, alice):
    check(api.get("/api/accounts/9999", alice), S.ERROR, 404)


@pytest.mark.api
@pytest.mark.schema
def test_SCH_27_error_400_invalid_amount(api, alice):
    check(api.deposit(alice, 1, "-5"), S.ERROR, 400)


@pytest.mark.api
@pytest.mark.schema
def test_SCH_28_error_400_insufficient_balance(api, alice):
    check(api.withdraw(alice, 1, "999999.00"), S.ERROR, 400)


@pytest.mark.api
@pytest.mark.schema
def test_SCH_29_error_400_registration_missing_fields(api):
    check(api.post("/api/auth/register", json={"email": "x@example.com"}), S.ERROR, 400)


@pytest.mark.api
@pytest.mark.schema
def test_SCH_30_error_409_duplicate_email(api):
    r = api.post("/api/auth/register", json={"name": "Dup", "email": "alice@example.com", "password": "Secret123!"})
    check(r, S.ERROR, 409)


@pytest.mark.api
@pytest.mark.schema
def test_SCH_31_error_400_malformed_json(api):
    r = api.post("/api/auth/login", data="{bad json", headers={"Content-Type": "application/json"})
    check(r, S.ERROR, 400)


@pytest.mark.api
@pytest.mark.schema
def test_SCH_32_error_413_oversized_body(api):
    r = api.post("/api/auth/login", data=json.dumps({"email": "a@b.com", "password": "x" * 200_000}),
                 headers={"Content-Type": "application/json"})
    check(r, S.ERROR, 413)


# ------------------------------------------------------------------ cross-cutting rules
def all_success_responses(api, alice, admin):
    with_activity(api, alice)
    paths = ["/api/auth/me", "/api/accounts", "/api/accounts/1", "/api/accounts/1/statement",
             "/api/transactions", "/api/branches"]
    admin_paths = ["/api/admin/stats", "/api/admin/users", "/api/admin/accounts",
                   "/api/admin/transactions", "/api/admin/audit-log"]
    return ([(p, api.get(p, alice)) for p in paths] + [(p, api.get(p, admin)) for p in admin_paths]
            + [("/api/health", api.get("/api/health"))])


def walk(value, path=""):
    """Yield (path, key, value) for every key in a nested JSON value."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield path, k, v
            yield from walk(v, f"{path}/{k}")
    elif isinstance(value, list):
        for item in value:
            yield from walk(item, path)


@pytest.mark.api
@pytest.mark.schema
def test_SCH_33_every_response_is_json_with_a_utf8_content_type(api, alice, admin):
    for path, r in all_success_responses(api, alice, admin):
        assert r.headers["Content-Type"] == "application/json; charset=utf-8", path


@pytest.mark.api
@pytest.mark.schema
def test_SCH_34_no_response_ever_contains_a_password_hash_or_secret(api, alice, admin):
    banned = ("password", "hash", "secret", "token_secret")
    for path, r in all_success_responses(api, alice, admin):
        for where, key, value in walk(r.json()):
            assert not any(b in key.lower() for b in banned), f"{path}: leaks field '{key}'"
            assert not (isinstance(value, str) and value.startswith("$2")), f"{path}: bcrypt hash in '{key}'"


@pytest.mark.api
@pytest.mark.schema
def test_SCH_35_money_is_always_a_two_decimal_string_never_a_float(api, alice, admin):
    money_keys = {"amount", "balance", "current_balance", "total_credits", "total_debits",
                  "totalBalance", "old_balance", "new_balance"}
    seen = 0
    for path, r in all_success_responses(api, alice, admin):
        for where, key, value in walk(r.json()):
            if key in money_keys:
                seen += 1
                assert isinstance(value, str), f"{path}: {key} is {type(value).__name__}, not a string"
    assert seen > 20, "the check did not find the money fields it expects"


@pytest.mark.api
@pytest.mark.schema
def test_SCH_36_timestamps_are_iso_8601_utc(api, alice, admin):
    time_keys = {"created_at", "changed_at"}
    seen = 0
    for path, r in all_success_responses(api, alice, admin):
        for where, key, value in walk(r.json()):
            if key in time_keys:
                seen += 1
                assert Draft202012Validator(S.ISO_TIME).is_valid(value), f"{path}: {key}={value!r}"
    assert seen > 10


@pytest.mark.api
@pytest.mark.schema
def test_SCH_37_ids_are_integers_never_strings(api, alice, admin):
    for path, r in all_success_responses(api, alice, admin):
        for where, key, value in walk(r.json()):
            if key.endswith("_id") and value is not None:
                assert isinstance(value, int) and not isinstance(value, bool), f"{path}: {key}={value!r}"


@pytest.mark.api
@pytest.mark.schema
def test_SCH_38_list_endpoints_return_arrays_even_when_empty(api, alice):
    assert api.get("/api/transactions", alice).json() == []
    assert api.get("/api/accounts/1/statement", alice).json()["transactions"] == []


@pytest.mark.api
@pytest.mark.schema
def test_SCH_39_error_bodies_never_expose_stack_traces_or_sql(api, alice):
    probes = [
        api.get("/api/accounts/abc", alice),
        api.get("/api/accounts/1; DROP TABLE users", alice),
        api.deposit(alice, "1 OR 1=1", "5.00"),
        api.post("/api/auth/login", json={"email": "' OR 1=1 --", "password": "x"}),
        api.post("/api/auth/register", json={"name": "x", "email": "bad", "password": "short"}),
    ]
    for r in probes:
        text = r.text.lower()
        assert r.status_code in (400, 401, 404), r.status_code
        for leak in ("sql", "stack", "at object.", "node_modules", "mysql", "errno", "select "):
            assert leak not in text, f"error body leaks '{leak}': {r.text[:200]}"
