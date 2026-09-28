"""Pure tests for the cookie rules — no bench needed (werkzeug only).

    pip install werkzeug pytest && python -m pytest tests
"""

from werkzeug.wrappers import Response

from yoisho_sso.cookies import emit_cookies, host_in_domain

SESSION = {"value": "abc123", "httponly": True, "secure": True, "samesite": "Lax", "max_age": 864000}


def set_cookies(response):
    return response.headers.getlist("Set-Cookie")


def only(headers, needle):
    return [h for h in headers if needle in h]


def test_host_matching():
    assert host_in_domain("edu.yoisho.in", ".yoisho.in")
    assert host_in_domain("yoisho.in", "yoisho.in")
    assert host_in_domain("EDU.Yoisho.in:443", ".yoisho.in")
    assert not host_in_domain("yoisho.in.evil.com", ".yoisho.in")
    assert not host_in_domain("notyoisho.in", ".yoisho.in")
    assert not host_in_domain("lms_site.com", ".yoisho.in")
    assert not host_in_domain("edu.yoisho.in", "")
    assert not host_in_domain("edu.yoisho.in", None)


def test_unconfigured_is_exactly_frappe():
    r = Response()
    emit_cookies(r, {"sid": SESSION, "user_id": {"value": "a@b.c"}}, [], shared_domain=None, host="edu.yoisho.in")
    headers = set_cookies(r)
    assert len(headers) == 2
    assert not any("Domain=" in h for h in headers)
    assert only(headers, "sid=abc123")


def test_host_outside_domain_is_untouched():
    r = Response()
    emit_cookies(r, {"sid": SESSION}, [], shared_domain=".yoisho.in", host="yoisho-lms.theradixlab.com")
    headers = set_cookies(r)
    assert headers == [h for h in headers if "Domain=" not in h]
    assert len(headers) == 1


def test_session_is_widened_and_host_only_copy_retired():
    r = Response()
    emit_cookies(r, {"sid": SESSION}, [], shared_domain=".yoisho.in", host="edu.yoisho.in")
    headers = only(set_cookies(r), "sid=")
    assert len(headers) == 2
    retire, wide = headers
    assert "Domain=" not in retire and "Expires=" in retire and retire.startswith("sid=;")
    assert "Domain=yoisho.in" in wide and "sid=abc123" in wide
    assert "HttpOnly" in wide and "Secure" in wide and "SameSite=Lax" in wide


def test_other_cookies_stay_host_only():
    r = Response()
    emit_cookies(r, {"user_id": {"value": "a@b.c"}, "system_user": {"value": "no"}}, [],
                 shared_domain=".yoisho.in", host="edu.yoisho.in")
    assert not any("Domain=" in h for h in set_cookies(r))


def test_guest_never_written_to_shared_domain():
    r = Response()
    emit_cookies(r, {"sid": {**SESSION, "value": "Guest"}}, [], shared_domain=".yoisho.in", host="edu.yoisho.in")
    headers = only(set_cookies(r), "sid=")
    assert len(headers) == 1
    assert "Domain=" not in headers[0] and headers[0].startswith("sid=;")
    assert not any("Guest" in h for h in set_cookies(r))


def test_logout_expires_both_copies():
    # Frappe's logout: clear_cookies() queues sid for deletion, then
    # login_as_guest() sets sid=Guest.
    r = Response()
    emit_cookies(r, {"sid": {**SESSION, "value": "Guest"}}, ["sid", "user_id"],
                 shared_domain=".yoisho.in", host="edu.yoisho.in")
    headers = set_cookies(r)
    sid = only(headers, "sid=")
    assert any("Domain=yoisho.in" in h and h.startswith("sid=;") for h in sid)
    assert any("Domain=" not in h and h.startswith("sid=;") for h in sid)
    assert not any(h.startswith("sid=Guest") for h in sid)
    assert all("Domain=" not in h for h in only(headers, "user_id="))
