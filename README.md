# yoisho_sso

A small Frappe app, installed on edu.yoisho.in. It shares the Frappe session across `*.yoisho.in`, so
that signing in once at **accounts.yoisho.in** signs a person into yoisho.in, study.yoisho.in,
kana.yoisho.in and the edu.yoisho.in desk. Signing out anywhere signs them out of all of them.

It is Phase 1 of the plan in `~/.claude/plans/peppy-whistling-puffin.md`.

Installing the app changes nothing on its own. Every behaviour below is switched on by a site_config key.

| site_config key | Example | Effect |
|---|---|---|
| `shared_cookie_domain` | `".yoisho.in"` | `sid` is issued with `Domain=yoisho.in`; the old edu-only `sid` is expired (`yoisho_sso/cookies.py`) |
| `sso_login_url` | `"https://accounts.yoisho.in/login"` | Frappe's `/login` **page** redirects there. `/login?local=1` still shows Frappe's own form as a break-glass way in (`yoisho_sso/login_redirect.py`) |
| `allow_cors` | list of origins (below) | Lets those origins call Frappe **with credentials** (Frappe core feature) |

It also adds `GET /api/method/yoisho_sso.api.whoami`, which returns who the session belongs to: email,
names, `yoisho_role` and roles, or `{"guest": true}`.

## Install (production)

Run these as `yoisho_lms_usr` in the bench directory, `/home/yoisho_lms_usr/yoisho_lms/lms-bench`:

```bash
bench get-app <git url or local path to this repo>
bench --site lms_site.com install-app yoisho_sso
bench --site lms_site.com migrate
```

Then add the config, one key at a time. Each command uses `--parse` so the value is stored as JSON, not
as a string:

```bash
bench --site lms_site.com set-config -p shared_cookie_domain '".yoisho.in"'
bench --site lms_site.com set-config -p allow_cors '["https://yoisho.in","https://www.yoisho.in","https://accounts.yoisho.in","https://study.yoisho.in","https://kana.yoisho.in"]'
# only once accounts.yoisho.in is live (Phase 3):
# bench --site lms_site.com set-config -p sso_login_url '"https://accounts.yoisho.in/login"'
```

Restart gunicorn. It runs with `--preload`, so it will not pick up the change until it restarts. Run
this as root:

```bash
supervisorctl restart lms-bench-web:
```

Do **not** run `bench setup production` on this box. It installs nginx, which collides with Apache.

## Verify

1. Sign in at `https://edu.yoisho.in/login` in a browser. Then open DevTools → Application → Cookies.
   - `sid` should show **Domain `.yoisho.in`**.
   - There should be no second `sid` scoped to `edu.yoisho.in`.
2. Open `https://edu.yoisho.in/api/method/yoisho_sso.api.whoami`. It should return your email and roles.
3. Sign out.
   - Both `sid` copies should be gone.
   - `whoami` should return `{"guest": true}`.
4. The desk (`/app`) should still work as before.

## Roll back

Remove `shared_cookie_domain` with `bench --site lms_site.com set-config shared_cookie_domain ''`, then
restart as above. Frappe goes back to host-only cookies. The app can stay installed.

## Tests

The cookie rules and the redirect builder are pure functions, so they run without a bench:

```bash
pip install werkzeug==3.1.6 pytest
python -m pytest tests
```
