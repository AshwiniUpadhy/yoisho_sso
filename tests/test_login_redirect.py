from urllib.parse import parse_qs, urlparse

from yoisho_sso.login_redirect import build_redirect

SSO = "https://accounts.yoisho.in/login"


def back_of(url):
    return parse_qs(urlparse(url).query)["redirect_to"][0]


def test_returns_to_the_desk_by_default():
    url = build_redirect(SSO, "edu.yoisho.in", "https", None)
    assert url.startswith(SSO + "?")
    assert back_of(url) == "https://edu.yoisho.in/app"


def test_keeps_frappes_redirect_to_path():
    assert back_of(build_redirect(SSO, "edu.yoisho.in", "https", "/app/user")) == "https://edu.yoisho.in/app/user"


def test_refuses_absolute_and_protocol_relative_targets():
    assert back_of(build_redirect(SSO, "edu.yoisho.in", "https", "https://evil.com")) == "https://edu.yoisho.in/app"
    assert back_of(build_redirect(SSO, "edu.yoisho.in", "https", "//evil.com/x")) == "https://edu.yoisho.in/app"


def test_appends_to_an_existing_query():
    url = build_redirect(SSO + "?app=edu", "edu.yoisho.in", "https", "/app")
    assert "?app=edu&redirect_to=" in url
