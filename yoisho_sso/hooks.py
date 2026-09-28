app_name = "yoisho_sso"
app_title = "Yoisho SSO"
app_publisher = "Yoisho"
app_description = "Share the Frappe session across *.yoisho.in (one login at accounts.yoisho.in)"
app_email = "dev@yoisho.in"
app_license = "MIT"

# ---------------------------------------------------------------------------
# Everything is driven by site_config, so installing this app changes nothing
# until the keys are set:
#   shared_cookie_domain  ".yoisho.in"                      -> sid shared across sub-domains
#   sso_login_url         "https://accounts.yoisho.in/login" -> /login page redirects there
# ---------------------------------------------------------------------------

before_request = [
    # Re-apply the flush_cookies patch per request: hooks are cached in Redis,
    # so a fresh worker may never import this module (same reason as
    # yoisho_bunny). Idempotent and cheap.
    "yoisho_sso.cookies.ensure_patched",
    "yoisho_sso.login_redirect.redirect_login_page",
]

try:
    from yoisho_sso.cookies import apply_patch as _p; _p()
except Exception:
    pass
