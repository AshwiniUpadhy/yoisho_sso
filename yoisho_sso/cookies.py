"""
Issue Frappe's session cookie for the whole parent domain.

WHY
    Every Yoisho app (yoisho.in, study., kana., edu.) authenticates against the
    same Frappe users, but each signed people in separately because Frappe's
    `sid` cookie is host-only: set by edu.yoisho.in, sent only to edu.yoisho.in.
    With `Domain=.yoisho.in` the one session reaches every sub-domain, so a
    single login at accounts.yoisho.in signs a person into all of them, and a
    logout anywhere signs them out of all of them.

    Frappe has no setting for this. CookieManager (frappe/auth.py) keeps no
    domain, and `flush_cookies` calls `response.set_cookie` without one — and it
    runs in process_response, AFTER the after_request hooks, so a hook cannot
    add the domain either. Hence a patch of `flush_cookies` itself.

WHAT IT DOES (only when `shared_cookie_domain` is set in site_config and the
request's host is inside that domain — lms_site.com and staging on another
domain are untouched):

    * `sid` is written with Domain=<shared>. ONLY `sid`: the other cookies
      Frappe sets (user_id, system_user, full_name, user_image) are re-set by
      edu.yoisho.in itself on every request (set_user_info(resume=True)), so
      widening them would only hand readable identity cookies to every
      sub-domain for no benefit.
    * Every time the wide `sid` is written, the legacy HOST-ONLY `sid` is
      expired in the same response. Browsers that logged in before this app was
      installed hold both; Werkzeug (Frappe) reads the first and Django the
      last, so leaving both would make each app see a different session.
    * `sid=Guest` is never written to the shared domain. Frappe sets it for
      every anonymous request; written wide it would overwrite a real session
      the person holds from another sub-domain. A missing cookie already reads
      as Guest (frappe/sessions.py), so only the host-only copy is expired.
    * Deletions (logout) expire both copies.

The core is `emit_cookies`, a pure function over a Werkzeug response, so it is
unit-tested without a bench (tests/test_cookies.py).
"""

import datetime
from urllib.parse import quote

WIDE_COOKIES = frozenset({"sid"})
GUEST = "Guest"


def normalise_domain(domain):
    """'.yoisho.in' / 'yoisho.in' / ' .Yoisho.in ' -> 'yoisho.in' ('' if unset)."""
    return (domain or "").strip().lstrip(".").lower()


def host_in_domain(host, domain):
    """True when `host` (possibly with a port) is `domain` or a sub-domain of it."""
    domain = normalise_domain(domain)
    if not domain:
        return False
    host = (host or "").split(":", 1)[0].strip().lower()
    return host == domain or host.endswith("." + domain)


def _expired():
    return datetime.datetime.now() - datetime.timedelta(days=1)


def emit_cookies(response, cookies, to_delete, shared_domain=None, host=None):
    """Write CookieManager's cookies to `response`.

    `cookies` / `to_delete` are CookieManager.cookies / .to_delete. With no
    usable `shared_domain` (or a host outside it) this is exactly Frappe's own
    flush_cookies; otherwise it applies the rules in the module docstring.
    """
    wide = normalise_domain(shared_domain) if host_in_domain(host, shared_domain) else ""

    for key, opts in cookies.items():
        value = opts.get("value") or ""
        common = dict(
            expires=opts.get("expires"),
            secure=opts.get("secure"),
            httponly=opts.get("httponly"),
            samesite=opts.get("samesite"),
            max_age=opts.get("max_age"),
        )

        if not wide or key not in WIDE_COOKIES:
            response.set_cookie(key, quote(value.encode("utf-8")), **common)
            continue

        # Retire the legacy host-only copy whatever happens next.
        response.set_cookie(key, "", expires=_expired())
        if value == GUEST:
            continue
        response.set_cookie(key, quote(value.encode("utf-8")), domain=wide, **common)

    for key in set(to_delete):
        response.set_cookie(key, "", expires=_expired())
        if wide and key in WIDE_COOKIES:
            response.set_cookie(key, "", expires=_expired(), domain=wide)


# ---------------------------------------------------------------------------
# Frappe wiring
# ---------------------------------------------------------------------------

def _patched_flush_cookies(self, response):
    import frappe

    request = getattr(frappe.local, "request", None)
    emit_cookies(
        response,
        self.cookies,
        self.to_delete,
        shared_domain=frappe.conf.get("shared_cookie_domain"),
        host=getattr(request, "host", None),
    )


def apply_patch():
    """Idempotent. Called at import and from before_request (see hooks.py):
    hooks are cached in Redis, so a fresh worker may never import hooks.py —
    the same reason yoisho_bunny re-applies its patch per request."""
    try:
        from frappe.auth import CookieManager
    except Exception:
        return
    if getattr(CookieManager.flush_cookies, "_yoisho_sso", False):
        return
    _patched_flush_cookies._yoisho_sso = True
    CookieManager.flush_cookies = _patched_flush_cookies


def ensure_patched():
    """before_request hook. Must never break the request."""
    try:
        apply_patch()
    except Exception:
        pass


apply_patch()
