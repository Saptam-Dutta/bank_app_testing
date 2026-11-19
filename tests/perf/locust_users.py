"""Virtual users for the Locust load, stress and spike tests (run by the pytest wrappers).

Customer       a realistic customer: logs in once, then mixes reads, deposits, withdrawals and transfers.
HotAccount     many users depositing into the SAME account at once (worst case for row locking).
ProbeUser      one extra user that only measures how fast the API answers while the rest apply pressure;
               every sample is written to a file so the test can see latency before / during / after a spike.
"""
import itertools
import json
import os
import time

from locust import HttpUser, between, constant, task

N_USERS = int(os.getenv("PERF_USERS", "50"))
ACCOUNT_BASE = int(os.getenv("PERF_ACCOUNT_BASE", "3"))     # account_id of load user 0
PROBE_FILE = os.getenv("PERF_PROBE_FILE", "")
PASSWORD = "password123"
_counter = itertools.count()


class _Authenticated(HttpUser):
    abstract = True
    token = None

    def login(self, email):
        with self.client.post("/api/auth/login", json={"email": email, "password": PASSWORD},
                              name="POST /api/auth/login", catch_response=True) as r:
            if r.status_code == 200:
                self.token = r.json()["token"]
                r.success()
            else:
                r.failure(f"login returned {r.status_code}")

    def call(self, method, path, name=None, **kw):
        if not self.token:
            self.login(self.email)
            if not self.token:
                return None
        headers = {"Authorization": f"Bearer {self.token}"}
        return self.client.request(method, path, headers=headers, name=name or f"{method} {path}", **kw)


class Customer(_Authenticated):
    wait_time = between(0.1, 0.5)

    def on_start(self):
        self.i = next(_counter) % N_USERS
        self.email = f"load{self.i}@example.com"
        self.account = ACCOUNT_BASE + self.i
        self.peer = ACCOUNT_BASE + (self.i + 1) % N_USERS
        self.login(self.email)

    @task(5)
    def list_accounts(self):
        self.call("GET", "/api/accounts")

    @task(3)
    def statement(self):
        self.call("GET", f"/api/accounts/{self.account}/statement", name="GET /api/accounts/:id/statement")

    @task(3)
    def history(self):
        self.call("GET", "/api/transactions")

    @task(2)
    def branches(self):
        self.call("GET", "/api/branches")

    @task(2)
    def profile(self):
        self.call("GET", "/api/auth/me")

    @task(3)
    def deposit(self):
        self.call("POST", "/api/transactions/deposit", json={"account_id": self.account, "amount": "5.00"})

    @task(2)
    def withdraw(self):
        self.call("POST", "/api/transactions/withdraw", json={"account_id": self.account, "amount": "2.00"})

    @task(3)
    def transfer(self):
        self.call("POST", "/api/transactions/transfer",
                  json={"from_account_id": self.account, "to_account_id": self.peer, "amount": "1.00"})


class HotAccount(_Authenticated):
    wait_time = constant(0)

    def on_start(self):
        self.email = "alice@example.com"
        self.login(self.email)

    @task
    def deposit_into_the_same_account(self):
        self.call("POST", "/api/transactions/deposit", name="POST deposit (hot account)",
                  json={"account_id": 1, "amount": "1.00"})


class ProbeUser(_Authenticated):
    fixed_count = 1
    wait_time = constant(0.25)

    def on_start(self):
        self.email = "load0@example.com"
        self.login(self.email)

    @task
    def probe(self):
        started = time.time()
        r = self.call("GET", "/api/accounts", name="PROBE GET /api/accounts")
        ms = (time.time() - started) * 1000
        if PROBE_FILE:
            with open(PROBE_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": started, "ms": round(ms, 1), "status": getattr(r, "status_code", 0)}) + "\n")
