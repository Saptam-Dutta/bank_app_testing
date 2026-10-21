"""Central test configuration.

DB credentials are read from backend/.env so nothing is hard-coded.
Tests ALWAYS run against a separate database (bank_app_test); your real
bank_app data is never touched.
"""
import os
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
DB_DIR = ROOT / "database"
REPORTS_DIR = Path(__file__).resolve().parent / "reports"
_env = dotenv_values(ROOT / "backend" / ".env")

DB_HOST = os.getenv("TEST_DB_HOST", _env.get("DB_HOST") or "localhost")
DB_PORT = int(os.getenv("TEST_DB_PORT", "3306"))
DB_USER = os.getenv("TEST_DB_USER", _env.get("DB_USER") or "root")
DB_PASSWORD = os.getenv("TEST_DB_PASSWORD", _env.get("DB_PASSWORD") or "")

TEST_DB_NAME = "bank_app_test"

# Backend instance started by the API tests (separate port, so your dev server on 5000 can stay running)
API_PORT = int(os.getenv("TEST_API_PORT", "5055"))
API_BASE_URL = f"http://localhost:{API_PORT}"
# Static web server for the frontend folder, started by the UI tests
UI_PORT = int(os.getenv("TEST_UI_PORT", "5056"))
UI_BASE_URL = f"http://localhost:{UI_PORT}"
FRONTEND_DIR = Path(os.getenv("TEST_FRONTEND_DIR") or ROOT / "frontend")
# Optional: path to a Chromium/Chrome executable (normally not needed; run `playwright install chromium`)
CHROMIUM_PATH = os.getenv("TEST_CHROMIUM_PATH", "")

# Secret used ONLY by the test backend; lets the tests forge tokens for security checks
TEST_JWT_SECRET = "pytest-only-jwt-secret-key-0123456789abcdef"

SCREENSHOT_DIR = REPORTS_DIR / "screenshots"

# The real app's secret, used only to check it is not the placeholder
REAL_JWT_SECRET = _env.get("JWT_SECRET") or ""

# Safety net: refuse to ever point the tests at the real database.
assert TEST_DB_NAME != (_env.get("DB_NAME") or ""), "Test DB must differ from the real DB"

SCHEMA_FILE = DB_DIR / "schema.sql"
HARDENING_FILE = DB_DIR / "001_hardening.sql"
SEED_FILE = DB_DIR / "seed.sql"
