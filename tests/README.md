# Python test suite

Place this `tests` folder next to `backend` and `database`:

```
Bank_app/
  backend/
  database/
  frontend/
  tests/        <- this folder
```

## One-time setup (Windows)

```
cd Bank_app\tests
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium      # downloads the test browser (once, ~150 MB)
```

## Run

Everything except the slow load/stress tests (database, API, schema, accessibility, UI), with an HTML report:

```
python -m pytest --html=reports\full_report.html --self-contained-html
```

or double-click `run_all_tests.bat` (venv active). Subsets:

```
python -m pytest -m smoke         # smoke test: a few seconds, run it first after every change
python -m pytest -m database      # database layer only (no Node needed)
python -m pytest -m api           # API layer only
python -m pytest -m schema        # API response-shape (contract) tests
python -m pytest -m ui            # browser UI tests only (Playwright)
python -m pytest -m accessibility # WCAG / keyboard / screen-reader checks
python -m pytest -m performance   # load + database-speed tests (Locust, about 1.5 min)
python -m pytest -m stress        # stress, spike and recovery tests (Locust, about 2.5 min)
python -m pytest -m "performance or stress" --html=reports\load_stress_report.html --self-contained-html
python -m pytest test_api_transactions.py -k "TXN_48"     # one test
```

## How it is isolated

- Each run drops and recreates a separate database, `bank_app_test`, from
  `database/schema.sql` + `database/001_hardening.sql`.
- Before every single test the tables are emptied and `database/seed.sql` is reloaded.
- API tests start their OWN copy of the backend (`node server.js`) on port **5055**,
  pointed at `bank_app_test`. Your dev server on port 5000 can stay running.
- UI tests serve your `frontend` folder on port **5056** and drive it in headless Chromium.
  The only thing changed is the API address inside `js/api.js`, which is pointed at the test
  backend (port 5055); the files on disk are never modified.
- On a failing UI test a screenshot is saved to `reports/screenshots/`.
- Your real `bank_app` database is never touched.
- DB credentials come from `backend/.env`. MySQL must be running; Node must be on PATH.

## Test IDs

| Prefix | Area |
|---|---|
| DB-CON / DB-REF / DB-TRG / DB-TXN / DB-LCK / DB-SCH | constraints, referential integrity, trigger, transactions, locking, schema |
| API-AUT | register, login, profile |
| API-ACC | accounts, statements, branches |
| API-TXN | deposit, withdraw, transfer, history, concurrency |
| API-ADM | admin endpoints, access control |
| API-SEC | tokens, injection, hardening |
| UI | browser tests: landing, register, login, route guards, dashboard, statement, profile, admin panel, XSS |
| SMK | smoke: server up, DB reachable, core flows work (15 checks, seconds) |
| SCH | schema / contract: every response validated against a strict JSON Schema (`schemas.py`) |
| ACC | accessibility: axe-core WCAG 2.1 A/AA scans, landmarks, labels, keyboard, live regions, reflow |
| PRF | performance / load: 25-user Locust run, hot-account run, idle latency, index use on 50,000 rows |
| STR | stress / spike: 150-user step stress, 5->100 user spike with recovery probe, request bursts |

`pytest` on its own skips the `performance` and `stress` tests (they are slow and timing-sensitive);
select them with `-m performance` or `-m stress`. Locust CSVs land in `reports/perf/`.

## Expected results on the current code

- **xfailed (4)** are documented gaps that are reported but deliberately not fixed:
  failed transactions not recorded, `X-Powered-By` header, CORS `*`, no login rate limit.
  They show as "expected failures" and are listed in the report as known defects.
- **API-SEC-33** fails until you replace the placeholder `JWT_SECRET` in `backend/.env`
  with a long random string. That is a real security finding, not a test problem.
