"""
Send edu.yoisho.in's own /login page to the one login page.

Inert until site_config `sso_login_url` is set (e.g.
"https://accounts.yoisho.in/login"), so the app can be installed before
accounts.yoisho.in exists. `/login?local=1` still shows Frappe's own form — a
break-glass door for Administrator if accounts.yoisho.in is ever down.
Only the /login PAGE is redirected; /api/method/login, which accounts.yoisho.in
itself calls, is untouched.
"""

from urllib.parse import urlencode


def build_redirect(sso_login_url, host, scheme, redirect_to):
    """The accounts URL to send a /login visitor to, returning them here after.

    `redirect_to` is Frappe's own `redirect-to` value — a path on this host. It
    is only accepted as a path ("/app/..."), never as an absolute or
    protocol-relative URL, so this cannot be used to bounce people elsewhere.
    """
    path = redirect_to if (redirect_to or "").startswith("/") and not redirect_to.startswith("//") else "/app"
    back = f"{scheme or 'https'}://{host}{path}"
    sep = "&" if "?" in sso_login_url else "?"
    return f"{sso_login_url}{sep}{urlencode({'redirect_to': back})}"


def redirect_login_page():
    """before_request hook."""
    import frappe
    from werkzeug.exceptions import HTTPException
    from werkzeug.utils import redirect

    sso_login_url = frappe.conf.get("sso_login_url")
    request = getattr(frappe.local, "request", None)
    if not sso_login_url or not request:
        return
    if request.method != "GET" or request.path.rstrip("/") != "/login":
        return
    if request.args.get("local"):
        return
    if getattr(frappe.session, "user", "Guest") != "Guest":
        return  # Frappe's own /login already sends a signed-in user on

    target = build_redirect(sso_login_url, request.host, request.scheme, request.args.get("redirect-to"))
    # Raised, not returned: before_request return values are ignored, and
    # frappe/app.py returns any werkzeug HTTPException as the response.
    raise HTTPException(response=redirect(target, 302))
