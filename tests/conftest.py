import os
import shutil
import subprocess
import time

import pymysql
import pytest
import requests

import config
from api_client import Api
from helpers import connect, run, run_sql_file


@pytest.fixture(scope="session", autouse=True)
def test_database():
    """Create a fresh bank_app_test database once per test run, using the real
    schema.sql plus the 001_hardening.sql migration (the same files your app uses)."""
    admin = connect(database=None)
    run(admin, f"DROP DATABASE IF EXISTS `{config.TEST_DB_NAME}`")
    run(admin, f"CREATE DATABASE `{config.TEST_DB_NAME}`")
    admin.close()

    conn = connect()
    run_sql_file(conn, config.SCHEMA_FILE)
    run_sql_file(conn, config.HARDENING_FILE)
    conn.close()
    yield


@pytest.fixture(autouse=True)
def reset_data(test_database):
    """Before every test: empty all tables and reload seed.sql, so tests never
    depend on each other. Seed gives users 1-3, branches 1-3, accounts 1 (5000) and 2 (3000)."""
    conn = connect()
    run(conn, "SET FOREIGN_KEY_CHECKS = 0")
    for table in ("audit_log", "loans", "transactions", "accounts", "users", "branches"):
        run(conn, f"TRUNCATE TABLE {table}")
    run(conn, "SET FOREIGN_KEY_CHECKS = 1")
    run_sql_file(conn, config.SEED_FILE)
    conn.close()
    yield


@pytest.fixture
def db():
    conn = connect()
    yield conn
    conn.close()


# --------------------------------------------------------------------------
# API tests: start the real backend (node server.js) against bank_app_test
# --------------------------------------------------------------------------
@pytest.fixture(scope="session")
def api_server(test_database):
    node = shutil.which("node")
    if not node:
        pytest.fail("Node.js was not found on PATH, so the backend cannot be started for API tests")

    env = os.environ.copy()
    env.update({
        "DB_HOST": config.DB_HOST,
        "DB_USER": config.DB_USER,
        "DB_PASSWORD": config.DB_PASSWORD,
        "DB_NAME": config.TEST_DB_NAME,      # the TEST database, never bank_app
        "PORT": str(config.API_PORT),
        "JWT_SECRET": config.TEST_JWT_SECRET,
    })

    config.REPORTS_DIR.mkdir(exist_ok=True)
    log = open(config.REPORTS_DIR / "backend_server.log", "w", encoding="utf-8")
    proc = subprocess.Popen([node, "server.js"], cwd=config.ROOT / "backend", env=env,
                            stdout=log, stderr=subprocess.STDOUT)

    base = config.API_BASE_URL
    started = False
    for _ in range(60):
        if proc.poll() is not None:
            break
        try:
            if requests.get(base + "/api/health", timeout=1).status_code == 200:
                started = True
                break
        except requests.RequestException:
            time.sleep(0.5)
    if not started:
        proc.terminate()
        log.close()
        tail = (config.REPORTS_DIR / "backend_server.log").read_text(encoding="utf-8")[-1500:]
        pytest.fail(f"Backend did not start on {base}. Server log:\n{tail}")

    yield base
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    log.close()


@pytest.fixture
def api(api_server):
    return Api(api_server)


@pytest.fixture
def alice(api):
    return api.login("alice@example.com")


@pytest.fixture
def bob(api):
    return api.login("bob@example.com")


@pytest.fixture
def admin(api):
    return api.login("admin@example.com")


# --------------------------------------------------------------------------
# UI tests: serve the real frontend folder and drive it with Playwright
# --------------------------------------------------------------------------
@pytest.fixture(scope="session")
def ui_server(api_server):
    """Serves frontend/ over HTTP. The only change: js/api.js has its hard-coded
    http://localhost:5000/api pointed at the TEST backend. Real CORS still applies
    because the page and the API are on different ports, just like in production use."""
    import functools
    import threading
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    if not config.FRONTEND_DIR.exists():
        pytest.fail(f"frontend folder not found at {config.FRONTEND_DIR}")

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path.split("?")[0] == "/js/api.js":
                src = (config.FRONTEND_DIR / "js" / "api.js").read_text(encoding="utf-8")
                body = src.replace("http://localhost:5000/api", config.API_BASE_URL + "/api").encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

    server = ThreadingHTTPServer(("localhost", config.UI_PORT),
                                 functools.partial(Handler, directory=str(config.FRONTEND_DIR)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield config.UI_BASE_URL
    server.shutdown()


@pytest.fixture(scope="session")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        opts = {"headless": True}
        if config.CHROMIUM_PATH:
            opts["executable_path"] = config.CHROMIUM_PATH
        b = p.chromium.launch(**opts)
        yield b
        b.close()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    setattr(item, "rep_" + report.when, report)


@pytest.fixture
def ui(request, browser, ui_server, api):
    """A fresh browser context (empty localStorage) per test, wrapped in a helper.
    If the test fails, a screenshot is saved to tests/reports/screenshots/."""
    from ui_client import UI
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    context.set_default_timeout(8000)
    helper = UI(context.new_page(), ui_server, api)
    yield helper
    failed = getattr(request.node, "rep_call", None) is not None and request.node.rep_call.failed
    if failed:
        try:
            helper.shot("FAILED_" + request.node.name)
        except Exception:
            pass
    context.close()
