"""Demo credentials, sessions, and audit history."""
from __future__ import annotations
from dataclasses import dataclass, field, replace
from datetime import datetime
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
import hashlib
import hmac
import json
import secrets
from .errors import AuthorizationError
from .timezones import UTC

# -----------------------------
# Security/Audit
# -----------------------------
@dataclass
class User:
    """System actor with role assignments and hashed credentials."""

    user_id: str
    roles: List[str]  # 'admin'|'doctor'|'nurse'|'billing'|'clerk'
    person_id: Optional[str] = None
    password: str = field(default="", repr=False, metadata={"deprecated": True})
    password_hash: Optional[str] = field(default=None, repr=False)
    password_salt: Optional[str] = field(default=None, repr=False)
    session_token: Optional[str] = field(default=None, repr=False)
    _active_tokens: List[str] = field(default_factory=list, repr=False)

    def remember_session(self, token: str) -> None:
        """Track an issued session token for subsequent validation."""
        if token not in self._active_tokens:
            self._active_tokens.append(token)
        self.session_token = token

    def revoke_token(self, token: str) -> None:
        """Revoke a specific session token."""
        if token in self._active_tokens:
            self._active_tokens.remove(token)
        if self.session_token == token:
            self.session_token = None

    def clear_sessions(self) -> None:
        """Revoke all outstanding session tokens."""
        self._active_tokens.clear()
        self.session_token = None

    @property
    def active_tokens(self) -> Tuple[str, ...]:
        """Expose active tokens as an immutable tuple."""
        return tuple(self._active_tokens)


@dataclass(frozen=True)
class AuditEvent:
    """Immutable record capturing security-sensitive state transitions."""

    who: str
    what: str
    when: datetime
    before: Optional[Dict[str, Any]] = None
    after: Optional[Dict[str, Any]] = None
    prev_hash: Optional[str] = None
    event_hash: Optional[str] = None

    @classmethod
    def for_action(
        cls,
        who: str,
        what: str,
        when: Optional[datetime] = None,
        *,
        before: Optional[Dict[str, Any]] = None,
        after: Optional[Dict[str, Any]] = None,
    ) -> "AuditEvent":
        """Factory that fills defaults while keeping the dataclass frozen."""
        timestamp = when or datetime.now(UTC)
        return cls(who=who, what=what, when=timestamp, before=before, after=after)


class AuditLog:
    """Hash-chained append-only audit log."""

    def __init__(self) -> None:
        self._events: List[AuditEvent] = []

    @property
    def events(self) -> Tuple[AuditEvent, ...]:
        """Return a defensive copy of recorded events."""
        return tuple(self._events)

    def reset(self) -> None:
        """Purge all recorded events."""
        self._events.clear()

    def log(self, event: AuditEvent) -> AuditEvent:
        """Append an event after computing its chained hash."""
        previous_hash = self._events[-1].event_hash if self._events else None
        event_hash = self._compute_hash(event, previous_hash)
        stored_event = replace(event, prev_hash=previous_hash, event_hash=event_hash)
        self._events.append(stored_event)
        return stored_event

    def verify_chain(self) -> bool:
        """Return True when the audit chain is intact."""
        previous_hash: Optional[str] = None
        for event in self._events:
            if event.prev_hash != previous_hash:
                return False
            recalculated = self._compute_hash(replace(event, prev_hash=None, event_hash=None), previous_hash)
            if event.event_hash != recalculated:
                return False
            previous_hash = event.event_hash
        return True

    def _compute_hash(self, event: AuditEvent, previous_hash: Optional[str]) -> str:
        payload = {
            "who": event.who,
            "what": event.what,
            "when": event.when.isoformat(),
            "before": event.before,
            "after": event.after,
            "prev_hash": previous_hash,
        }
        raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


class AuthService:
    """Manages secure password hashing and session lifecycle."""

    def __init__(self, users: Dict[str, User], iterations: int = 390_000) -> None:
        self._users = users
        self._iterations = iterations

    @property
    def users(self) -> Mapping[str, User]:
        """Expose the registered users as an immutable mapping."""
        return MappingProxyType(self._users)

    def register_user(self, user: User, password: str) -> None:
        """Hash and persist credentials for a user."""
        salt = secrets.token_hex(16)
        password_hash = self._derive(password, salt)
        user.password = ""
        user.password_salt = salt
        user.password_hash = password_hash
        user.clear_sessions()
        self._users[user.user_id] = user

    def authenticate(self, username: str, password: str) -> Optional[Tuple[User, str]]:
        """Return (user, token) when credentials verify."""
        user = self._users.get(username)
        if not user or not user.password_hash or not user.password_salt:
            return None
        candidate = self._derive(password, user.password_salt)
        if not hmac.compare_digest(candidate, user.password_hash):
            return None
        token = self._issue_token(user)
        return user, token

    def change_password(self, user: User, current: str, new_password: str) -> bool:
        """Change a password after validating the current secret."""
        if not self.verify_password(user, current):
            return False
        self._set_password(user, new_password)
        return True

    def reset_password(self, user: User, new_password: str) -> None:
        """Reset a password without validating the old one (admin use)."""
        self._set_password(user, new_password)

    def verify_password(self, user: User, password: str) -> bool:
        """Return True when the supplied password matches the stored hash."""
        if not user.password_hash or not user.password_salt:
            return False
        candidate = self._derive(password, user.password_salt)
        return hmac.compare_digest(candidate, user.password_hash)

    def validate_session(self, username: str, token: str) -> bool:
        """Ensure a token is currently active for the given user."""
        user = self._users.get(username)
        if not user:
            return False
        return token in user.active_tokens

    def _set_password(self, user: User, password: str) -> None:
        salt = secrets.token_hex(16)
        password_hash = self._derive(password, salt)
        user.password = ""
        user.password_salt = salt
        user.password_hash = password_hash
        user.clear_sessions()

    def _derive(self, password: str, salt_hex: str) -> str:
        salt_bytes = bytes.fromhex(salt_hex)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_bytes, self._iterations)
        return dk.hex()

    def _issue_token(self, user: User) -> str:
        token = secrets.token_hex(16)
        user.remember_session(token)
        return token


def require_role(
    user: User,
    allowed: Sequence[str],
    *,
    auth: Optional[AuthService] = None,
    token: Optional[str] = None,
) -> None:
    """Verify role membership and session authenticity when auth is supplied."""
    if auth is not None:
        if auth.users.get(user.user_id) is not user or not token or not auth.validate_session(user.user_id, token):
            raise AuthorizationError("Invalid or expired session token.")
    elif token is not None:
        raise AuthorizationError("Session token provided without auth service.")
    if not any(role in allowed for role in user.roles):
        raise AuthorizationError("insufficient role")
