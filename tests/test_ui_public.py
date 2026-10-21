"""UI testing (Playwright): public pages, register, login, route guards (UI-xxx)."""
import re

import pytest
from playwright.sync_api import expect

from helpers import one, rows, scalar

pytestmark = pytest.mark.ui

NEW = {"name": "Carol White", "email": "carol@example.com", "phone": "9123456780", "password": "Secret123!"}


def fill_register(ui, **overrides):
    data = {**NEW, **overrides}
    ui.goto("/register.html")
    ui.page.fill("#name", data["name"])
    ui.page.fill("#email", data["email"])
    ui.page.fill("#phone", data["phone"])
    ui.page.fill("#password", data["password"])
    return data


# ----------------------------------------------------------------- landing
def test_UI_01_landing_page_shows_headline_and_three_feature_cards(ui):
    ui.goto("/index.html")
    expect(ui.page.locator("h1")).to_have_text("Banking, made simple.")
    expect(ui.page.locator(".feature-card")).to_have_count(3)


def test_UI_02_get_started_button_opens_registration(ui):
    ui.goto("/index.html")
    ui.page.click("text=Get Started")
    expect(ui.page).to_have_url(re.compile(r"/register\.html$"))


def test_UI_03_navbar_login_link_opens_login(ui):
    ui.goto("/index.html")
    ui.page.click(".nav-links a[href='login.html']")
    expect(ui.page).to_have_url(re.compile(r"/login\.html$"))


@pytest.mark.parametrize("path,title", [
    ("/index.html", "SecureBank - Simple, Secure Banking"),
    ("/login.html", "Login - SecureBank"),
    ("/register.html", "Register - SecureBank"),
])
def test_UI_04_public_page_titles(ui, path, title):
    ui.goto(path)
    expect(ui.page).to_have_title(title)


@pytest.mark.parametrize("path,title,email", [
    ("/dashboard.html", "Dashboard - SecureBank", "alice@example.com"),
    ("/profile.html", "Profile - SecureBank", "alice@example.com"),
    ("/account-details.html", "Account Details - SecureBank", "alice@example.com"),
    ("/admin.html", "Admin - SecureBank", "admin@example.com"),
])
def test_UI_05_logged_in_page_titles(ui, path, title, email):
    ui.login_as(email, path)
    expect(ui.page).to_have_title(title)


# ---------------------------------------------------------------- register
def test_UI_06_registration_succeeds_and_redirects_to_login(ui, db):
    data = fill_register(ui)
    ui.page.click("#registerForm button[type=submit]")
    expect(ui.page.locator("#successMsg")).to_contain_text("Registration successful")
    expect(ui.page).to_have_url(re.compile(r"/login\.html$"), timeout=6000)
    assert one(db, "SELECT name, role FROM users WHERE email = %s", (data["email"],)) == \
           {"name": "Carol White", "role": "customer"}


def test_UI_07_duplicate_email_shows_error_message(ui):
    fill_register(ui, email="alice@example.com")
    ui.page.click("#registerForm button[type=submit]")
    expect(ui.page.locator("#errorMsg")).to_have_text("Email already registered")
    assert "/register.html" in ui.url


def test_UI_08_empty_registration_form_is_blocked_by_the_browser(ui, db):
    ui.goto("/register.html")
    ui.page.click("#registerForm button[type=submit]")
    assert ui.valid("#registerForm") is False
    assert scalar(db, "SELECT COUNT(*) FROM users") == 3


@pytest.mark.parametrize("email", ["plainaddress", "no-at.com", "a@", "@b.com"])
def test_UI_09_invalid_email_is_blocked_by_the_browser(ui, email):
    fill_register(ui, email=email)
    assert ui.valid("#registerForm") is False


def test_UI_10_password_shorter_than_the_backend_minimum_is_blocked_in_the_browser(ui):
    """The server requires 8+ characters; the form must not let 6 or 7 through."""
    fill_register(ui, password="1234567")
    assert ui.valid("#registerForm") is False


def test_UI_11_server_side_validation_error_is_displayed(ui):
    fill_register(ui, phone="abc")
    ui.page.click("#registerForm button[type=submit]")
    expect(ui.page.locator("#errorMsg")).to_have_text("Phone must be 7 to 15 digits")


def test_UI_12_newly_registered_user_can_log_in_through_the_form(ui):
    data = fill_register(ui)
    ui.page.click("#registerForm button[type=submit]")
    expect(ui.page).to_have_url(re.compile(r"/login\.html$"), timeout=6000)
    ui.login_via_form(data["email"], data["password"])
    expect(ui.page).to_have_url(re.compile(r"/dashboard\.html$"))
    expect(ui.page.locator("#welcomeMsg")).to_have_text("Hi, Carol White")


def test_UI_13_password_field_is_masked(ui):
    ui.goto("/register.html")
    assert ui.page.get_attribute("#password", "type") == "password"
    ui.goto("/login.html")
    assert ui.page.get_attribute("#password", "type") == "password"


# ------------------------------------------------------------------- login
def test_UI_14_customer_login_opens_the_dashboard(ui):
    ui.login_via_form("alice@example.com", "password123")
    expect(ui.page).to_have_url(re.compile(r"/dashboard\.html$"))
    expect(ui.page.locator("#welcomeMsg")).to_have_text("Hi, Alice Johnson")


def test_UI_15_admin_login_opens_the_admin_panel(ui):
    ui.login_via_form("admin@example.com", "password123")
    expect(ui.page).to_have_url(re.compile(r"/admin\.html$"))
    expect(ui.page.locator("#welcomeMsg")).to_have_text("Admin: Admin User")


def test_UI_16_wrong_password_shows_error_and_stores_no_token(ui):
    ui.login_via_form("alice@example.com", "wrong-password")
    expect(ui.page.locator("#errorMsg")).to_have_text("Invalid email or password")
    assert "/login.html" in ui.url and ui.local("token") is None


def test_UI_17_unknown_email_shows_the_same_error(ui):
    ui.login_via_form("nobody@example.com", "password123")
    expect(ui.page.locator("#errorMsg")).to_have_text("Invalid email or password")


def test_UI_18_empty_login_form_is_blocked_by_the_browser(ui):
    ui.goto("/login.html")
    ui.page.click("#loginForm button[type=submit]")
    assert ui.valid("#loginForm") is False and "/login.html" in ui.url


def test_UI_19_successful_login_stores_token_and_user_in_local_storage(ui):
    ui.login_via_form("alice@example.com", "password123")
    expect(ui.page).to_have_url(re.compile(r"/dashboard\.html$"))
    assert ui.local("token") and ui.local("token").count(".") == 2
    assert '"role":"customer"' in ui.local("user") and "password" not in ui.local("user")


def test_UI_20_pressing_enter_submits_the_login_form(ui):
    ui.goto("/login.html")
    ui.page.fill("#email", "alice@example.com")
    ui.page.fill("#password", "password123")
    ui.page.press("#password", "Enter")
    expect(ui.page).to_have_url(re.compile(r"/dashboard\.html$"))


def test_UI_21_sql_injection_text_in_the_password_field_does_not_log_in(ui):
    ui.login_via_form("alice@example.com", "' OR '1'='1")
    expect(ui.page.locator("#errorMsg")).to_have_text("Invalid email or password")
    assert ui.local("token") is None


def test_UI_22_sql_injection_text_in_the_email_field_is_rejected_by_the_browser(ui):
    ui.goto("/login.html")
    ui.page.fill("#email", "' OR 1=1 --")
    ui.page.fill("#password", "x")
    assert ui.valid("#loginForm") is False


def test_UI_23_login_page_links_to_registration(ui):
    ui.goto("/login.html")
    ui.page.click(".link-row a")
    expect(ui.page).to_have_url(re.compile(r"/register\.html$"))


# ------------------------------------------------------------ route guards
@pytest.mark.parametrize("path", ["/dashboard.html", "/profile.html", "/account-details.html", "/admin.html"])
def test_UI_24_protected_pages_redirect_anonymous_visitors_to_login(ui, path):
    ui.goto(path)
    expect(ui.page).to_have_url(re.compile(r"/login\.html$"))


def test_UI_25_customer_opening_the_admin_page_is_sent_to_the_dashboard(ui):
    ui.login_as("alice@example.com", "/admin.html")
    expect(ui.page).to_have_url(re.compile(r"/dashboard\.html$"))


def test_UI_26_logout_clears_the_session_and_returns_to_login(ui):
    ui.login_as("alice@example.com")
    ui.page.click("#logoutBtn")
    expect(ui.page).to_have_url(re.compile(r"/login\.html$"))
    assert ui.local("token") is None and ui.local("user") is None
    ui.goto("/dashboard.html")
    expect(ui.page).to_have_url(re.compile(r"/login\.html$"))


def test_UI_27_invalid_token_sends_the_user_back_to_login(ui):
    """A stale or tampered token must not leave the user on a broken page."""
    ui.set_storage("not.a.valid-token", {"user_id": 1, "name": "Alice Johnson", "role": "customer"})
    ui.goto("/dashboard.html")
    expect(ui.page).to_have_url(re.compile(r"/login\.html$"))


def test_UI_28_editing_the_role_in_local_storage_does_not_unlock_admin_data(ui):
    """Client-side guards are cosmetic; the API must refuse the data."""
    data = ui.login_as("alice@example.com", "/dashboard.html")
    user = {**data["user"], "role": "admin"}
    ui.page.evaluate("u => localStorage.setItem('user', JSON.stringify(u))", user)
    ui.goto("/admin.html")
    ui.page.wait_for_timeout(1200)
    assert "/admin.html" in ui.url                       # the page shell opens...
    expect(ui.page.locator("#statUsers")).to_have_text("—")   # ...but no data arrives
    expect(ui.page.locator("#usersBody tr")).to_have_count(0)


# ------------------------------------------------------- general UI quality
@pytest.mark.parametrize("path", ["/index.html", "/login.html", "/register.html"])
def test_UI_29_public_pages_load_without_errors_or_missing_files(ui, path):
    ui.goto(path)
    ui.page.wait_for_load_state("networkidle")
    assert ui.console_errors == [] and ui.bad_responses == []


@pytest.mark.parametrize("path,email", [("/dashboard.html", "alice@example.com"),
                                        ("/profile.html", "alice@example.com"),
                                        ("/admin.html", "admin@example.com")])
def test_UI_30_logged_in_pages_load_without_errors_or_missing_files(ui, path, email):
    ui.login_as(email, path)
    ui.page.wait_for_load_state("networkidle")
    assert ui.console_errors == [] and ui.bad_responses == []


def test_UI_31_stylesheet_is_applied(ui):
    ui.goto("/index.html")
    colour = ui.page.eval_on_selector(".navbar", "e => getComputedStyle(e).backgroundColor")
    assert colour != "rgba(0, 0, 0, 0)"


@pytest.mark.parametrize("path", ["/index.html", "/login.html", "/register.html"])
def test_UI_32_public_pages_fit_a_phone_screen_without_sideways_scrolling(ui, path):
    ui.page.set_viewport_size({"width": 375, "height": 667})
    ui.goto(path)
    assert ui.has_horizontal_scroll() is False


def test_UI_33_dashboard_fits_a_phone_screen_without_sideways_scrolling(ui):
    ui.page.set_viewport_size({"width": 375, "height": 667})
    ui.login_as("alice@example.com")
    expect(ui.page.locator(".account-card")).to_have_count(1)
    assert ui.has_horizontal_scroll() is False
