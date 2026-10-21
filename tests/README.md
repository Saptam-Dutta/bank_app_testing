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

Everything (database + API), with an HTML report:

```
python -m pytest --html=reports\full_report.html --self-contained-html
```

or double-click `run_all_tests.bat` (venv active). Subsets:

```
python -m pytest -m database      # database layer only (no Node needed)
python -m pytest -m api           # API layer only
python -m pytest -m ui            # browser UI tests only (Playwright)
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

## Expected results on the current code

- **xfailed (4)** are documented gaps that are reported but deliberately not fixed:
  failed transactions not recorded, `X-Powered-By` header, CORS `*`, no login rate limit.
  They show as "expected failures" and are listed in the report as known defects.
- **API-SEC-33** fails until you replace the placeholder `JWT_SECRET` in `backend/.env`
  with a long random string. That is a real security finding, not a test problem.
