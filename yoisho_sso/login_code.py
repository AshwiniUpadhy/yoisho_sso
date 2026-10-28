"""
Sign in with a code sent by email, instead of a password (sso.yoisho.in).

    send_login_code(email)            -> always {"sent": True}
    login_with_code(email, code)      -> {"ok": True, ...} and a session (sid cookie)

Modelled on Frappe's own "Login with Email Link" (frappe/www/login.py: a
one-time value in Redis, rate limited, then login_manager.login_as), but with
a 6-digit code typed on sso.yoisho.in, so the person lands back on the site
they came from rather than on edu.

Off until site_config says otherwise:
    sso_login_code              1 -> both methods work
    sso_login_code_allow_staff  1 -> staff accounts may use it too (default:
                                     students and affiliates only; a code by
                                     email is only as safe as the mailbox)

Safeguards (OWASP-style, and Frappe's own link for the numbers):
  - 6 digits, valid 10 minutes, single use; only an HMAC of it is stored
  - 5 wrong tries and that code is dead; a new one must be asked for
  - at most one code a minute and 5 an hour per address
  - the send answer never says whether an account exists
Per-visitor limits live on sso.yoisho.in: every request reaches edu from that
server, so an IP limit here would be one limit shared by everyone.
"""

import hashlib
import hmac
import secrets
import time

import frappe

CODE_DIGITS = 6
CODE_TTL_SEC = 10 * 60
MAX_ATTEMPTS = 5
RESEND_AFTER_SEC = 60
MAX_SENDS_PER_HOUR = 5

# yoisho_role values that mean staff (Support is stored as "Admin").
STAFF_YOISHO_ROLES = {"admin", "superadmin", "teacher", "sales"}
# Frappe roles that mean staff whatever yoisho_role says.
STAFF_FRAPPE_ROLES = {"Administrator", "System Manager"}

SENT = {"sent": True}
WRONG = "That code is not right, or it has expired. Ask for a new one."


# ── Pure helpers (tested without a site) ───────────────────────────────────

def normalise_email(email):
	return str(email or "").strip().lower()


def new_code():
	return "".join(secrets.choice("0123456789") for _ in range(CODE_DIGITS))


def clean_code(code):
	"""The digits of what was typed ("123 456" from a paste counts)."""
	return "".join(ch for ch in str(code or "") if ch.isdigit())


def code_hash(secret, email, code):
	return hmac.new(str(secret).encode(), f"{email}:{code}".encode(), hashlib.sha256).hexdigest()


def is_staff(yoisho_role, roles):
	return str(yoisho_role or "").strip().lower() in STAFF_YOISHO_ROLES or bool(STAFF_FRAPPE_ROLES & set(roles or ()))


def may_use_code(user, allow_staff):
	"""user: {name, enabled, yoisho_role, roles} or None."""
	if not user or not user.get("enabled") or user.get("name") in ("Administrator", "Guest"):
		return False
	return allow_staff or not is_staff(user.get("yoisho_role"), user.get("roles"))


def send_allowed(sends, now):
	"""sends: timestamps of earlier codes for this address. -> (ok, recent sends to keep)."""
	recent = [t for t in (sends or []) if now - t < 3600]
	if recent and now - max(recent) < RESEND_AFTER_SEC:
		return False, recent
	if len(recent) >= MAX_SENDS_PER_HOUR:
		return False, recent
	return True, recent


def check_code(record, expected_hash, now):
	"""-> 'ok', 'wrong' (attempt counted) or 'dead' (expired, used up, none)."""
	if not record or now > record.get("expires", 0) or record.get("attempts", 0) >= MAX_ATTEMPTS:
		return "dead"
	return "ok" if hmac.compare_digest(record.get("hash", ""), expected_hash) else "wrong"


# ── Site-side ──────────────────────────────────────────────────────────────

def _enabled():
	return bool(frappe.conf.get("sso_login_code"))


def _secret():
	from frappe.utils.password import get_encryption_key

	return get_encryption_key()


def _code_key(email):
	return f"yoisho_sso:login_code:{email}"


def _sends_key(email):
	return f"yoisho_sso:login_code_sends:{email}"


def _user(email):
	meta = frappe.get_meta("User")
	fields = ["name", "enabled", "first_name"] + (["yoisho_role"] if meta.has_field("yoisho_role") else [])
	row = frappe.db.get_value("User", {"email": email}, fields, as_dict=True)
	if not row:
		return None
	row["roles"] = frappe.get_roles(row["name"])
	return row


def _login_as(name):
	"""Start a session for `name`: Frappe sets the sid cookie, which
	yoisho_sso.cookies shares across *.yoisho.in. Does NOT check `enabled`."""
	frappe.local.login_manager.login_as(name)
	return frappe.db.get_value("User", name, "full_name") or ""


def _send_email(email, code, first_name):
	greeting = f"Hi {frappe.utils.escape_html(first_name)}," if first_name else "Hi,"
	frappe.sendmail(
		recipients=[email],
		subject=f"{code} is your Yoisho sign-in code",
		message=(
			f"<p>{greeting}</p>"
			f"<p>Your code to sign in to Yoisho is:</p>"
			f"<p style=\"font-size:28px;font-weight:700;letter-spacing:6px\">{code}</p>"
			f"<p>It works once, for the next {CODE_TTL_SEC // 60} minutes.</p>"
			"<p>If you did not ask for it, ignore this email: nobody can sign in without the code.</p>"
		),
		now=True,
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def send_login_code(email=None):
	if not _enabled():
		frappe.throw("Sign-in codes are not available.", frappe.PermissionError)
	email = normalise_email(email)
	if not email or "@" not in email:
		frappe.throw("Enter a valid email address.", frappe.ValidationError)

	now = time.time()
	ok, recent = send_allowed(frappe.cache.get_value(_sends_key(email)), now)
	if not ok:
		# Same answer as a send: a refusal here would say the address is real.
		return SENT

	user = _user(email)
	if not may_use_code(user, bool(frappe.conf.get("sso_login_code_allow_staff"))):
		return SENT

	code = new_code()
	frappe.cache.set_value(
		_code_key(email),
		{"hash": code_hash(_secret(), email, code), "expires": now + CODE_TTL_SEC, "attempts": 0},
		expires_in_sec=CODE_TTL_SEC,
	)
	frappe.cache.set_value(_sends_key(email), recent + [now], expires_in_sec=3600)
	try:
		_send_email(email, code, user.get("first_name"))
	except Exception:
		# Logged, not shown: the person sees "check your email" either way and
		# can ask again in a minute.
		frappe.log_error(title="yoisho_sso: sign-in code email failed")
	return SENT


@frappe.whitelist(allow_guest=True, methods=["POST"])
def login_with_code(email=None, code=None):
	if not _enabled():
		frappe.throw("Sign-in codes are not available.", frappe.PermissionError)
	email = normalise_email(email)
	code = clean_code(code)
	key = _code_key(email)
	record = frappe.cache.get_value(key)
	now = time.time()

	verdict = check_code(record, code_hash(_secret(), email, code), now) if len(code) == CODE_DIGITS else (
		"wrong" if record else "dead"
	)
	if verdict != "ok":
		if verdict == "wrong":
			record["attempts"] = record.get("attempts", 0) + 1
			frappe.cache.set_value(key, record, expires_in_sec=max(1, int(record["expires"] - now)))
		frappe.throw(WRONG, frappe.AuthenticationError)

	frappe.cache.delete_value(key)
	# Checked again at use: the account may have been disabled, or turned into
	# staff, in the ten minutes since the code was sent.
	user = _user(email)
	if not may_use_code(user, bool(frappe.conf.get("sso_login_code_allow_staff"))):
		frappe.throw(WRONG, frappe.AuthenticationError)

	# login_as does not check `enabled` itself; may_use_code did.
	return {"ok": True, "full_name": _login_as(user["name"])}
