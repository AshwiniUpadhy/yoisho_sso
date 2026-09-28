"""
Who is signed in, for apps that only hold the shared session cookie.

The yoisho.in SPA used to establish identity by reading the User doc with the
Administrator API key baked into its bundle, keyed by whatever email the login
form had typed. With the session shared across *.yoisho.in the SPA holds no
readable sid at all, and it should not need the admin key to learn its own
name: this answers from the session itself. Called with credentials from any
allowed origin (site_config `allow_cors`).
"""

import frappe

# Custom fields on User in this estate; read only when they exist, so the
# method works on a site without them (e.g. a fresh bench).
_OPTIONAL_USER_FIELDS = ("yoisho_role", "location")
_USER_FIELDS = ("name", "email", "full_name", "first_name", "last_name", "mobile_no", "user_image")


@frappe.whitelist(allow_guest=True, methods=["GET"])
def whoami():
    user = frappe.session.user
    if not user or user == "Guest":
        return {"guest": True}

    meta = frappe.get_meta("User")
    fields = list(_USER_FIELDS) + [f for f in _OPTIONAL_USER_FIELDS if meta.has_field(f)]
    info = frappe.db.get_value("User", user, fields, as_dict=True) or {}
    roles = [r for r in frappe.get_roles(user) if r not in ("All", "Guest")]

    return {
        "guest": False,
        "email": info.get("email") or user,
        "full_name": info.get("full_name") or "",
        "first_name": info.get("first_name") or "",
        "last_name": info.get("last_name") or "",
        "mobile_no": info.get("mobile_no") or "",
        "user_image": info.get("user_image") or "",
        "location": info.get("location") or "",
        "yoisho_role": info.get("yoisho_role") or "",
        "roles": roles,
    }
