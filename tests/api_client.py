"""Tiny HTTP client used by the API tests."""
from concurrent.futures import ThreadPoolExecutor

import requests

PASSWORD = "password123"


class Api:
    def __init__(self, base):
        self.base = base

    def request(self, method, path, token=None, json=None, headers=None, data=None):
        h = dict(headers or {})
        if token:
            h["Authorization"] = f"Bearer {token}"
        return requests.request(method, self.base + path, json=json, data=data, headers=h, timeout=30)

    def get(self, path, token=None, **kw):
        return self.request("GET", path, token, **kw)

    def post(self, path, token=None, json=None, **kw):
        return self.request("POST", path, token, json=json, **kw)

    def put(self, path, token=None, json=None, **kw):
        return self.request("PUT", path, token, json=json, **kw)

    def patch(self, path, token=None, json=None, **kw):
        return self.request("PATCH", path, token, json=json, **kw)

    def login(self, email, password=PASSWORD):
        r = self.post("/api/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, (
            f"Could not log in as {email}: {r.status_code} {r.text}. "
            "Seed data or the auth endpoint is broken, so every API test would fail.")
        return r.json()["token"]

    # convenience wrappers for money endpoints
    def deposit(self, token, account_id, amount):
        return self.post("/api/transactions/deposit", token, {"account_id": account_id, "amount": amount})

    def withdraw(self, token, account_id, amount):
        return self.post("/api/transactions/withdraw", token, {"account_id": account_id, "amount": amount})

    def transfer(self, token, src, dst, amount, **extra):
        return self.post("/api/transactions/transfer", token,
                         {"from_account_id": src, "to_account_id": dst, "amount": amount, **extra})


def parallel(calls):
    """Run zero-argument callables at the same time; return their results in order."""
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = [pool.submit(c) for c in calls]
        return [f.result() for f in futures]
