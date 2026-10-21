"""API testing: security (token handling, injection, hardening) (API-SEC-xx)."""
import base64
import json
import time

import jwt
import pytest

import config
from api_client import parallel
from helpers import balance, run, scalar

pytestmark = pytest.mark.api

SECRET = config.TEST_JWT_SECRET


def make_token(payload=None, secret=SECRET, algorithm="HS256"):
    claims = {"user_id": 1, "email": "alice@example.com", "role": "customer",
              "iat": int(time.time()), "exp": int(time.time()) + 3600}
    claims.update(payload or {})
    return jwt.encode(claims, secret, algorithm=algorithm)


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


# ----------------------------------------------------------- token handling
def test_API_SEC_01_a_correctly_signed_token_is_accepted(api):
    """Positive control for the forging helper: if this fails, the other token tests mean nothing."""
    assert api.get("/api/auth/me", make_token()).status_code == 200


def test_API_SEC_02_expired_token_is_rejected(api):
    assert api.get("/api/auth/me", make_token({"exp": int(time.time()) - 10})).status_code == 401


def test_API_SEC_03_token_signed_with_another_secret_is_rejected(api):
    assert api.get("/api/auth/me", make_token(secret="some-other-secret-value-0123456789abcdef")).status_code == 401


def test_API_SEC_04_unsigned_token_alg_none_is_rejected(api):
    header = b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    body = b64(json.dumps({"user_id": 3, "email": "admin@example.com", "role": "admin",
                           "exp": int(time.time()) + 3600}).encode())
    assert api.get("/api/admin/stats", f"{header}.{body}.").status_code == 401


def test_API_SEC_05_payload_edited_after_signing_is_rejected(api, alice):
    """Take Alice's real token and rewrite the payload to claim admin, keeping her signature."""
    header, _payload, signature = alice.split(".")
    forged = b64(json.dumps({"user_id": 3, "email": "admin@example.com", "role": "admin",
                             "exp": int(time.time()) + 3600}).encode())
    assert api.get("/api/admin/stats", f"{header}.{forged}.{signature}").status_code == 401


@pytest.mark.parametrize("token", ["garbage", "a.b.c", "....", "null", "undefined", "Bearer"])
def test_API_SEC_06_malformed_tokens_are_rejected(api, token):
    assert api.get("/api/auth/me", token).status_code == 401


@pytest.mark.parametrize("header", ["Basic YWxpY2U6cGFzc3dvcmQ=", "Token abc", "bearer abc", "abc"])
def test_API_SEC_07_wrong_authorization_scheme_is_rejected(api, alice, header):
    assert api.get("/api/auth/me", headers={"Authorization": header}).status_code == 401


def test_API_SEC_08_token_passed_in_query_string_is_ignored(api, alice):
    assert api.get(f"/api/auth/me?token={alice}").status_code == 401


def test_API_SEC_09_valid_token_for_a_deleted_user_is_rejected(api, alice, db):
    run(db, "SET FOREIGN_KEY_CHECKS = 0")
    run(db, "DELETE FROM users WHERE user_id = 1")
    run(db, "SET FOREIGN_KEY_CHECKS = 1")
    assert api.get("/api/auth/me", alice).status_code == 401


def test_API_SEC_10_validly_signed_token_for_a_nonexistent_user_is_rejected(api):
    assert api.get("/api/auth/me", make_token({"user_id": 9999})).status_code == 401


def test_API_SEC_11_role_claim_inside_the_token_is_not_trusted(api):
    """Signed with the real secret and claiming admin, but the database says customer."""
    token = make_token({"user_id": 1, "role": "admin"})
    assert api.get("/api/admin/stats", token).status_code == 403


def test_API_SEC_12_token_cannot_be_used_to_act_as_another_user(api, alice, db):
    """Changing the account_id in the request body never reaches another user's money."""
    assert api.withdraw(alice, 2, 100).status_code == 404
    assert api.transfer(alice, 2, 1, 100).status_code == 404
    assert balance(db, 2) == 3000


# ---------------------------------------------------------------- injection
SQLI = ["' OR '1'='1", "' OR 1=1 --", "admin@example.com'--", "'; DROP TABLE users; --",
        "\" OR \"\"=\"", "1' UNION SELECT * FROM users --"]


@pytest.mark.parametrize("payload", SQLI)
def test_API_SEC_13_sql_injection_in_login_email_does_not_log_anyone_in(api, db, payload):
    r = api.post("/api/auth/login", json={"email": payload, "password": payload})
    assert r.status_code == 401
    assert scalar(db, "SELECT COUNT(*) FROM users") == 3


@pytest.mark.parametrize("payload", SQLI)
def test_API_SEC_14_sql_injection_in_register_name_is_stored_as_text(api, db, payload):
    r = api.post("/api/auth/register", json={"name": payload, "email": "inj@example.com", "password": "Passw0rd!"})
    assert r.status_code == 201
    assert scalar(db, "SELECT name FROM users WHERE email = 'inj@example.com'") == payload
    assert scalar(db, "SELECT COUNT(*) FROM users") == 4


def test_API_SEC_15_script_tags_are_stored_and_returned_as_json_text(api, alice):
    xss = "<script>alert(1)</script>"
    api.put("/api/auth/me", alice, {"name": xss})
    r = api.get("/api/auth/me", alice)
    assert r.headers["Content-Type"].startswith("application/json")      # never rendered as HTML
    assert r.json()["name"] == xss


@pytest.mark.parametrize("bad_id", ["1 OR 1=1", "1;DROP TABLE accounts", "1%20UNION%20SELECT%201", "-1", "1e1"])
def test_API_SEC_16_sql_injection_in_url_ids_returns_400(api, alice, db, bad_id):
    assert api.get(f"/api/accounts/{bad_id}", alice).status_code == 400
    assert scalar(db, "SELECT COUNT(*) FROM accounts") == 2


def test_API_SEC_17_object_instead_of_value_cannot_change_the_query(api, alice, db):
    """mysql2's query() expands objects into SQL fragments; the validators must stop that first."""
    r = api.post("/api/transactions/withdraw", alice, {"account_id": {"user_id": 2}, "amount": 1})
    assert r.status_code == 400
    assert balance(db, 2) == 3000


# ------------------------------------------------------ input and transport
def test_API_SEC_18_malformed_json_returns_400_json_error(api):
    r = api.post("/api/auth/login", data='{"email": ', headers={"Content-Type": "application/json"})
    assert r.status_code == 400 and r.json() == {"error": "Malformed JSON body"}


def test_API_SEC_19_oversized_body_returns_413(api):
    r = api.post("/api/auth/register", json={"name": "x" * 200_000, "email": "a@b.co", "password": "Passw0rd!"})
    assert r.status_code == 413


def test_API_SEC_20_non_json_content_type_returns_400_not_500(api):
    r = api.post("/api/auth/login", data="email=a&password=b", headers={"Content-Type": "text/plain"})
    assert r.status_code == 400


def test_API_SEC_21_empty_request_body_returns_400_not_500(api):
    assert api.post("/api/auth/register").status_code == 400
    assert api.post("/api/transactions/deposit", api.login("alice@example.com")).status_code == 400


def test_API_SEC_22_json_array_body_returns_400_not_500(api):
    assert api.post("/api/auth/login", json=[1, 2, 3]).status_code == 400


def test_API_SEC_23_unknown_route_returns_json_404(api):
    r = api.get("/api/does-not-exist")
    assert r.status_code == 404 and r.json() == {"error": "Route not found"}


@pytest.mark.parametrize("method,path", [("DELETE", "/api/accounts/1"), ("PUT", "/api/accounts"),
                                         ("PATCH", "/api/transactions"), ("DELETE", "/api/admin/users")])
def test_API_SEC_24_unsupported_methods_are_not_available(api, alice, method, path):
    """Never a 2xx. (Under /api/admin a customer is stopped with 403 before routing, which is fine.)"""
    assert api.request(method, path, alice).status_code in (403, 404, 405)


def test_API_SEC_25_no_response_leaks_password_hashes(api, alice, admin):
    for path, token in [("/api/auth/me", alice), ("/api/accounts", alice), ("/api/admin/users", admin)]:
        assert "$2b$" not in api.get(path, token).text


def test_API_SEC_26_error_responses_do_not_expose_stack_traces_or_sql(api, alice):
    bodies = [api.post("/api/transactions/deposit", alice, {"account_id": "x", "amount": "y"}).text,
              api.get("/api/accounts/abc", alice).text,
              api.post("/api/auth/login", json=["x"]).text]
    for body in bodies:
        assert "at Object" not in body and "node_modules" not in body and "SQL" not in body.upper().split('"ERROR"')[0]


def test_API_SEC_27_health_endpoint_is_public_and_minimal(api):
    r = api.get("/api/health")
    assert r.status_code == 200 and set(r.json()) == {"status", "message"}


def test_API_SEC_28_cors_preflight_allows_the_authorization_header(api):
    r = api.request("OPTIONS", "/api/accounts", headers={
        "Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization"})
    assert r.status_code in (200, 204)
    assert "authorization" in r.headers.get("Access-Control-Allow-Headers", "").lower()


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
@pytest.mark.xfail(reason="KNOWN GAP (reported, not fixed): Express sends 'X-Powered-By: Express', "
                          "which tells attackers which framework to target. Fix: app.disable('x-powered-by') or helmet.",
                   strict=False)
def test_API_SEC_30_server_does_not_advertise_its_framework(api):
    assert "X-Powered-By" not in api.get("/api/health").headers


@pytest.mark.xfail(reason="KNOWN GAP (reported, not fixed): CORS allows every origin ('*') by default. "
                          "Fix: set CORS_ORIGIN in .env to the frontend's address.",
                   strict=False)
def test_API_SEC_31_cors_is_not_open_to_every_origin(api):
    r = api.get("/api/health", headers={"Origin": "http://evil.example"})
    assert r.headers.get("Access-Control-Allow-Origin") != "*"


@pytest.mark.xfail(reason="KNOWN GAP (reported, not fixed): there is no rate limiting, so passwords can be "
                          "guessed without limit. Fix: express-rate-limit on /api/auth/login.",
                   strict=False)
def test_API_SEC_32_repeated_failed_logins_are_throttled(api):
    codes = [api.post("/api/auth/login", json={"email": "alice@example.com", "password": f"wrong{i}"}).status_code
             for i in range(25)]
    assert 429 in codes


def test_API_SEC_33_placeholder_jwt_secret_is_not_used_by_the_real_app():
    """Reads the REAL backend/.env. If this fails, change JWT_SECRET to a long random string."""
    secret = config.REAL_JWT_SECRET
    if not secret:
        pytest.skip("backend/.env not present (e.g. in CI), nothing to check")
    assert not secret.startswith("change_this") and len(secret) >= 32, \
        "JWT_SECRET in backend/.env is still the placeholder: anyone who knows it can forge admin tokens"
