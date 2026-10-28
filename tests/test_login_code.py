import types

import frappe
import pytest

from yoisho_sso import login_code as lc

STUDENT = {"name": "asha@example.com", "enabled": 1, "first_name": "Asha", "yoisho_role": "Student", "roles": ["LMS Student"]}


# ── Pure helpers ───────────────────────────────────────────────────────────

def test_codes_are_six_random_digits():
    codes = {lc.new_code() for _ in range(200)}
    assert all(len(c) == 6 and c.isdigit() for c in codes)
    assert len(codes) > 190


def test_a_pasted_code_keeps_only_its_digits():
    assert lc.clean_code(" 123 456 ") == "123456"
    assert lc.clean_code(None) == ""


def test_the_hash_depends_on_email_code_and_secret():
    h = lc.code_hash("s", "a@x.in", "123456")
    assert h != lc.code_hash("s", "b@x.in", "123456")
    assert h != lc.code_hash("s", "a@x.in", "123457")
    assert h != lc.code_hash("t", "a@x.in", "123456")


def test_staff_are_kept_out_unless_allowed():
    for role in ("Admin", "SuperAdmin", "Teacher", "sales"):
        assert not lc.may_use_code({**STUDENT, "yoisho_role": role}, allow_staff=False)
        assert lc.may_use_code({**STUDENT, "yoisho_role": role}, allow_staff=True)
    assert not lc.may_use_code({**STUDENT, "roles": ["System Manager"]}, allow_staff=False)
    assert lc.may_use_code(STUDENT, allow_staff=False)
    assert lc.may_use_code({**STUDENT, "yoisho_role": "Affiliate"}, allow_staff=False)


def test_disabled_missing_and_system_accounts_never_get_a_code():
    assert not lc.may_use_code(None, True)
    assert not lc.may_use_code({**STUDENT, "enabled": 0}, True)
    assert not lc.may_use_code({**STUDENT, "name": "Administrator"}, True)


def test_one_code_a_minute_and_five_an_hour():
    assert lc.send_allowed([], 10_000) == (True, [])
    assert lc.send_allowed([10_000 - 30], 10_000)[0] is False
    assert lc.send_allowed([10_000 - 61], 10_000)[0] is True
    five = [10_000 - 3000 + i * 100 for i in range(5)]
    assert lc.send_allowed(five, 10_000)[0] is False
    # Older than an hour no longer counts.
    assert lc.send_allowed([10_000 - 4000] * 5, 10_000) == (True, [])


def test_a_code_is_dead_when_expired_used_up_or_missing():
    rec = {"hash": "h", "expires": 100, "attempts": 0}
    assert lc.check_code(rec, "h", 50) == "ok"
    assert lc.check_code(rec, "x", 50) == "wrong"
    assert lc.check_code(rec, "h", 101) == "dead"
    assert lc.check_code({**rec, "attempts": 5}, "h", 50) == "dead"
    assert lc.check_code(None, "h", 50) == "dead"


# ── The two methods, with Redis, mail and login faked ──────────────────────

class FakeCache:
    def __init__(self):
        self.d = {}

    def get_value(self, k):
        return self.d.get(k)

    def set_value(self, k, v, expires_in_sec=None):
        self.d[k] = v

    def delete_value(self, k):
        self.d.pop(k, None)


@pytest.fixture
def site(monkeypatch):
    cache = FakeCache()
    sent, logged_in = [], []
    users = {"asha@example.com": dict(STUDENT)}
    conf = {"sso_login_code": 1}

    def throw(msg, exc=Exception):
        raise exc(msg)

    # @frappe.whitelist reads local.flags; outside a request there is none.
    monkeypatch.setattr(frappe.local, "flags", frappe._dict(), raising=False)
    monkeypatch.setattr(frappe, "cache", cache, raising=False)
    monkeypatch.setattr(frappe, "throw", throw)
    monkeypatch.setattr(lc, "_enabled", lambda: bool(conf.get("sso_login_code")))
    monkeypatch.setattr(frappe, "conf", types.SimpleNamespace(get=conf.get), raising=False)
    monkeypatch.setattr(lc, "_secret", lambda: "test-secret")
    monkeypatch.setattr(lc, "_user", lambda email: users.get(email))
    monkeypatch.setattr(lc, "_send_email", lambda email, code, first: sent.append((email, code)))
    monkeypatch.setattr(lc, "_login_as", lambda name: logged_in.append(name) or "Asha Rao")
    clock = {"t": 1_000_000.0}
    monkeypatch.setattr(lc.time, "time", lambda: clock["t"])
    return types.SimpleNamespace(cache=cache, sent=sent, logged_in=logged_in, users=users, conf=conf, clock=clock)


def test_the_right_code_signs_in_once(site):
    assert lc.send_login_code(" Asha@Example.com ") == lc.SENT
    (email, code), = site.sent
    assert email == "asha@example.com"
    assert code not in str(site.cache.d)  # only the hash is stored

    assert lc.login_with_code("asha@example.com", code)["ok"] is True
    assert site.logged_in == ["asha@example.com"]
    with pytest.raises(frappe.AuthenticationError):
        lc.login_with_code("asha@example.com", code)


def test_unknown_and_staff_addresses_get_the_same_answer_and_no_mail(site):
    site.users["staff@yoisho.com"] = {**STUDENT, "name": "staff@yoisho.com", "yoisho_role": "Admin"}
    assert lc.send_login_code("nobody@example.com") == lc.SENT
    assert lc.send_login_code("staff@yoisho.com") == lc.SENT
    assert site.sent == []


def test_five_wrong_tries_kill_the_code(site):
    lc.send_login_code("asha@example.com")
    (_, code), = site.sent
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        with pytest.raises(frappe.AuthenticationError):
            lc.login_with_code("asha@example.com", wrong)
    with pytest.raises(frappe.AuthenticationError):
        lc.login_with_code("asha@example.com", code)
    assert site.logged_in == []


def test_an_expired_code_does_not_work(site):
    lc.send_login_code("asha@example.com")
    (_, code), = site.sent
    site.clock["t"] += lc.CODE_TTL_SEC + 1
    with pytest.raises(frappe.AuthenticationError):
        lc.login_with_code("asha@example.com", code)


def test_a_resend_within_a_minute_sends_nothing(site):
    lc.send_login_code("asha@example.com")
    lc.send_login_code("asha@example.com")
    assert len(site.sent) == 1
    site.clock["t"] += 61
    lc.send_login_code("asha@example.com")
    assert len(site.sent) == 2


def test_an_account_disabled_after_the_send_cannot_use_its_code(site):
    lc.send_login_code("asha@example.com")
    (_, code), = site.sent
    site.users["asha@example.com"]["enabled"] = 0
    with pytest.raises(frappe.AuthenticationError):
        lc.login_with_code("asha@example.com", code)
    assert site.logged_in == []


def test_off_unless_switched_on(site):
    site.conf["sso_login_code"] = 0
    with pytest.raises(frappe.PermissionError):
        lc.send_login_code("asha@example.com")
    with pytest.raises(frappe.PermissionError):
        lc.login_with_code("asha@example.com", "123456")


# ── The editable email ─────────────────────────────────────────────────────

def test_an_edited_email_is_used_only_while_it_shows_the_code():
    assert lc.usable_email("Your code", "<p>Use 123456</p>", "123456")
    assert not lc.usable_email("Your code", "<p>Welcome back!</p>", "123456")
    assert not lc.usable_email("  ", "<p>123456</p>", "123456")


def test_the_built_in_wording_fills_every_placeholder():
    import jinja2
    env = jinja2.Environment()
    args = {"code": "482913", "first_name": "Asha", "minutes": 10}
    subject = env.from_string(lc.DEFAULT_SUBJECT).render(args)
    body = env.from_string(lc.DEFAULT_BODY).render(args)
    assert subject == "482913 is your Yoisho sign-in code"
    assert "Hi Asha," in body and "482913" in body and "10 minutes" in body
    assert "Hi," in env.from_string(lc.DEFAULT_BODY).render({**args, "first_name": ""})


def _jinja_render(subject, body, args):
    import jinja2
    env = jinja2.Environment()
    return env.from_string(subject).render(args).strip(), env.from_string(body).render(args)


@pytest.mark.parametrize("template, expect_custom", [
    ({"subject": "Code: {{ code }}", "response_": "<p>{{ first_name }}, use {{ code }}</p>"}, True),
    ({"subject": "Hello", "response_": "<p>Welcome back!</p>"}, False),  # {{ code }} deleted
    (None, False),  # no template
])
def test_the_desk_template_or_the_built_in_email(monkeypatch, template, expect_custom):
    logged = []
    monkeypatch.setattr(lc, "_render", _jinja_render)
    monkeypatch.setattr(frappe, "db", types.SimpleNamespace(exists=lambda *a: template is not None), raising=False)
    monkeypatch.setattr(frappe, "get_doc", lambda *a: types.SimpleNamespace(**template))
    monkeypatch.setattr(frappe, "log_error", lambda **k: logged.append(k))
    subject, message = lc._email_for("482913", "<b>Asha</b>")
    assert "482913" in message
    if expect_custom:
        assert subject == "Code: 482913"
        assert "&lt;b&gt;Asha&lt;/b&gt;" in message  # a name is escaped
    else:
        assert subject == "482913 is your Yoisho sign-in code"
    assert bool(logged) == (template is not None and not expect_custom)
