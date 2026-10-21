"""API testing: authentication and profile (API-AUT-xx)."""
import time
from decimal import Decimal

import jwt
import pytest

from api_client import parallel
from helpers import one, rows, scalar

pytestmark = pytest.mark.api

NEW_USER = {"name": "Carol White", "email": "carol@example.com", "password": "Secret123!", "phone": "9123456780"}


# ---------------------------------------------------------------- register
def test_API_AUT_01_register_with_valid_data(api, db):
    r = api.post("/api/auth/register", json=NEW_USER)
    assert r.status_code == 201
    uid = r.json()["user_id"]
    row = one(db, "SELECT name, email, role FROM users WHERE user_id = %s", (uid,))
    assert row == {"name": "Carol White", "email": "carol@example.com", "role": "customer"}


def test_API_AUT_02_new_user_can_log_in_straight_away(api):
    api.post("/api/auth/register", json=NEW_USER)
    r = api.post("/api/auth/login", json={"email": NEW_USER["email"], "password": NEW_USER["password"]})
    assert r.status_code == 200 and r.json()["token"]


def test_API_AUT_03_phone_is_optional(api):
    body = {k: v for k, v in NEW_USER.items() if k != "phone"}
    assert api.post("/api/auth/register", json=body).status_code == 201


@pytest.mark.parametrize("missing", ["name", "email", "password"])
def test_API_AUT_04_missing_required_field_returns_400(api, missing):
    body = {k: v for k, v in NEW_USER.items() if k != missing}
    assert api.post("/api/auth/register", json=body).status_code == 400


def test_API_AUT_05_empty_body_returns_400(api):
    assert api.post("/api/auth/register", json={}).status_code == 400


def test_API_AUT_06_duplicate_email_returns_409(api):
    r = api.post("/api/auth/register", json={**NEW_USER, "email": "alice@example.com"})
    assert r.status_code == 409


def test_API_AUT_07_duplicate_email_is_case_insensitive(api):
    r = api.post("/api/auth/register", json={**NEW_USER, "email": "ALICE@Example.com"})
    assert r.status_code == 409


@pytest.mark.parametrize("email", ["plainaddress", "no-at-sign.com", "a@b", "a b@c.com", "@example.com", ""])
def test_API_AUT_08_invalid_email_format_returns_400(api, email):
    assert api.post("/api/auth/register", json={**NEW_USER, "email": email}).status_code == 400


def test_API_AUT_09_password_shorter_than_8_returns_400(api):
    assert api.post("/api/auth/register", json={**NEW_USER, "password": "1234567"}).status_code == 400


def test_API_AUT_10_password_of_exactly_8_is_accepted(api):
    """Boundary value."""
    assert api.post("/api/auth/register", json={**NEW_USER, "password": "12345678"}).status_code == 201


def test_API_AUT_11_password_longer_than_72_bytes_returns_400(api):
    """bcrypt silently ignores everything after 72 bytes, so longer passwords are refused."""
    assert api.post("/api/auth/register", json={**NEW_USER, "password": "a" * 73}).status_code == 400


def test_API_AUT_12_name_longer_than_100_returns_400(api):
    assert api.post("/api/auth/register", json={**NEW_USER, "name": "N" * 101}).status_code == 400


def test_API_AUT_13_name_of_exactly_100_is_accepted(api):
    assert api.post("/api/auth/register", json={**NEW_USER, "name": "N" * 100}).status_code == 201


@pytest.mark.parametrize("phone", ["12345", "abcdefghij", "9" * 16, "98765 43210", 9876543210])
def test_API_AUT_14_invalid_phone_returns_400(api, phone):
    assert api.post("/api/auth/register", json={**NEW_USER, "phone": phone}).status_code == 400


@pytest.mark.parametrize("field,value", [("name", 123), ("email", {"a": 1}), ("password", ["x"]), ("name", True)])
def test_API_AUT_15_wrong_data_types_return_400_not_500(api, field, value):
    assert api.post("/api/auth/register", json={**NEW_USER, field: value}).status_code == 400


def test_API_AUT_16_password_is_stored_as_bcrypt_hash_not_plaintext(api, db):
    api.post("/api/auth/register", json=NEW_USER)
    stored = scalar(db, "SELECT password_hash FROM users WHERE email = %s", (NEW_USER["email"],))
    assert stored != NEW_USER["password"] and stored.startswith("$2") and len(stored) == 60


def test_API_AUT_17_same_password_gets_different_hashes(api, db):
    api.post("/api/auth/register", json=NEW_USER)
    api.post("/api/auth/register", json={**NEW_USER, "email": "dave@example.com"})
    hashes = [r["password_hash"] for r in rows(db, "SELECT password_hash FROM users WHERE user_id > 3")]
    assert len(hashes) == 2 and hashes[0] != hashes[1]       # per-user salt


def test_API_AUT_18_cannot_register_as_admin(api, db):
    r = api.post("/api/auth/register", json={**NEW_USER, "role": "admin"})
    assert r.status_code == 201
    assert scalar(db, "SELECT role FROM users WHERE user_id = %s", (r.json()["user_id"],)) == "customer"


def test_API_AUT_19_simultaneous_duplicate_registrations_give_one_201_and_rest_409(api, db):
    """Race condition: 6 identical registrations at once must never produce a 500."""
    results = parallel([lambda: api.post("/api/auth/register", json=NEW_USER).status_code for _ in range(6)])
    assert results.count(201) == 1
    assert results.count(409) == 5
    assert scalar(db, "SELECT COUNT(*) FROM users WHERE email = %s", (NEW_USER["email"],)) == 1


def test_API_AUT_20_malformed_json_returns_400(api):
    r = api.post("/api/auth/register", data="{not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 400 and "error" in r.json()


def test_API_AUT_21_email_is_stored_in_lower_case(api, db):
    api.post("/api/auth/register", json={**NEW_USER, "email": "Carol@Example.COM"})
    assert scalar(db, "SELECT email FROM users WHERE user_id > 3") == "carol@example.com"


# ------------------------------------------------------------------- login
def test_API_AUT_22_login_with_valid_credentials(api):
    r = api.post("/api/auth/login", json={"email": "alice@example.com", "password": "password123"})
    body = r.json()
    assert r.status_code == 200
    assert body["token"] and body["user"]["email"] == "alice@example.com" and body["user"]["role"] == "customer"


def test_API_AUT_23_admin_login_returns_admin_role(api):
    r = api.post("/api/auth/login", json={"email": "admin@example.com", "password": "password123"})
    assert r.status_code == 200 and r.json()["user"]["role"] == "admin"


def test_API_AUT_24_wrong_password_returns_401(api):
    r = api.post("/api/auth/login", json={"email": "alice@example.com", "password": "wrong-password"})
    assert r.status_code == 401


def test_API_AUT_25_unknown_email_returns_same_401_as_wrong_password(api):
    wrong_pw = api.post("/api/auth/login", json={"email": "alice@example.com", "password": "nope"})
    no_user = api.post("/api/auth/login", json={"email": "nobody@example.com", "password": "nope"})
    assert no_user.status_code == 401
    assert no_user.json() == wrong_pw.json()          # no hint about which emails exist


@pytest.mark.parametrize("body", [{}, {"email": "alice@example.com"}, {"password": "password123"},
                                  {"email": "", "password": ""}])
def test_API_AUT_26_missing_credentials_return_400(api, body):
    assert api.post("/api/auth/login", json=body).status_code == 400


def test_API_AUT_27_login_email_is_case_insensitive(api):
    r = api.post("/api/auth/login", json={"email": "ALICE@EXAMPLE.COM", "password": "password123"})
    assert r.status_code == 200


@pytest.mark.parametrize("body", [{"email": {"$ne": None}, "password": "x"},
                                  {"email": "alice@example.com", "password": {"$ne": None}},
                                  {"email": ["alice@example.com"], "password": "password123"}])
def test_API_AUT_28_non_string_credentials_return_400(api, body):
    assert api.post("/api/auth/login", json=body).status_code == 400


def test_API_AUT_29_token_contains_identity_and_expires_in_two_hours(api):
    token = api.login("alice@example.com")
    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["user_id"] == 1 and claims["email"] == "alice@example.com" and claims["role"] == "customer"
    assert claims["exp"] - claims["iat"] == 2 * 60 * 60


def test_API_AUT_30_login_response_never_contains_password_data(api):
    r = api.post("/api/auth/login", json={"email": "alice@example.com", "password": "password123"})
    assert "password" not in r.text.lower() and "$2b$" not in r.text


# ---------------------------------------------------------------- profile
def test_API_AUT_31_me_returns_the_logged_in_user(api, alice):
    r = api.get("/api/auth/me", alice)
    assert r.status_code == 200
    assert r.json()["email"] == "alice@example.com" and "password_hash" not in r.json()


def test_API_AUT_32_me_without_token_returns_401(api):
    assert api.get("/api/auth/me").status_code == 401


def test_API_AUT_33_me_with_garbage_token_returns_401(api):
    assert api.get("/api/auth/me", "not.a.token").status_code == 401


def test_API_AUT_34_update_profile_changes_name_and_phone(api, alice, db):
    r = api.put("/api/auth/me", alice, {"name": "Alice Updated", "phone": "9000000001"})
    assert r.status_code == 200 and r.json()["user"]["name"] == "Alice Updated"
    assert one(db, "SELECT name, phone FROM users WHERE user_id = 1") == {"name": "Alice Updated", "phone": "9000000001"}


def test_API_AUT_35_update_profile_without_name_returns_400(api, alice):
    assert api.put("/api/auth/me", alice, {"phone": "9000000001"}).status_code == 400


def test_API_AUT_36_update_profile_cannot_change_email_or_role(api, alice, db):
    api.put("/api/auth/me", alice, {"name": "Alice", "email": "evil@example.com", "role": "admin"})
    assert one(db, "SELECT email, role FROM users WHERE user_id = 1") == {"email": "alice@example.com", "role": "customer"}


def test_API_AUT_37_update_profile_with_overlong_name_returns_400(api, alice):
    assert api.put("/api/auth/me", alice, {"name": "N" * 101}).status_code == 400


def test_API_AUT_38_update_profile_with_invalid_phone_returns_400(api, alice):
    assert api.put("/api/auth/me", alice, {"name": "Alice", "phone": "abc"}).status_code == 400


def test_API_AUT_39_update_profile_only_affects_the_logged_in_user(api, alice, db):
    api.put("/api/auth/me", alice, {"name": "Changed"})
    assert scalar(db, "SELECT name FROM users WHERE user_id = 2") == "Bob Smith"
