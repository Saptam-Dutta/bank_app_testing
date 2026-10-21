"""Helper wrapper around a Playwright page for the UI tests."""
import json


class UI:
    def __init__(self, page, base, api):
        self.page = page
        self.base = base
        self.api = api
        self.console_errors = []
        self.bad_responses = []
        self.dialogs = []
        page.on("console", self._on_console)
        page.on("pageerror", lambda e: self.console_errors.append(str(e)))
        page.on("response", lambda r: self.bad_responses.append((r.status, r.url))
                if r.status >= 400 and not r.url.endswith("favicon.ico") else None)
        # accept every alert() and remember its text
        page.on("dialog", self._on_dialog)

    def _on_console(self, msg):
        if msg.type == "error" and not msg.location.get("url", "").endswith("favicon.ico"):
            self.console_errors.append(msg.text)

    def _on_dialog(self, dialog):
        self.dialogs.append(dialog.message)
        dialog.accept()

    @property
    def url(self):
        return self.page.url

    def goto(self, path):
        self.page.goto(self.base + path)

    def set_storage(self, token, user):
        """Put a login into localStorage without using the login form."""
        self.goto("/login.html")
        self.page.evaluate(
            "([t, u]) => { localStorage.setItem('token', t); localStorage.setItem('user', JSON.stringify(u)); }",
            [token, user])

    def login_as(self, email, path=None, password="password123"):
        """Log in through the API (fast) and open `path`; by default the page the login form
        would send this user to (admin.html for admins, dashboard.html for customers)."""
        r = self.api.post("/api/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        data = r.json()
        self.set_storage(data["token"], data["user"])
        self.goto(path or ("/admin.html" if data["user"]["role"] == "admin" else "/dashboard.html"))
        return data

    def login_via_form(self, email, password):
        self.goto("/login.html")
        self.page.fill("#email", email)
        self.page.fill("#password", password)
        self.page.click("#loginForm button[type=submit]")

    def wait_dialog(self, timeout_ms=5000):
        """Wait until the page has shown an alert() box; returns its text."""
        waited = 0
        while not self.dialogs and waited < timeout_ms:
            self.page.wait_for_timeout(100)
            waited += 100
        return self.dialogs[-1] if self.dialogs else None

    def shot(self, name):
        import re
        import config
        config.SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)[:120]
        self.page.screenshot(path=str(config.SCREENSHOT_DIR / f"{safe}.png"), full_page=True)

    def local(self, key):
        return self.page.evaluate("k => localStorage.getItem(k)", key)

    def valid(self, form_selector):
        return self.page.eval_on_selector(form_selector, "f => f.checkValidity()")

    def has_horizontal_scroll(self):
        return self.page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
