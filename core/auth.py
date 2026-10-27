"""Sign-in: students by hall-ticket number + password, one admin account from .env.

Students are added by the admin from a class list. To set their first password, a
student needs a one-time sign-up code the admin generates for them (so knowing a hall
ticket number isn't enough to take over the account). Passwords and codes are stored
as salted PBKDF2 hashes, never in plain text.

Repeated failures lock a username: MAX_FAILED_LOGINS wrong passwords or codes in a row
block it for LOCKOUT_SECONDS.
"""

import hashlib
import hmac
import math
import re
import secrets
import time
from dataclasses import dataclass

from core import config, db

ADMIN_USERNAME = "admin"
MIN_PASSWORD_LENGTH = 6
MAX_FAILED_LOGINS = 5
LOCKOUT_SECONDS = 300
_ITERATIONS = 200_000
# No 0/O, 1/I/L: codes are read off a printout or a screen.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_now = time.time  # replaced in tests


class AuthError(ValueError):
    """Sign-in refused; the message is safe to show to the user."""


class PasswordNotSet(AuthError):
    """The student exists but hasn't chosen a password yet (first sign-in)."""


class LockedOut(AuthError):
    """Too many failed attempts for this username."""


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


def _normalise_code(code: str) -> str:
    return re.sub(r"[\s-]", "", code).upper()


def _account(user, role: str = "student") -> Account:
    return Account(user["id"], user["username"], user["full_name"], role, user["cohort_id"])


# --- Lockout ---

def _check_not_locked(username: str) -> None:
    row = db.login_failures(username)
    if row and row["locked_until"] and row["locked_until"] > _now():
        minutes = math.ceil((row["locked_until"] - _now()) / 60)
        raise LockedOut(f"Too many failed attempts. Try again in {minutes} minute{'s' if minutes != 1 else ''}.")


def _fail(username: str, message: str) -> None:
    db.record_login_failure(username, MAX_FAILED_LOGINS, LOCKOUT_SECONDS, _now())
    raise AuthError(message)


# --- Sign-in ---

def sign_in(username: str, password: str) -> Account:
    """Check the credentials. Raises PasswordNotSet on a student's first sign-in."""
    username = username.strip()
    if not username:
        raise AuthError("Enter your hall ticket number.")
    _check_not_locked(username)
    if username.lower() == ADMIN_USERNAME:
        if not config.ADMIN_PASSWORD:
            raise AuthError("Admin sign-in is off. Set ADMIN_PASSWORD in the .env file.")
        if not hmac.compare_digest(password.encode(), config.ADMIN_PASSWORD.encode()):
            _fail(username, "Wrong hall ticket number or password.")
        db.clear_login_failures(username)
        return _account(db.get_or_create_user(ADMIN_USERNAME), "admin")

    user = db.find_user(username)
    if user is None:
        _fail(username, "This hall ticket number isn't registered. Ask your department admin to add you.")
    if not user["password_hash"]:
        raise PasswordNotSet("First sign-in: enter the sign-up code from your department and choose a password.")
    if not verify_password(password, user["password_hash"]):
        _fail(username, "Wrong hall ticket number or password.")
    db.clear_login_failures(username)
    return _account(user)


def set_first_password(username: str, code: str, password: str, confirm: str) -> Account:
    """Set a student's first password, given the one-time code the admin issued them."""
    username = username.strip()
    _check_not_locked(username)
    user = db.find_user(username)
    if user is None or username.lower() == ADMIN_USERNAME:
        raise AuthError("This hall ticket number isn't registered.")
    if user["password_hash"]:
        raise AuthError("This account already has a password. Sign in with it.")
    if not user["setup_code_hash"]:
        raise AuthError("You don't have a sign-up code yet. Ask your department admin for one.")
    if not verify_password(_normalise_code(code), user["setup_code_hash"]):
        _fail(username, "That sign-up code isn't right. Check it with your department admin.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"Use at least {MIN_PASSWORD_LENGTH} characters.")
    if password != confirm:
        raise AuthError("The two passwords don't match.")
    db.set_password_hash(user["id"], hash_password(password))  # also uses up the code
    db.clear_login_failures(username)
    return _account(user)


# --- Admin: sign-up codes ---

def issue_setup_code(user_id: int) -> str:
    """A new one-time code for a student (replacing any earlier one), e.g. "K7QF-3MXP".
    Only its hash is stored, so the admin must hand it out now."""
    code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
    db.set_setup_code_hash(user_id, hash_password(code))
    return f"{code[:4]}-{code[4:]}"


def issue_codes_for_cohort(cohort_id: int) -> list[tuple[str, str, str]]:
    """New codes for every student in the cohort who hasn't set a password:
    (hall ticket, name, code)."""
    return [
        (s["username"], s["full_name"] or "", issue_setup_code(s["id"]))
        for s in db.list_students(cohort_id) if not s["has_password"]
    ]


def reset_password(user_id: int) -> str:
    """Clear a student's password; they set a new one with the returned code."""
    db.set_password_hash(user_id, None)
    db.clear_login_failures(db.get_user(user_id)["username"])
    return issue_setup_code(user_id)
