"""Accessibility testing (Playwright + axe-core): WCAG 2.1 A/AA scans, landmarks and
headings, labels, keyboard use, focus visibility, screen-reader announcements,
reflow on small screens (ACC-xx).

axe-core is the same engine used by browser "Accessibility" audits. It finds the
problems a machine can detect reliably; the keyboard / announcement / reflow tests
cover things it cannot.
"""
import pytest
from axe_playwright_python.sync_playwright import Axe
from playwright.sync_api import expect


pytestmark = [pytest.mark.ui, pytest.mark.accessibility]

WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]
BEST_PRACTICE_TAGS = ["best-practice"]

# (page key, path, who must be logged in or None)
PAGES = [
    ("landing", "/index.html", None),
    ("login", "/login.html", None),
    ("register", "/register.html", None),
    ("dashboard", "/dashboard.html", "alice@example.com"),
    ("account-details", "/account-details.html", "alice@example.com"),
    ("profile", "/profile.html", "alice@example.com"),
    ("admin", "/admin.html", "admin@example.com"),
]


def open_page(ui, path, who):
    """Open a page in a realistic state (logged in where needed, data loaded)."""
    if who:
        ui.login_as(who, "/login.html")
        if path.startswith("/account-details"):
            ui.page.evaluate("sessionStorage.setItem('viewAccountId', '1')")
        ui.goto(path)
        ui.page.wait_for_load_state("networkidle")
    else:
        ui.goto(path)
        ui.page.wait_for_load_state("networkidle")


def scan(page, tags):
    result = Axe().run(page, options={"runOnly": {"type": "tag", "values": tags}})
    return result.response["violations"]


def describe(violations):
    lines = []
    for v in violations:
        targets = ", ".join(str(n["target"][0]) for n in v["nodes"][:4])
        lines.append(f"[{v['impact']}] {v['id']} ({len(v['nodes'])} element(s): {targets}): {v['help']}")
    return "\n".join(lines)


def page_params(prefix_start):
    return [pytest.param(path, who, id=f"ACC-{prefix_start + i:02d}-{key}")
            for i, (key, path, who) in enumerate(PAGES)]


# ------------------------------------------------- A. WCAG 2.1 A/AA automated scan
@pytest.mark.parametrize("path,who", page_params(1))
def test_wcag_a_aa_scan_finds_no_violations(ui, path, who):
    """ACC-01..07: axe-core WCAG 2.0/2.1 level A and AA rules: colour contrast, labels,
    names for buttons and links, valid ARIA, image alternatives, and so on."""
    open_page(ui, path, who)
    violations = scan(ui.page, WCAG_TAGS)
    assert not violations, "WCAG violations:\n" + describe(violations)


# ------------------------------------------------- B. best-practice scan
@pytest.mark.parametrize("path,who", page_params(8))
def test_best_practice_scan_landmarks_and_headings(ui, path, who):
    """ACC-08..14: axe best-practice rules: one main landmark, one h1, heading order,
    all content inside landmarks (these make screen-reader navigation workable)."""
    open_page(ui, path, who)
    violations = scan(ui.page, BEST_PRACTICE_TAGS)
    assert not violations, "Best-practice violations:\n" + describe(violations)


# ------------------------------------------------- C. targeted checks
def test_ACC_15_every_page_declares_its_language(ui):
    bad = []
    for key, path, who in PAGES:
        open_page(ui, path, who)
        if not ui.page.evaluate("document.documentElement.lang"):
            bad.append(key)
    assert not bad, f"No lang attribute on: {bad}"


def test_ACC_16_every_page_has_a_unique_descriptive_title(ui):
    titles = {}
    for key, path, who in PAGES:
        open_page(ui, path, who)
        titles[key] = ui.page.title().strip()
    assert all(len(t) >= 5 for t in titles.values()), titles
    assert len(set(titles.values())) == len(titles), f"Duplicate page titles: {titles}"


def test_ACC_17_every_form_control_has_an_accessible_name(ui):
    """Each input/select/textarea needs a <label for>, aria-label or aria-labelledby."""
    missing = []
    js = """() => [...document.querySelectorAll('input:not([type=hidden]), select, textarea')]
        .filter(e => !(e.labels && e.labels.length) && !e.getAttribute('aria-label') && !e.getAttribute('aria-labelledby'))
        .map(e => e.id || e.name || e.type)"""
    for key, path, who in PAGES:
        open_page(ui, path, who)
        missing += [f"{key}:{name}" for name in ui.page.evaluate(js)]
    assert not missing, f"Form controls without a label: {missing}"


def test_ACC_18_login_can_be_completed_with_the_keyboard_only(ui):
    ui.goto("/login.html")
    ui.page.focus("#email")
    ui.page.keyboard.type("alice@example.com")
    ui.page.keyboard.press("Tab")
    ui.page.keyboard.type("password123")
    ui.page.keyboard.press("Enter")          # submits the form, no mouse
    ui.page.wait_for_url("**/dashboard.html")


def test_ACC_19_tab_order_on_login_follows_reading_order(ui):
    ui.goto("/login.html")
    ui.page.focus("body")
    seen = []
    for _ in range(8):
        ui.page.keyboard.press("Tab")
        seen.append(ui.page.evaluate("document.activeElement.id || document.activeElement.textContent.trim().slice(0, 20)"))
    assert "email" in seen and "password" in seen and "Login" in seen, seen
    assert seen.index("email") < seen.index("password") < seen.index("Login"), seen


def test_ACC_20_keyboard_focus_is_visibly_indicated_on_inputs_and_buttons(ui):
    """WCAG 2.4.7: something (outline, border, shadow) must change when an element is focused."""
    ui.goto("/login.html")
    probe = """sel => {
        const el = document.querySelector(sel);
        const style = () => { const c = getComputedStyle(el);
            return [c.outlineStyle + c.outlineWidth, c.borderColor, c.boxShadow, c.backgroundColor].join('|'); };
        el.blur(); const before = style(); el.focus(); return [before, style()]; }"""
    for sel in ("#email", "#password", "#loginForm button[type=submit]", ".nav-links a"):
        ui.page.keyboard.press("Tab")                       # move into keyboard modality
        before, after = ui.page.evaluate(probe, sel)
        assert before != after, f"{sel}: no visual change when focused ({after})"


def test_ACC_21_login_error_is_announced_to_screen_readers(ui):
    """The error box must be a live region (role=alert / aria-live) so a screen-reader user
    hears it without having to hunt for it."""
    ui.goto("/login.html")
    live = ui.page.eval_on_selector(
        "#errorMsg", "e => e.getAttribute('role') === 'alert' || ['polite','assertive'].includes(e.getAttribute('aria-live'))")
    assert live, "#errorMsg is not a live region"
    ui.login_via_form("alice@example.com", "wrong-password")
    expect(ui.page.locator("#errorMsg")).not_to_be_empty()


def test_ACC_22_register_success_and_error_messages_are_live_regions(ui):
    ui.goto("/register.html")
    for sel in ("#errorMsg", "#successMsg"):
        live = ui.page.eval_on_selector(
            sel, "e => ['alert','status'].includes(e.getAttribute('role')) || ['polite','assertive'].includes(e.getAttribute('aria-live'))")
        assert live, f"{sel} is not a live region"


def test_ACC_23_dashboard_forms_report_errors_in_a_live_region(ui):
    ui.login_as("alice@example.com", "/dashboard.html")
    for sel in ("#txnError", "#newAccountError"):
        live = ui.page.eval_on_selector(
            sel, "e => ['alert','status'].includes(e.getAttribute('role')) || ['polite','assertive'].includes(e.getAttribute('aria-live'))")
        assert live, f"{sel} is not a live region"


def test_ACC_24_login_page_with_an_error_showing_still_passes_wcag(ui):
    ui.login_via_form("alice@example.com", "wrong-password")
    expect(ui.page.locator("#errorMsg")).not_to_be_empty()
    violations = scan(ui.page, WCAG_TAGS)
    assert not violations, describe(violations)


def test_ACC_25_account_page_with_transactions_still_passes_wcag(ui, api):
    """The statement table is built from data; scan it when it actually has rows."""
    token = api.login("alice@example.com")
    api.deposit(token, 1, "25.00")
    api.withdraw(token, 1, "10.00")
    api.transfer(token, 1, 2, "5.00")
    open_page(ui, "/account-details.html", "alice@example.com")
    expect(ui.page.locator("#statementBody tr")).to_have_count(3)
    violations = scan(ui.page, WCAG_TAGS)
    assert not violations, describe(violations)


def test_ACC_26_admin_tables_with_data_still_pass_wcag(ui, api):
    token = api.login("alice@example.com")
    api.deposit(token, 1, "25.00")
    open_page(ui, "/admin.html", "admin@example.com")
    expect(ui.page.locator("#usersBody tr").first).to_be_visible()
    violations = scan(ui.page, WCAG_TAGS)
    assert not violations, describe(violations)


def test_ACC_27_data_tables_have_header_cells(ui, api):
    token = api.login("alice@example.com")
    api.deposit(token, 1, "25.00")
    problems = []
    for path, who in (("/account-details.html", "alice@example.com"), ("/admin.html", "admin@example.com")):
        open_page(ui, path, who)
        problems += ui.page.evaluate(
            "() => [...document.querySelectorAll('table')].filter(t => !t.querySelector('th')).map(t => t.id || 'table')")
    assert not problems, f"Tables with no header cells: {problems}"


@pytest.mark.parametrize("path,who", [pytest.param(p, w, id=f"ACC-28-{k}") for k, p, w in PAGES[:3]]
                         + [pytest.param(p, w, id=f"ACC-29-{k}") for k, p, w in PAGES[3:]])
def test_page_reflows_at_320px_without_horizontal_scrolling(ui, path, who):
    """ACC-28/29 (WCAG 1.4.10 Reflow): at 320 CSS px wide (a phone, or a desktop at 400% zoom)
    the page must not need sideways scrolling."""
    ui.page.set_viewport_size({"width": 320, "height": 700})
    open_page(ui, path, who)
    assert not ui.has_horizontal_scroll(), f"{path} scrolls horizontally at 320px"


def test_ACC_30_text_can_be_enlarged_to_200_percent_without_losing_content(ui):
    """WCAG 1.4.4: with the browser's text size doubled, the login form must stay usable."""
    ui.goto("/login.html")
    ui.page.add_style_tag(content="html { font-size: 200% !important; }")
    expect(ui.page.locator("#loginForm button[type=submit]")).to_be_visible()
    box = ui.page.locator("#loginForm button[type=submit]").bounding_box()
    assert box and box["x"] >= 0 and box["x"] + box["width"] <= ui.page.viewport_size["width"], box


def test_ACC_31_pages_do_not_rely_on_alert_dialogs_for_form_errors(ui):
    """Login and register report validation problems inline; no blocking alert() box."""
    ui.login_via_form("alice@example.com", "wrong-password")
    expect(ui.page.locator("#errorMsg")).not_to_be_empty()
    assert ui.dialogs == []
