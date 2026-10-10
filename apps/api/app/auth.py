"""Phase 2 accounts, sessions, roles, and scoped credentials.

Secrets are never stored. Passwords use PBKDF2; session and ingest
tokens are SHA-256 hashed with only a display prefix retained.
"""
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select

from .db import Account, Credential, Membership, Organization, Project, Session, utc_now

ROLES = ("owner", "admin", "member", "viewer")
_ROLE_RANK = {"viewer": 0, "member": 1, "admin": 2, "owner": 3}

SESSION_PREFIX = "tvs_"
INGEST_PREFIX = "tvk_"
SESSION_TTL = timedelta(days=30)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 210_000)
    return f"pbkdf2$210000${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def normalize_email(email: str) -> str:
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise ValueError("invalid email")
    return email


def new_session_token() -> str:
    return SESSION_PREFIX + secrets.token_urlsafe(32)


API_KEY_PREFIX = "tervik_"


def new_api_key() -> tuple[str, str, str]:
    """Return (secret, prefix, hash) for a read API key: `tervik_<64 hex>`."""
    secret = API_KEY_PREFIX + secrets.token_hex(32)
    return secret, secret[:14], sha256_hex(secret)


def new_ingest_key() -> tuple[str, str, str]:
    """Return (secret, prefix, hash). The secret is returned once."""
    secret = INGEST_PREFIX + secrets.token_urlsafe(32)
    return secret, secret[:12], sha256_hex(secret)


def create_organization(session, name: str) -> Organization:
    org = Organization(id=str(uuid4()), name=name.strip())
    session.add(org)
    session.flush()
    return org


def add_membership(session, org_id: str, account_id: str, role: str) -> Membership:
    if role not in ROLES:
        raise ValueError("invalid role")
    membership = Membership(org_id=org_id, account_id=account_id, role=role)
    session.add(membership)
    session.flush()
    return membership


def has_role(role: str | None, minimum: str) -> bool:
    if role is None:
        return False
    return _ROLE_RANK.get(role, -1) >= _ROLE_RANK[minimum]


def get_membership(session, org_id: str, account_id: str) -> Membership | None:
    return session.get(Membership, (org_id, account_id))


def create_session(session, account_id: str, org_id: str | None = None) -> tuple[Session, str]:
    token = new_session_token()
    record = Session(
        id=str(uuid4()), account_id=account_id, org_id=org_id,
        token_hash=sha256_hex(token), expires_at=datetime.now(timezone.utc) + SESSION_TTL,
    )
    session.add(record)
    session.flush()
    return record, token


def resolve_session(db_session, token: str) -> tuple[Session, Account] | None:
    if not token.startswith(SESSION_PREFIX):
        return None
    record = db_session.scalars(select(Session).where(
        Session.token_hash == sha256_hex(token))).first()
    if record is None or record.revoked_at is not None:
        return None
    expires = record.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        return None
    account = db_session.get(Account, record.account_id)
    if account is None:
        return None
    return record, account


def is_ingest_token(token: str) -> bool:
    return token.startswith(INGEST_PREFIX)


def project_role(db_session, project: Project, account_id: str) -> str | None:
    """Role of an account on a project. Legacy projects are isolated: no session access."""
    if project.org_id is None:
        return None
    membership = get_membership(db_session, project.org_id, account_id)
    return membership.role if membership else None


def require_project_role(db_session, project: Project, account_id: str, minimum: str) -> str:
    role = project_role(db_session, project, account_id)
    if not has_role(role, minimum):
        raise PermissionError("forbidden")
    return role


def credential_for_token(db_session, token: str) -> Credential | None:
    record = db_session.scalars(select(Credential).where(
        Credential.key_hash == sha256_hex(token))).first()
    if record is None or record.revoked_at is not None:
        return None
    return record
