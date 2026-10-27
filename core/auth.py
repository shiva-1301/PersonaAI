"""Sign-in: students by hall-ticket number + password, one admin account from .env.

Students are added by the admin from a class list. A student has no password until
their first sign-in, when they choose one. Passwords are stored as salted PBKDF2
hashes, never in plain text.
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass

from core import config, db

ADMIN_USERNAME = "admin"
MIN_PASSWORD_LENGTH = 6
_ITERATIONS = 200_000


class AuthError(ValueError):
    """Sign-in refused; the message is safe to show to the user."""


class PasswordNotSet(AuthError):
    """The student exists but hasn't chosen a password yet (first sign-in)."""


@dataclass
class Account:
    user_id: int
    username: str
    full_name: str | None
    role: str  # "student" | "admin"
    cohort_id: int | None


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt, digest = stored.split("$")
        check = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(check.hex(), digest)


def _account(user, role: str = "student") -> Account:
    return Account(user["id"], user["username"], user["full_name"], role, user["cohort_id"])


def sign_in(username: str, password: str) -> Account:
    """Check the credentials. Raises PasswordNotSet on a student's first sign-in."""
    username = username.strip()
    if not username:
        raise AuthError("Enter your hall ticket number.")
    if username.lower() == ADMIN_USERNAME:
        if not config.ADMIN_PASSWORD:
            raise AuthError("Admin sign-in is off. Set ADMIN_PASSWORD in the .env file.")
        if not hmac.compare_digest(password.encode(), config.ADMIN_PASSWORD.encode()):
            raise AuthError("Wrong hall ticket number or password.")
        return _account(db.get_or_create_user(ADMIN_USERNAME), "admin")

    user = db.find_user(username)
    if user is None:
        raise AuthError("This hall ticket number isn't registered. Ask your department admin to add you.")
    if not user["password_hash"]:
        raise PasswordNotSet("First sign-in: choose a password for your account.")
    if not verify_password(password, user["password_hash"]):
        raise AuthError("Wrong hall ticket number or password.")
    return _account(user)


def set_first_password(username: str, password: str, confirm: str) -> Account:
    """Set the password of a student who doesn't have one yet, and sign them in."""
    user = db.find_user(username)
    if user is None or username.strip().lower() == ADMIN_USERNAME:
        raise AuthError("This hall ticket number isn't registered.")
    if user["password_hash"]:
        raise AuthError("This account already has a password. Sign in with it.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"Use at least {MIN_PASSWORD_LENGTH} characters.")
    if password != confirm:
        raise AuthError("The two passwords don't match.")
    db.set_password_hash(user["id"], hash_password(password))
    return _account(user)
