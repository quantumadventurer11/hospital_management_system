# Assignment #4: Hospital Management System v2.0
# Developer: Benjamin Charles Brumm
# Student #: W0305413
# Course: Data Movement and Integration
# Instructor: Dr. Cheolsoon Im
# Date Completed: October 12th, 2025

# -----------------------------
# Imports
# -----------------------------

from __future__ import annotations
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import hashlib
import hmac
import secrets
# Prefer stdlib zoneinfo, fall back to backports for older Python versions
try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except Exception:
    from backports.zoneinfo import ZoneInfo, ZoneInfoNotFoundError  # type: ignore
from typing import Any, Callable, ClassVar, Dict, Generic, Iterable, List, Mapping, Optional, Sequence, Tuple, TypeVar
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox, filedialog
# Secure password input when available
try:
    from getpass import getpass
except Exception:
    getpass = None  # type: ignore
# Protocol may live in typing (modern Python) or typing_extensions (older)
try:
    from typing import Protocol, runtime_checkable  # type: ignore
except Exception:
    from typing_extensions import Protocol, runtime_checkable  # type: ignore
import uuid
from types import MappingProxyType

# -----------------------------
# Error Handling
# -----------------------------
class ValidationError(Exception): ...
class AuthorizationError(Exception): ...
class SchedulingConflictError(Exception): ...
class NotFoundError(Exception): ...
class DuplicateError(Exception): ...
class TimezoneError(Exception): ...

FALLBACK_TIMEZONES = {
    "UTC": timezone.utc,
    "America/Los_Angeles": timezone(timedelta(hours=-8)),
    "America/Vancouver": timezone(timedelta(hours=-8)),
    "America/Denver": timezone(timedelta(hours=-7)),
    "America/Edmonton": timezone(timedelta(hours=-7)),
    "America/Phoenix": timezone(timedelta(hours=-7)),
    "America/Chicago": timezone(timedelta(hours=-6)),
    "America/Winnipeg": timezone(timedelta(hours=-6)),
    "America/New_York": timezone(timedelta(hours=-5)),
    "America/Toronto": timezone(timedelta(hours=-5)),
    "America/Halifax": timezone(timedelta(hours=-4)),
    "America/Puerto_Rico": timezone(timedelta(hours=-4)),
}

TIMEZONE_CHOICES: List[Tuple[str, str]] = [
    ("Pacific - Los Angeles", "America/Los_Angeles"),
    ("Pacific - Vancouver", "America/Vancouver"),
    ("Mountain - Denver", "America/Denver"),
    ("Mountain - Edmonton", "America/Edmonton"),
    ("Mountain - Phoenix", "America/Phoenix"),
    ("Central - Chicago", "America/Chicago"),
    ("Central - Winnipeg", "America/Winnipeg"),
    ("Eastern - New York", "America/New_York"),
    ("Eastern - Toronto", "America/Toronto"),
    ("Atlantic - Halifax", "America/Halifax"),
    ("Atlantic - Puerto Rico", "America/Puerto_Rico"),
]

def get_timezone(key: str):
    try:
        return ZoneInfo(key)
    except ZoneInfoNotFoundError:
        if key in FALLBACK_TIMEZONES:
            return FALLBACK_TIMEZONES[key]
        raise TimezoneError(f"No time zone found with key {key}. Install the 'tzdata' package for full coverage.") from None

UTC = get_timezone("UTC")
ATTACHMENTS_DIR = Path("hospital_attachments")
try:
    ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

def format_section(title: str, items: List[str]) -> str:
    return f"{title}:\n" + "\n".join(f"- {item}" for item in items)

NOTE_TEMPLATES = [
    {
        "id": "routine_followup",
        "name": "Routine follow-up",
        "text": "Subjective: Patient reports stable symptoms.\nObjective: Vitals within normal limits.\nAssessment: Condition stable.\nPlan: Continue current therapy and reassess at next visit.",
    },
    {
        "id": "post_op_check",
        "name": "Post-op check",
        "text": "Subjective: Post-operative day 7, pain well controlled.\nObjective: Incision clean, dry, intact.\nAssessment: Healing appropriately.\nPlan: Remove sutures next visit, reinforce wound care instructions.",
    },
]
NOTE_TEMPLATE_LOOKUP = {tpl["id"]: tpl for tpl in NOTE_TEMPLATES}

T = TypeVar("T")

BILLING_TEMPLATES = [
    {
        "id": "office_visit_established",
        "name": "Office Visit (99213)",
        "code": "99213",
        "amount": 150.0,
        "description": "Established patient office visit, moderate complexity.",
    },
    {
        "id": "telehealth_consult",
        "name": "Telehealth Consult (Q0506)",
        "code": "Q0506",
        "amount": 200.0,
        "description": "Telehealth rehabilitation consult.",
    },
]
BILLING_TEMPLATE_LOOKUP = {tpl["id"]: tpl for tpl in BILLING_TEMPLATES}

REMINDER_TEMPLATES = [
    {
        "id": "follow_up_two_weeks",
        "name": "Follow-up in 2 weeks",
        "text": "Reminder: schedule a follow-up appointment in two weeks.",
    },
    {
        "id": "lab_results_review",
        "name": "Review lab results",
        "text": "Reminder: review pending lab results and contact patient with findings.",
    },
]
REMINDER_TEMPLATE_LOOKUP = {tpl["id"]: tpl for tpl in REMINDER_TEMPLATES}

# -----------------------------
# Value Objects
# -----------------------------
@dataclass(frozen=True)
class TimeBlock:
    """Time range used for provider availability, appointments, or stays."""

    start_dt: datetime
    end_dt: datetime
    label: str
    type: str  # 'availability'|'appt'|'leave'|'admission'

    @staticmethod
    def overlaps(a: "TimeBlock", b: "TimeBlock") -> bool:
        """Return True when two time blocks intersect."""
        return not (a.end_dt <= b.start_dt or a.start_dt >= b.end_dt)

    def intersects(self, other: "TimeBlock") -> bool:
        """Convenience wrapper that reuses the static overlap helper."""
        return self.__class__.overlaps(self, other)

@dataclass(frozen=True)
class Charge:
    code: str
    amount: float
    dt: datetime
    description: str = ""

@dataclass(frozen=True)
class Payment:
    method: str  # 'cash'|'card'|'insurance'
    amount: float
    dt: datetime
    reference: str = ""


@runtime_checkable
class ConflictPolicy(Protocol):
    """Strategy interface for validating proposed schedule blocks."""

    def validate(self, existing: Sequence[TimeBlock], candidate: TimeBlock) -> None:
        """Raise SchedulingConflictError if the candidate conflicts with existing blocks."""


class HardNoOverlapPolicy:
    """Rejects any time block that intersects an existing protected block."""

    _protected_types: Sequence[str] = ("appt", "leave", "admission")

    def validate(self, existing: Sequence[TimeBlock], candidate: TimeBlock) -> None:
        for block in existing:
            if block.type in self._protected_types and TimeBlock.overlaps(block, candidate):
                raise SchedulingConflictError("Schedule conflict")


class AllowBufferPolicy:
    """Allows adjacent appointments while enforcing a configurable safety buffer."""

    _protected_types: Sequence[str] = ("appt", "leave", "admission")

    def __init__(self, buffer_minutes: int = 15) -> None:
        if buffer_minutes < 0:
            raise ValidationError("Buffer minutes must be non-negative.")
        self._buffer = timedelta(minutes=buffer_minutes)

    def validate(self, existing: Sequence[TimeBlock], candidate: TimeBlock) -> None:
        for block in existing:
            if block.type not in self._protected_types:
                continue
            if self._overlaps_with_buffer(block, candidate):
                raise SchedulingConflictError("Schedule conflict within protected buffer window")

    def _overlaps_with_buffer(self, block: TimeBlock, candidate: TimeBlock) -> bool:
        window_start = block.start_dt - self._buffer
        window_end = block.end_dt + self._buffer
        padded = TimeBlock(window_start, window_end, block.label, block.type)
        return TimeBlock.overlaps(padded, candidate)

# -----------------------------
# Core Entities
# -----------------------------
@dataclass
class Person:
    id: str
    name: str
    dob: datetime
    sex: str
    contact_info: Dict[str, str]

    def age(self, asof: Optional[datetime] = None) -> int:
        asof = asof or datetime.now(UTC)
        return int((asof.date() - self.dob.date()).days // 365.25)

    def anonymize(self) -> Dict[str, Any]:
        return {"id": self.id, "year_of_birth": self.dob.year, "sex": self.sex}

@dataclass
class Patient(Person):
    patient_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    primary_doctor_id: Optional[str] = None
    insurance: Optional['InsurancePolicy'] = None
    allergies: List[str] = field(default_factory=list)

@dataclass
class Doctor(Person):
    doctor_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    specialty: str = ""
    department_id: Optional[str] = None
    license_no: str = ""
    timezone: str = "America/Los_Angeles"  # default PT
    schedule: 'Schedule' = field(default_factory=lambda: Schedule())

    def update_details(
        self,
        *,
        name: Optional[str] = None,
        dob: Optional[datetime] = None,
        sex: Optional[str] = None,
        contact_info: Optional[Mapping[str, str]] = None,
        specialty: Optional[str] = None,
        department_id: Optional[str] = None,
        license_no: Optional[str] = None,
        timezone: Optional[str] = None,
        schedule: Optional['Schedule'] = None,
    ) -> None:
        """
        Update mutable fields for the doctor profile. Identifiers remain unchanged.

        Any argument left as None keeps the current value. The timezone is validated
        using the same helper that is applied during registration.
        """
        if name is not None:
            self.name = name
        if dob is not None:
            if not isinstance(dob, datetime):
                raise ValidationError("dob must be a datetime instance.")
            self.dob = dob
        if sex is not None:
            normalized = sex.upper()
            if normalized not in {"M", "F", "X", "U"}:
                raise ValidationError("sex must be one of M, F, X, or U.")
            self.sex = normalized
        if contact_info is not None:
            self.contact_info = dict(contact_info)
        if specialty is not None:
            self.specialty = specialty
        if department_id is not None:
            self.department_id = department_id
        if license_no is not None:
            self.license_no = license_no
        if timezone is not None:
            get_timezone(timezone)
            self.timezone = timezone
        if schedule is not None:
            if not isinstance(schedule, Schedule):
                raise ValidationError("schedule must be an instance of Schedule.")
            self.schedule = schedule

@dataclass
class Department:
    dept_id: str
    name: str
    location: str
    head_doctor_id: Optional[str] = None

@dataclass
class Appointment:
    """Scheduled encounter between a patient and a clinician."""

    appt_id: str
    patient_id: str
    doctor_id: str
    dept_id: str
    start_dt: datetime  # timezone-aware
    end_dt: datetime    # timezone-aware
    status: str = "scheduled"  # 'scheduled'|'completed'|'cancelled'
    reason: str = ""

    _VALID_STATUSES: ClassVar[Tuple[str, ...]] = ("scheduled", "completed", "cancelled")

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "status" and value not in self._VALID_STATUSES:
            raise ValidationError(f"Invalid appointment status '{value}'. Allowed: {', '.join(self._VALID_STATUSES)}")
        super().__setattr__(name, value)

@dataclass
class MedicalRecord:
    record_id: str
    patient_id: str
    entries: List['RecordEntry'] = field(default_factory=list)
    attachments: List['RecordAttachment'] = field(default_factory=list)
    allergies: List[str] = field(default_factory=list)
    meds_active: List[str] = field(default_factory=list)

@dataclass
class RecordEntry:
    entry_id: str
    created_dt: datetime
    author_id: str
    notes: str
    type: str  # 'visit'|'diagnosis'|'prescription'|'lab_order'|'lab_result'|'procedure'

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "created_dt": self.created_dt.isoformat(),
            "author_id": self.author_id,
            "notes": self.notes,
            "type": self.type,
        }

@dataclass
class RecordAttachment:
    attachment_id: str
    record_id: str
    filename: str
    stored_path: str
    uploaded_dt: datetime
    note: str = ""

# Inpatient
@dataclass
class Bed:
    """Represents a physical bed within the inpatient ward."""

    bed_id: str
    room_id: str
    status: str = "free"  # 'free'|'occupied'|'cleaning'
    occupant_patient_id: Optional[str] = None

    _VALID_STATUSES: ClassVar[Tuple[str, ...]] = ("free", "occupied", "cleaning")

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "status" and value not in self._VALID_STATUSES:
            raise ValidationError(f"Invalid bed status '{value}'. Allowed: {', '.join(self._VALID_STATUSES)}")
        super().__setattr__(name, value)

# Insurance and Billing
@dataclass
class InsuranceProvider:
    """Basic metadata describing an insurance carrier."""

    provider_id: str
    name: str
    country: str  # 'US'|'CA'


@dataclass
class InsurancePolicy:
    """Insurance policy with copay configuration."""

    policy_id: str
    provider: InsuranceProvider
    plan: str
    member_no: str
    copay_percent: float = 0.2


@dataclass
class BillingAccount:
    """Tracks patient-level financial activity."""

    acct_id: str
    patient_id: str
    charges: List[Charge] = field(default_factory=list)
    payments: List[Payment] = field(default_factory=list)

    def add_charge(self, charge: Charge) -> None:
        """Record a new charge."""
        self.charges.append(charge)

    def add_payment(self, payment: Payment) -> None:
        """Record a payment against outstanding charges."""
        self.payments.append(payment)

    def balance(self) -> float:
        """Return the current outstanding balance."""
        return round(sum(c.amount for c in self.charges) - sum(p.amount for p in self.payments), 2)


@runtime_checkable
class BillingStrategy(Protocol):
    """Strategy interface for applying billing rules."""

    def bill(self, patient: Patient, account: BillingAccount, code: str, base_amount: float, description: str) -> Charge:
        """Apply a charge to the provided account and return it."""


class SelfPayStrategy:
    """Default billing logic for patients paying directly."""

    def bill(self, patient: Patient, account: BillingAccount, code: str, base_amount: float, description: str) -> Charge:
        charge = Charge(code=code, amount=round(base_amount, 2), dt=datetime.now(UTC), description=description)
        account.add_charge(charge)
        return charge


class InsuranceStrategy:
    """Billing logic that respects insurance copay percentages."""

    def bill(self, patient: Patient, account: BillingAccount, code: str, base_amount: float, description: str) -> Charge:
        if not patient.insurance:
            raise ValidationError("Patient does not have an insurance policy configured.")
        policy = patient.insurance
        patient_portion = round(base_amount * policy.copay_percent, 2)
        details = f"{description} (copay {policy.copay_percent:.0%})"
        charge = Charge(code=code, amount=patient_portion, dt=datetime.now(UTC), description=details)
        account.add_charge(charge)
        return charge

# Schedules
@dataclass
class Schedule:
    """Mutable collection of time blocks for a clinician."""

    blocks: List[TimeBlock] = field(default_factory=list)

    def is_free(self, rng: Tuple[datetime, datetime], policy: Optional[ConflictPolicy] = None) -> bool:
        """Return True when a time range can be scheduled without violating the policy."""
        policy = policy or HardNoOverlapPolicy()
        probe = TimeBlock(rng[0], rng[1], "probe", "appt")
        try:
            policy.validate(self.blocks, probe)
        except SchedulingConflictError:
            return False
        return True

    def add_block(self, block: TimeBlock, policy: Optional[ConflictPolicy] = None) -> None:
        """Append a block after validating it with the supplied policy."""
        policy = policy or HardNoOverlapPolicy()
        policy.validate(self.blocks, block)
        self.blocks.append(block)

    def remove_block(self, block: TimeBlock) -> None:
        """Remove a previously scheduled block."""
        self.blocks.remove(block)

    @property
    def protected_view(self) -> Tuple[TimeBlock, ...]:
        """Expose a read-only snapshot of the schedule."""
        return tuple(self.blocks)

# -----------------------------
# Repositories (in-memory)
# -----------------------------
@runtime_checkable
class Repo(Protocol[T]):
    """CRUD contract used by services to interact with persistence layers."""

    def get(self, obj_id: str) -> T: ...

    def add(self, obj: T) -> T: ...

    def update(self, obj: T) -> T: ...

    def find(self, **filters: Any) -> List[T]: ...

    def all(self) -> Iterable[T]: ...


class MemoryRepo(Generic[T]):
    """Simple in-memory repository used for interactive demo flows."""

    def __init__(self, key: str):
        self._key = key
        self._data: Dict[str, T] = {}

    @property
    def key(self) -> str:
        """Identifier attribute this repository indexes on."""
        return self._key

    def get(self, obj_id: str) -> T:
        if obj_id not in self._data:
            raise NotFoundError(f"{self._key} not found: {obj_id}")
        return self._data[obj_id]

    def add(self, obj: T) -> T:
        oid = getattr(obj, self._key)
        if oid in self._data:
            raise DuplicateError(f"{self._key} exists: {oid}")
        self._data[oid] = obj
        return obj

    def update(self, obj: T) -> T:
        oid = getattr(obj, self._key)
        if oid not in self._data:
            raise NotFoundError(f"{self._key} not found: {oid}")
        self._data[oid] = obj
        return obj

    def all(self) -> Iterable[T]:
        return tuple(self._data.values())

    def find(self, **filters: Any) -> List[T]:
        results: List[T] = []
        for value in self._data.values():
            if all(getattr(value, field) == expected for field, expected in filters.items()):
                results.append(value)
        return results

# Typed repos
class PatientRepo(MemoryRepo[Patient]):
    def __init__(self): super().__init__("patient_id")
class DoctorRepo(MemoryRepo[Doctor]):
    def __init__(self): super().__init__("doctor_id")
class DepartmentRepo(MemoryRepo[Department]):
    def __init__(self): super().__init__("dept_id")
class AppointmentRepo(MemoryRepo[Appointment]):
    def __init__(self): super().__init__("appt_id")
class RecordRepo(MemoryRepo[MedicalRecord]):
    def __init__(self): super().__init__("record_id")
class BillingRepo(MemoryRepo[BillingAccount]):
    def __init__(self): super().__init__("acct_id")
class BedRepo(MemoryRepo[Bed]):
    def __init__(self): super().__init__("bed_id")
class InsuranceProviderRepo(MemoryRepo[InsuranceProvider]):
    def __init__(self): super().__init__("provider_id")
class PolicyRepo(MemoryRepo[InsurancePolicy]):
    def __init__(self): super().__init__("policy_id")

@dataclass
class SystemContext:
    """Aggregates repositories, services, and security state."""

    patients: Repo[Patient]
    doctors: Repo[Doctor]
    depts: Repo[Department]
    appts: Repo[Appointment]
    records: Repo[MedicalRecord]
    billing: Repo[BillingAccount]
    beds: Repo[Bed]
    providers: Repo[InsuranceProvider]
    policies: Repo[InsurancePolicy]
    audit: AuditLog
    auth: AuthService
    appt_svc: AppointmentService
    rec_svc: MedicalRecordService
    bill_svc: BillingService
    ip_svc: InpatientService
    users: Dict[str, User]

    @classmethod
    def create_default(cls, seed_defaults: bool = True) -> "SystemContext":
        """Factory building a fully wired system with optional seed data."""
        patients = PatientRepo()
        doctors = DoctorRepo()
        depts = DepartmentRepo()
        appts = AppointmentRepo()
        records = RecordRepo()
        billing = BillingRepo()
        beds = BedRepo()
        if seed_defaults:
            providers, policies = seed_insurers()
        else:
            providers = InsuranceProviderRepo()
            policies = PolicyRepo()
        audit = AuditLog()
        users: Dict[str, User] = {}
        auth = AuthService(users)

        conflict_policy = HardNoOverlapPolicy()
        appt_svc = AppointmentService(appts, patients, doctors, depts, audit, auth, conflict_policy=conflict_policy)
        rec_svc = MedicalRecordService(records, patients, audit, auth)
        bill_svc = BillingService(billing, patients, policies, audit, auth)
        ip_svc = InpatientService(beds, patients, doctors, audit, auth, conflict_policy=conflict_policy)

        default_users = [
            ("admin", ["admin", "billing"], "admin123"),
            ("clerk", ["clerk"], "clerk123"),
            ("nurse", ["nurse"], "nurse123"),
            ("doctor", ["doctor"], "doctor123"),
        ]
        for username, roles, password in default_users:
            user = User(user_id=username, roles=roles)
            auth.register_user(user, password)

        return cls(
            patients=patients,
            doctors=doctors,
            depts=depts,
            appts=appts,
            records=records,
            billing=billing,
            beds=beds,
            providers=providers,
            policies=policies,
            audit=audit,
            auth=auth,
            appt_svc=appt_svc,
            rec_svc=rec_svc,
            bill_svc=bill_svc,
            ip_svc=ip_svc,
            users=users,
        )

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

# -----------------------------
# Services
# -----------------------------
class AppointmentService:
    """Coordinates appointment lifecycle events."""

    def __init__(
        self,
        appts: Repo[Appointment],
        patients: Repo[Patient],
        doctors: Repo[Doctor],
        depts: Repo[Department],
        audit: AuditLog,
        auth: AuthService,
        conflict_policy: Optional[ConflictPolicy] = None,
    ) -> None:
        self._appts = appts
        self._patients = patients
        self._doctors = doctors
        self._depts = depts
        self._audit = audit
        self._auth = auth
        self._conflict_policy: ConflictPolicy = conflict_policy or HardNoOverlapPolicy()

    @property
    def conflict_policy(self) -> ConflictPolicy:
        """Return the currently configured scheduling policy."""
        return self._conflict_policy

    def set_conflict_policy(self, policy: ConflictPolicy) -> None:
        """Swap the active scheduling policy."""
        self._conflict_policy = policy

    def book(
        self,
        user: User,
        patient_id: str,
        doctor_id: str,
        dept_id: str,
        start: datetime,
        end: datetime,
        reason: str,
    ) -> Appointment:
        """Create a new appointment when the requested slot is available."""
        require_role(user, ["admin", "clerk", "doctor"], auth=self._auth, token=user.session_token)
        if start.tzinfo is None or end.tzinfo is None:
            raise TimezoneError("datetime must be timezone-aware")
        if end <= start:
            raise ValidationError("Appointment end time must be after its start time.")
        patient = self._patients.get(patient_id)
        doctor = self._doctors.get(doctor_id)
        _ = self._depts.get(dept_id)
        doctor_tz = get_timezone(doctor.timezone)
        rng = (start.astimezone(doctor_tz), end.astimezone(doctor_tz))
        if not doctor.schedule.is_free(rng, self._conflict_policy):
            raise SchedulingConflictError("Doctor not available")
        appt = Appointment(
            appt_id=str(uuid.uuid4()),
            patient_id=patient.patient_id,
            doctor_id=doctor.doctor_id,
            dept_id=dept_id,
            start_dt=start,
            end_dt=end,
            status="scheduled",
            reason=reason,
        )
        self._appts.add(appt)
        doctor.schedule.add_block(TimeBlock(rng[0], rng[1], f"Appt {appt.appt_id}", "appt"), self._conflict_policy)
        self._doctors.update(doctor)
        self._audit.log(
            AuditEvent.for_action(
                user.user_id,
                "book_appointment",
                after={"appt_id": appt.appt_id, "doctor_id": doctor_id, "patient_id": patient_id},
            )
        )
        return appt

    def complete(self, user: User, appt_id: str) -> Appointment:
        """Mark an appointment as completed."""
        require_role(user, ["admin", "doctor", "nurse"], auth=self._auth, token=user.session_token)
        appt = self._appts.get(appt_id)
        if appt.status != "scheduled":
            raise ValidationError("Only scheduled appointments can be completed.")
        before = {"status": appt.status}
        appt.status = "completed"
        self._appts.update(appt)
        self._audit.log(
            AuditEvent.for_action(
                user.user_id,
                "complete_appointment",
                before=before,
                after={"status": appt.status, "appt_id": appt.appt_id},
            )
        )
        return appt

class MedicalRecordService:
    """Maintains longitudinal patient documentation."""

    def __init__(self, records: Repo[MedicalRecord], patients: Repo[Patient], audit: AuditLog, auth: AuthService):
        self._records = records
        self._patients = patients
        self._audit = audit
        self._auth = auth
        self._attachments_dir = ATTACHMENTS_DIR

    @property
    def attachments_dir(self) -> Path:
        """Read-only exposure of the attachment root path."""
        return self._attachments_dir

    def ensure_record(self, patient_id: str) -> MedicalRecord:
        """Return the existing medical record or create a new chart."""
        for record in self._records.all():
            if record.patient_id == patient_id:
                return record
        patient = self._patients.get(patient_id)
        record = MedicalRecord(record_id=str(uuid.uuid4()), patient_id=patient.patient_id)
        self._records.add(record)
        return record

    def append_entry(self, user: User, patient_id: str, entry_type: str, notes: str, author_id: str) -> RecordEntry:
        """Append a structured clinical note."""
        require_role(user, ["admin", "doctor", "nurse"], auth=self._auth, token=user.session_token)
        record = self.ensure_record(patient_id)
        entry = RecordEntry(
            entry_id=str(uuid.uuid4()),
            created_dt=datetime.now(UTC),
            author_id=author_id,
            notes=notes,
            type=entry_type,
        )
        record.entries.append(entry)
        self._records.update(record)
        self._audit.log(
            AuditEvent.for_action(
                user.user_id,
                "append_record_entry",
                after={"entry_id": entry.entry_id, "patient_id": patient_id, "type": entry_type},
            )
        )
        return entry

    def add_attachment(self, user: User, patient_id: str, source_path: str, note: str = "") -> RecordAttachment:
        """Store a binary attachment on the patient's chart."""
        require_role(user, ["admin", "doctor", "nurse"], auth=self._auth, token=user.session_token)
        record = self.ensure_record(patient_id)
        src = Path(source_path)
        if not src.exists() or not src.is_file():
            raise FileNotFoundError(f"File not found: {source_path}")
        patient_dir = self._attachments_dir / patient_id
        patient_dir.mkdir(parents=True, exist_ok=True)
        dest_name = f"{uuid.uuid4()}_{src.name}"
        dest_path = patient_dir / dest_name
        shutil.copy2(src, dest_path)
        relative_path = dest_path.relative_to(self._attachments_dir)
        attachment = RecordAttachment(
            attachment_id=str(uuid.uuid4()),
            record_id=record.record_id,
            filename=src.name,
            stored_path=str(relative_path),
            uploaded_dt=datetime.now(UTC),
            note=note,
        )
        record.attachments.append(attachment)
        self._records.update(record)
        self._audit.log(
            AuditEvent.for_action(
                user.user_id,
                "add_attachment",
                after={"record_id": record.record_id, "filename": src.name},
            )
        )
        return attachment

class BillingService:
    """Applies financial transactions using pluggable billing strategies."""

    def __init__(
        self,
        billing: Repo[BillingAccount],
        patients: Repo[Patient],
        policies: Repo[InsurancePolicy],
        audit: AuditLog,
        auth: AuthService,
        default_strategy: Optional[BillingStrategy] = None,
        insurance_strategy: Optional[BillingStrategy] = None,
    ) -> None:
        self._billing = billing
        self._patients = patients
        self._policies = policies
        self._audit = audit
        self._auth = auth
        self._default_strategy: BillingStrategy = default_strategy or SelfPayStrategy()
        self._insurance_strategy: BillingStrategy = insurance_strategy or InsuranceStrategy()

    def set_strategies(self, *, default: Optional[BillingStrategy] = None, insurance: Optional[BillingStrategy] = None) -> None:
        """Swap billing strategies at runtime."""
        if default:
            self._default_strategy = default
        if insurance:
            self._insurance_strategy = insurance

    def ensure_account(self, patient_id: str) -> BillingAccount:
        """Locate or lazily create a billing account for the patient."""
        for account in self._billing.all():
            if account.patient_id == patient_id:
                return account
        account = BillingAccount(acct_id=str(uuid.uuid4()), patient_id=patient_id)
        self._billing.add(account)
        return account

    def invoice(self, user: User, patient_id: str, code: str, amount: float, description: str) -> Charge:
        """Apply a charge using the appropriate billing strategy."""
        require_role(user, ["admin", "billing"], auth=self._auth, token=user.session_token)
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount) or amount <= 0:
            raise ValidationError("Charge amount must be a positive finite number.")
        patient = self._patients.get(patient_id)
        account = self.ensure_account(patient_id)
        strategy = self._insurance_strategy if patient.insurance else self._default_strategy
        charge = strategy.bill(patient, account, code, amount, description)
        self._billing.update(account)
        self._audit.log(
            AuditEvent.for_action(
                user.user_id,
                "invoice",
                after={"patient_id": patient_id, "amount": charge.amount, "code": code},
            )
        )
        return charge

    def post_payment(self, user: User, patient_id: str, method: str, amount: float, reference: str = "") -> Payment:
        """Record a payment against a patient's account."""
        require_role(user, ["admin", "billing"], auth=self._auth, token=user.session_token)
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount) or amount <= 0:
            raise ValidationError("Payment amount must be a positive finite number.")
        if method not in ("cash", "card", "insurance"):
            raise ValidationError("Unsupported payment method.")
        self._patients.get(patient_id)
        account = self.ensure_account(patient_id)
        payment = Payment(method=method, amount=amount, dt=datetime.now(UTC), reference=reference)
        account.add_payment(payment)
        self._billing.update(account)
        self._audit.log(
            AuditEvent.for_action(
                user.user_id,
                "payment",
                after={"patient_id": patient_id, "amount": amount, "method": method},
            )
        )
        return payment

class InpatientService:
    """Coordinates bed assignments and provider schedules for admissions."""

    def __init__(
        self,
        beds: Repo[Bed],
        patients: Repo[Patient],
        doctors: Repo[Doctor],
        audit: AuditLog,
        auth: AuthService,
        conflict_policy: Optional[ConflictPolicy] = None,
    ) -> None:
        self._beds = beds
        self._patients = patients
        self._doctors = doctors
        self._audit = audit
        self._auth = auth
        self._conflict_policy: ConflictPolicy = conflict_policy or HardNoOverlapPolicy()

    def set_conflict_policy(self, policy: ConflictPolicy) -> None:
        """Swap the conflict policy used for admissions."""
        self._conflict_policy = policy

    def admit(
        self,
        user: User,
        patient_id: str,
        doctor_id: str,
        hours: int = 24,
        start_dt: Optional[datetime] = None,
    ) -> Bed:
        """Assign the first available bed to a patient."""
        require_role(user, ["admin", "nurse"], auth=self._auth, token=user.session_token)
        if hours <= 0:
            raise ValidationError("Admission duration must be positive.")
        if start_dt is not None and start_dt.tzinfo is None:
            raise TimezoneError("Admission start time must be timezone-aware.")
        self._patients.get(patient_id)
        if any(bed.occupant_patient_id == patient_id for bed in self._beds.all()):
            raise SchedulingConflictError("Patient is already admitted.")
        next_bed = next((bed for bed in self._beds.all() if bed.status == "free"), None)
        if not next_bed:
            raise SchedulingConflictError("No beds available")
        doctor = self._doctors.get(doctor_id)
        doctor_tz = get_timezone(doctor.timezone)
        start_local = start_dt.astimezone(doctor_tz) if start_dt else datetime.now(doctor_tz)
        block = TimeBlock(start_local, start_local + timedelta(hours=hours), f"Admission for {patient_id}", "admission")
        doctor.schedule.add_block(block, self._conflict_policy)
        next_bed.status = "occupied"
        next_bed.occupant_patient_id = patient_id
        self._beds.update(next_bed)
        self._doctors.update(doctor)
        self._audit.log(
            AuditEvent.for_action(
                user.user_id,
                "admit",
                after={"patient_id": patient_id, "bed_id": next_bed.bed_id, "doctor_id": doctor_id},
            )
        )
        return next_bed

    def discharge(self, user: User, bed_id: str) -> Bed:
        """Discharge a patient and mark the bed for cleaning."""
        require_role(user, ["admin", "nurse"], auth=self._auth, token=user.session_token)
        bed = self._beds.get(bed_id)
        if bed.status != "occupied" or bed.occupant_patient_id is None:
            raise ValidationError("Only occupied beds can be discharged.")
        bed.status = "cleaning"
        bed.occupant_patient_id = None
        self._beds.update(bed)
        self._audit.log(
            AuditEvent.for_action(
                user.user_id,
                "discharge",
                after={"bed_id": bed.bed_id},
            )
        )
        return bed

def seed_insurers() -> Tuple[InsuranceProviderRepo, PolicyRepo]:
    providers = InsuranceProviderRepo()
    policies = PolicyRepo()
    seeds = [
        ("us_blueshield_ca", "Blue Shield of California", "US"),
        ("us_kp", "Kaiser Permanente", "US"),
        ("us_aetna", "Aetna", "US"),
        ("ca_bluecross_ns", "Medavie Blue Cross NS", "CA"),
        ("ca_manulife", "Manulife", "CA"),
    ]
    for pid, name, country in seeds:
        providers.add(InsuranceProvider(provider_id=pid, name=name, country=country))
    return providers, policies

def initialize_system(seed_defaults: bool = True) -> SystemContext:
    """Backward-compatible shim that delegates to SystemContext.create_default."""
    return SystemContext.create_default(seed_defaults=seed_defaults)

def create_physician(
    ctx: SystemContext,
    *,
    name: str,
    dob: datetime,
    sex: str,
    email: str,
    specialty: str,
    license_no: str,
    timezone_name: str,
    department_name: str,
    department_location: str,
    username: Optional[str]=None,
    password: Optional[str]=None,
    existing_user: Optional[User]=None,
) -> Tuple[Doctor, User]:
    get_timezone(timezone_name)  # validate
    if existing_user is None:
        if username is None or password is None:
            raise ValidationError("Username and password required for new physician users.")
        if username in ctx.users:
            raise DuplicateError(f"Username already exists: {username}")
    elif (
        ctx.users.get(existing_user.user_id) is not existing_user
        or not ctx.auth.validate_session(existing_user.user_id, existing_user.session_token or "")
    ):
        raise AuthorizationError("Physician account requires an active session.")
    dept = Department(dept_id=str(uuid.uuid4()), name=department_name, location=department_location)
    ctx.depts.add(dept)
    contact = {"email": email} if email else {}
    doctor = Doctor(
        id=str(uuid.uuid4()),
        name=name,
        dob=dob,
        sex=sex or "U",
        contact_info=contact,
        specialty=specialty,
        department_id=dept.dept_id,
        license_no=license_no,
        timezone=timezone_name,
    )
    ctx.doctors.add(doctor)
    if existing_user:
        existing_user.roles = sorted(set(existing_user.roles + ["doctor", "clerk"]))
        existing_user.person_id = doctor.doctor_id
        user = existing_user
    else:
        user = User(user_id=username, roles=["doctor", "clerk"], person_id=doctor.doctor_id)
        ctx.auth.register_user(user, password)
        ctx.auth.authenticate(username, password)
    ctx.users[user.user_id] = user
    return doctor, user

def create_patient(
    ctx: SystemContext,
    doctor: Doctor,
    *,
    name: str,
    dob: datetime,
    sex: str,
    email: str="",
    allergies: Optional[List[str]]=None,
    insurance_provider_id: Optional[str]=None,
    insurance_plan: str="",
    insurance_member_no: str="",
    insurance_copay: float=0.2,
) -> Patient:
    allergies = allergies or []
    insurance_policy: Optional[InsurancePolicy] = None
    if insurance_provider_id:
        provider = ctx.providers.get(insurance_provider_id)
        insurance_policy = InsurancePolicy(
            policy_id=str(uuid.uuid4()),
            provider=provider,
            plan=insurance_plan or "Standard",
            member_no=insurance_member_no or "UNKNOWN",
            copay_percent=insurance_copay,
        )
        ctx.policies.add(insurance_policy)
    contact = {"email": email} if email else {}
    patient = Patient(
        id=str(uuid.uuid4()),
        name=name,
        dob=dob,
        sex=sex or "U",
        contact_info=contact,
        primary_doctor_id=doctor.doctor_id,
        insurance=insurance_policy,
        allergies=allergies,
    )
    ctx.patients.add(patient)
    return patient

def suggest_appointment_slots(doctor: Doctor, duration_minutes: int, count: int=3) -> List[datetime]:
    tz = get_timezone(doctor.timezone)
    now_local = datetime.now(tz)
    step = timedelta(minutes=15)
    suggestions: List[datetime] = []
    availability_blocks = sorted(
        [block for block in doctor.schedule.blocks if block.type == "availability"],
        key=lambda b: b.start_dt,
    )
    for block in availability_blocks:
        start_cursor = max(block.start_dt, now_local)
        end_limit = block.end_dt - timedelta(minutes=duration_minutes)
        while start_cursor <= end_limit:
            candidate_end = start_cursor + timedelta(minutes=duration_minutes)
            if doctor.schedule.is_free((start_cursor, candidate_end)):
                suggestions.append(start_cursor)
                if len(suggestions) >= count:
                    return suggestions
            start_cursor += step
    # Fallback scan up to 7 days ahead if availability blocks did not provide enough options
    candidate = now_local
    max_horizon = now_local + timedelta(days=7)
    while len(suggestions) < count and candidate < max_horizon:
        candidate = candidate.replace(second=0, microsecond=0)
        candidate_end = candidate + timedelta(minutes=duration_minutes)
        if doctor.schedule.is_free((candidate, candidate_end)):
            suggestions.append(candidate)
        candidate += step
    return suggestions[:count]

def datetime_to_iso(dt: datetime) -> str:
    return dt.isoformat()

def datetime_from_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt

def context_to_dict(ctx: SystemContext) -> Dict[str, Any]:
    def serialize_timeblock(block: TimeBlock) -> Dict[str, Any]:
        return {
            "start": datetime_to_iso(block.start_dt),
            "end": datetime_to_iso(block.end_dt),
            "label": block.label,
            "type": block.type,
        }

    data: Dict[str, Any] = {
        "users": [
            {
                "user_id": user.user_id,
                "roles": user.roles,
                "person_id": user.person_id,
                "password": user.password or "",
                "password_hash": user.password_hash,
                "password_salt": user.password_salt,
            }
            for user in ctx.users.values()
        ],
        "providers": [
            {
                "provider_id": provider.provider_id,
                "name": provider.name,
                "country": provider.country,
            }
            for provider in ctx.providers.all()
        ],
        "policies": [
            {
                "policy_id": policy.policy_id,
                "provider_id": policy.provider.provider_id,
                "plan": policy.plan,
                "member_no": policy.member_no,
                "copay_percent": policy.copay_percent,
            }
            for policy in ctx.policies.all()
        ],
        "departments": [
            {
                "dept_id": dept.dept_id,
                "name": dept.name,
                "location": dept.location,
                "head_doctor_id": dept.head_doctor_id,
            }
            for dept in ctx.depts.all()
        ],
        "doctors": [
            {
                "doctor_id": doc.doctor_id,
                "id": doc.id,
                "name": doc.name,
                "dob": datetime_to_iso(doc.dob),
                "sex": doc.sex,
                "contact_info": doc.contact_info,
                "specialty": doc.specialty,
                "department_id": doc.department_id,
                "license_no": doc.license_no,
                "timezone": doc.timezone,
                "schedule": [serialize_timeblock(block) for block in doc.schedule.blocks],
            }
            for doc in ctx.doctors.all()
        ],
        "patients": [
            {
                "patient_id": pat.patient_id,
                "id": pat.id,
                "name": pat.name,
                "dob": datetime_to_iso(pat.dob),
                "sex": pat.sex,
                "contact_info": pat.contact_info,
                "primary_doctor_id": pat.primary_doctor_id,
                "insurance_policy_id": pat.insurance.policy_id if pat.insurance else None,
                "allergies": pat.allergies,
            }
            for pat in ctx.patients.all()
        ],
        "appointments": [
            {
                "appt_id": appt.appt_id,
                "patient_id": appt.patient_id,
                "doctor_id": appt.doctor_id,
                "dept_id": appt.dept_id,
                "start_dt": datetime_to_iso(appt.start_dt),
                "end_dt": datetime_to_iso(appt.end_dt),
                "status": appt.status,
                "reason": appt.reason,
            }
            for appt in ctx.appts.all()
        ],
        "records": [
            {
                "record_id": rec.record_id,
                "patient_id": rec.patient_id,
                "entries": [
                    {
                        "entry_id": entry.entry_id,
                        "created_dt": datetime_to_iso(entry.created_dt),
                        "author_id": entry.author_id,
                        "notes": entry.notes,
                        "type": entry.type,
                    }
                    for entry in rec.entries
                ],
                "attachments": [
                    {
                        "attachment_id": att.attachment_id,
                        "filename": att.filename,
                        "stored_path": att.stored_path,
                        "uploaded_dt": datetime_to_iso(att.uploaded_dt),
                        "note": att.note,
                    }
                    for att in rec.attachments
                ],
                "allergies": rec.allergies,
                "meds_active": rec.meds_active,
            }
            for rec in ctx.records.all()
        ],
        "billing": [
            {
                "acct_id": acct.acct_id,
                "patient_id": acct.patient_id,
                "charges": [
                    {
                        "code": charge.code,
                        "amount": charge.amount,
                        "dt": datetime_to_iso(charge.dt),
                        "description": charge.description,
                    }
                    for charge in acct.charges
                ],
                "payments": [
                    {
                        "method": payment.method,
                        "amount": payment.amount,
                        "dt": datetime_to_iso(payment.dt),
                        "reference": payment.reference,
                    }
                    for payment in acct.payments
                ],
            }
            for acct in ctx.billing.all()
        ],
        "beds": [
            {
                "bed_id": bed.bed_id,
                "room_id": bed.room_id,
                "status": bed.status,
                "occupant_patient_id": bed.occupant_patient_id,
            }
            for bed in ctx.beds.all()
        ],
        "audit": [
            {
                "who": ev.who,
                "what": ev.what,
                "when": datetime_to_iso(ev.when),
                "before": ev.before,
                "after": ev.after,
                "prev_hash": ev.prev_hash,
                "event_hash": ev.event_hash,
            }
            for ev in ctx.audit.events
        ],
    }
    return data

def context_from_dict(data: Dict[str, Any]) -> SystemContext:
    ctx = initialize_system(seed_defaults=False)
    ctx.users.clear()
    for user_info in data.get("users", []):
        user = User(
            user_id=user_info["user_id"],
            roles=user_info.get("roles", []),
            person_id=user_info.get("person_id"),
        )
        password_hash = user_info.get("password_hash")
        password_salt = user_info.get("password_salt")
        if password_hash and password_salt:
            user.password = ""
            user.password_hash = password_hash
            user.password_salt = password_salt
            user.clear_sessions()
            ctx.users[user.user_id] = user
        else:
            password = user_info.get("password", "password")
            ctx.auth.register_user(user, password)
        if user.user_id not in ctx.users:
            ctx.users[user.user_id] = user
    for provider in data.get("providers", []):
        ctx.providers.add(
            InsuranceProvider(
                provider_id=provider["provider_id"],
                name=provider["name"],
                country=provider["country"],
            )
        )
    for policy in data.get("policies", []):
        provider = ctx.providers.get(policy["provider_id"])
        ctx.policies.add(
            InsurancePolicy(
                policy_id=policy["policy_id"],
                provider=provider,
                plan=policy["plan"],
                member_no=policy["member_no"],
                copay_percent=policy.get("copay_percent", 0.2),
            )
        )
    for dept in data.get("departments", []):
        ctx.depts.add(
            Department(
                dept_id=dept["dept_id"],
                name=dept["name"],
                location=dept["location"],
                head_doctor_id=dept.get("head_doctor_id"),
            )
        )
    for doc_info in data.get("doctors", []):
        schedule_blocks = [
            TimeBlock(
                start_dt=datetime_from_iso(block["start"]),
                end_dt=datetime_from_iso(block["end"]),
                label=block["label"],
                type=block["type"],
            )
            for block in doc_info.get("schedule", [])
        ]
        doctor = Doctor(
            id=doc_info["id"],
            name=doc_info["name"],
            dob=datetime_from_iso(doc_info["dob"]),
            sex=doc_info["sex"],
            contact_info=doc_info.get("contact_info", {}),
            specialty=doc_info.get("specialty", ""),
            department_id=doc_info.get("department_id"),
            license_no=doc_info.get("license_no", ""),
            timezone=doc_info.get("timezone", "UTC"),
            doctor_id=doc_info["doctor_id"],
            schedule=Schedule(blocks=schedule_blocks),
        )
        ctx.doctors.add(doctor)
    for pat_info in data.get("patients", []):
        insurance = None
        if pat_info.get("insurance_policy_id"):
            try:
                insurance = ctx.policies.get(pat_info["insurance_policy_id"])
            except NotFoundError:
                insurance = None
        patient = Patient(
            id=pat_info["id"],
            name=pat_info["name"],
            dob=datetime_from_iso(pat_info["dob"]),
            sex=pat_info["sex"],
            contact_info=pat_info.get("contact_info", {}),
            primary_doctor_id=pat_info.get("primary_doctor_id"),
            insurance=insurance,
            allergies=pat_info.get("allergies", []),
            patient_id=pat_info["patient_id"],
        )
        ctx.patients.add(patient)
    for appt_info in data.get("appointments", []):
        appt = Appointment(
            appt_id=appt_info["appt_id"],
            patient_id=appt_info["patient_id"],
            doctor_id=appt_info["doctor_id"],
            dept_id=appt_info["dept_id"],
            start_dt=datetime_from_iso(appt_info["start_dt"]),
            end_dt=datetime_from_iso(appt_info["end_dt"]),
            status=appt_info.get("status", "scheduled"),
            reason=appt_info.get("reason", ""),
        )
        ctx.appts.add(appt)
    for rec_info in data.get("records", []):
        record = MedicalRecord(
            record_id=rec_info["record_id"],
            patient_id=rec_info["patient_id"],
            entries=[],
            attachments=[],
            allergies=rec_info.get("allergies", []),
            meds_active=rec_info.get("meds_active", []),
        )
        for entry_info in rec_info.get("entries", []):
            record.entries.append(
                RecordEntry(
                    entry_id=entry_info["entry_id"],
                    created_dt=datetime_from_iso(entry_info["created_dt"]),
                    author_id=entry_info["author_id"],
                    notes=entry_info["notes"],
                    type=entry_info["type"],
                )
            )
        for att_info in rec_info.get("attachments", []):
            record.attachments.append(
                RecordAttachment(
                    attachment_id=att_info["attachment_id"],
                    record_id=rec_info["record_id"],
                    filename=att_info["filename"],
                    stored_path=att_info.get("stored_path", ""),
                    uploaded_dt=datetime_from_iso(att_info["uploaded_dt"]),
                    note=att_info.get("note", ""),
                )
            )
        ctx.records.add(record)
    for acct_info in data.get("billing", []):
        account = BillingAccount(
            acct_id=acct_info["acct_id"],
            patient_id=acct_info["patient_id"],
            charges=[],
            payments=[],
        )
        for charge_info in acct_info.get("charges", []):
            account.charges.append(
                Charge(
                    code=charge_info["code"],
                    amount=charge_info["amount"],
                    dt=datetime_from_iso(charge_info["dt"]),
                    description=charge_info.get("description", ""),
                )
            )
        for payment_info in acct_info.get("payments", []):
            account.payments.append(
                Payment(
                    method=payment_info["method"],
                    amount=payment_info["amount"],
                    dt=datetime_from_iso(payment_info["dt"]),
                    reference=payment_info.get("reference", ""),
                )
            )
        ctx.billing.add(account)
    for bed_info in data.get("beds", []):
        ctx.beds.add(
            Bed(
                bed_id=bed_info["bed_id"],
                room_id=bed_info["room_id"],
                status=bed_info.get("status", "free"),
                occupant_patient_id=bed_info.get("occupant_patient_id"),
            )
        )
    ctx.audit.reset()
    for ev in data.get("audit", []):
        event = AuditEvent.for_action(
            ev["who"],
            ev["what"],
            when=datetime_from_iso(ev["when"]),
            before=ev.get("before"),
            after=ev.get("after"),
        )
        logged = ctx.audit.log(event)
        expected_prev = ev.get("prev_hash")
        expected_hash = ev.get("event_hash")
        if expected_prev and logged.prev_hash != expected_prev:
            raise ValidationError("Audit log chain mismatch detected while loading data.")
        if expected_hash and logged.event_hash != expected_hash:
            raise ValidationError("Audit log hash mismatch detected while loading data.")
    return ctx

def save_context_to_file(ctx: SystemContext, path: str) -> None:
    payload = context_to_dict(ctx)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)

def load_context_from_file(path: str) -> SystemContext:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return context_from_dict(data)

def run_smoke_tests() -> Dict[str, Any]:
    """Execute lightweight integration checks across auth, scheduling, billing, and audit."""
    ctx = SystemContext.create_default()
    results: Dict[str, Any] = {}

    auth_outcome = ctx.auth.authenticate("admin", "admin123")
    results["auth_success"] = bool(auth_outcome)
    admin_user = ctx.users["admin"]
    if auth_outcome:
        admin_user = auth_outcome[0]

    dept = Department(dept_id=str(uuid.uuid4()), name="Testing", location="Virtual Lab")
    ctx.depts.add(dept)
    doctor = Doctor(
        id=str(uuid.uuid4()),
        name="Integration Doctor",
        dob=datetime(1985, 1, 1, tzinfo=UTC),
        sex="U",
        contact_info={},
        specialty="General Medicine",
        department_id=dept.dept_id,
        license_no="TEST-001",
        timezone="UTC",
    )
    ctx.doctors.add(doctor)
    patient = Patient(
        id=str(uuid.uuid4()),
        name="Integration Patient",
        dob=datetime(1990, 6, 1, tzinfo=UTC),
        sex="U",
        contact_info={},
        primary_doctor_id=doctor.doctor_id,
    )
    ctx.patients.add(patient)

    base_start = datetime.now(UTC) + timedelta(hours=1)
    base_end = base_start + timedelta(minutes=30)
    ctx.appt_svc.book(admin_user, patient.patient_id, doctor.doctor_id, dept.dept_id, base_start, base_end, "Baseline visit")

    try:
        ctx.appt_svc.book(
            admin_user,
            patient.patient_id,
            doctor.doctor_id,
            dept.dept_id,
            base_start + timedelta(minutes=25),
            base_end + timedelta(minutes=25),
            "Overlap attempt",
        )
        results["hard_policy_blocks_overlap"] = False
    except SchedulingConflictError:
        results["hard_policy_blocks_overlap"] = True

    ctx.appt_svc.set_conflict_policy(AllowBufferPolicy(15))
    try:
        ctx.appt_svc.book(
            admin_user,
            patient.patient_id,
            doctor.doctor_id,
            dept.dept_id,
            base_end,
            base_end + timedelta(minutes=30),
            "Buffer conflict",
        )
        results["buffer_policy_enforced"] = False
    except SchedulingConflictError:
        results["buffer_policy_enforced"] = True

    buffered_start = base_end + timedelta(minutes=15)
    buffered_end = buffered_start + timedelta(minutes=30)
    buffered_appt = ctx.appt_svc.book(
        admin_user,
        patient.patient_id,
        doctor.doctor_id,
        dept.dept_id,
        buffered_start,
        buffered_end,
        "Buffered follow-up",
    )
    results["buffer_policy_allows_gap"] = buffered_appt is not None

    provider = InsuranceProvider(provider_id="test_ins", name="Test Insurance", country="US")
    ctx.providers.add(provider)
    policy = InsurancePolicy(
        policy_id=str(uuid.uuid4()),
        provider=provider,
        plan="Integration Plan",
        member_no="TEST-PLAN-1",
        copay_percent=0.25,
    )
    ctx.policies.add(policy)
    insured_patient = Patient(
        id=str(uuid.uuid4()),
        name="Insured Patient",
        dob=datetime(1988, 7, 7, tzinfo=UTC),
        sex="U",
        contact_info={},
        primary_doctor_id=doctor.doctor_id,
        insurance=policy,
    )
    ctx.patients.add(insured_patient)

    self_pay_charge = ctx.bill_svc.invoice(admin_user, patient.patient_id, code="T1000", amount=100.0, description="Self pay checkup")
    insured_charge = ctx.bill_svc.invoice(admin_user, insured_patient.patient_id, code="T2000", amount=200.0, description="Insured checkup")
    results["billing_self_pay_amount"] = self_pay_charge.amount
    results["billing_insured_amount"] = insured_charge.amount

    results["audit_chain_valid"] = ctx.audit.verify_chain()
    results["audit_event_count"] = len(ctx.audit.events)
    return results

def run_demo() -> str:
    ctx = initialize_system()
    patients = ctx.patients
    doctors = ctx.doctors
    depts = ctx.depts
    billing = ctx.billing
    beds = ctx.beds
    records = ctx.records
    providers = ctx.providers
    policies = ctx.policies
    appt_svc = ctx.appt_svc
    rec_svc = ctx.rec_svc
    bill_svc = ctx.bill_svc
    ip_svc = ctx.ip_svc
    audit = ctx.audit
    admin = ctx.users["admin"]
    clerk = ctx.users["clerk"]
    nurse = ctx.users["nurse"]
    doctor_user = ctx.users["doctor"]
    for username, password in (
        ("admin", "admin123"),
        ("clerk", "clerk123"),
        ("nurse", "nurse123"),
        ("doctor", "doctor123"),
    ):
        ctx.auth.authenticate(username, password)

    cardio = Department(dept_id=str(uuid.uuid4()), name="Cardiology", location="SF Campus")
    depts.add(cardio)
    beds.add(Bed(bed_id="BED-101", room_id="RM-10"))
    beds.add(Bed(bed_id="BED-102", room_id="RM-10"))

    doc = Doctor(
        id=str(uuid.uuid4()),
        name="Dr. Ada Lovelace",
        dob=datetime(1980, 5, 17, tzinfo=UTC),
        sex="F",
        contact_info={"email": "ada@clinic.example"},
        specialty="Cardiology",
        department_id=cardio.dept_id,
        license_no="CA-12345",
        timezone="America/Los_Angeles",
    )
    doctors.add(doc)

    provider = providers.get("us_blueshield_ca")
    policy = InsurancePolicy(policy_id=str(uuid.uuid4()), provider=provider, plan="PPO Gold", member_no="BSCA-0001", copay_percent=0.1)
    policies.add(policy)

    pat = Patient(
        id=str(uuid.uuid4()),
        name="John Doe",
        dob=datetime(1990, 2, 2, tzinfo=UTC),
        sex="M",
        contact_info={"email": "john@example.com"},
        primary_doctor_id=doc.doctor_id,
        insurance=policy,
        allergies=["Penicillin"],
    )
    patients.add(pat)

    doc_tz = get_timezone(doc.timezone)
    now_pt = datetime.now(doc_tz)
    avail = TimeBlock(now_pt + timedelta(hours=1), now_pt + timedelta(hours=5), "Clinic hours", "availability")
    doc.schedule.add_block(avail)
    doctors.update(doc)

    # Book appointment using AST times to test timezone conversion
    halifax_tz = get_timezone("America/Halifax")
    start_ast = (now_pt + timedelta(hours=2)).astimezone(halifax_tz)
    end_ast = (now_pt + timedelta(hours=3)).astimezone(halifax_tz)
    appt = appt_svc.book(clerk, pat.patient_id, doc.doctor_id, cardio.dept_id, start_ast, end_ast, "Chest pain evaluation")

    appt_svc.complete(doctor_user, appt.appt_id)
    _ = rec_svc.append_entry(doctor_user, pat.patient_id, "visit", "ECG normal. Follow-up in 2 weeks.", author_id=doc.doctor_id)

    bill_svc.invoice(admin, pat.patient_id, code="99213", amount=150.0, description="Office visit")
    bill_svc.post_payment(admin, pat.patient_id, method="insurance", amount=135.0, reference="CLAIM-123")

    # Admission scheduled to start one hour after appointment end
    admission_start_ast = end_ast + timedelta(hours=1)
    bed_primary = ip_svc.admit(nurse, pat.patient_id, doc.doctor_id, hours=12, start_dt=admission_start_ast)
    ip_svc.discharge(nurse, bed_primary.bed_id)

    doc_east = Doctor(
        id=str(uuid.uuid4()),
        name="Dr. Grace Hopper",
        dob=datetime(1985, 8, 22, tzinfo=UTC),
        sex="F",
        contact_info={"email": "grace@clinic.example"},
        specialty="Neurology",
        department_id=cardio.dept_id,
        license_no="NS-54321",
        timezone="America/Halifax",
    )
    doctors.add(doc_east)

    provider_ca = providers.get("ca_bluecross_ns")
    policy_ca = InsurancePolicy(policy_id=str(uuid.uuid4()), provider=provider_ca, plan="Atlantic Wellness", member_no="BCNS-9001", copay_percent=0.15)
    policies.add(policy_ca)

    pat_ca = Patient(
        id=str(uuid.uuid4()),
        name="Alice Smith",
        dob=datetime(1992, 11, 12, tzinfo=halifax_tz),
        sex="F",
        contact_info={"email": "alice@example.ca"},
        primary_doctor_id=doc_east.doctor_id,
        insurance=policy_ca,
        allergies=["Latex"],
    )
    patients.add(pat_ca)

    east_now = datetime.now(halifax_tz)
    east_avail = TimeBlock(east_now + timedelta(hours=1), east_now + timedelta(hours=6), "Clinic hours East", "availability")
    doc_east.schedule.add_block(east_avail)
    doctors.update(doc_east)

    tele_start_halifax = east_now + timedelta(hours=2)
    tele_end_halifax = tele_start_halifax + timedelta(minutes=45)
    tele_start_utc = tele_start_halifax.astimezone(UTC)
    tele_end_utc = tele_end_halifax.astimezone(UTC)
    tele_appt = appt_svc.book(clerk, pat_ca.patient_id, doc_east.doctor_id, cardio.dept_id, tele_start_utc, tele_end_utc, "Telehealth rehab consult")

    appt_svc.complete(doctor_user, tele_appt.appt_id)
    _ = rec_svc.append_entry(doctor_user, pat_ca.patient_id, "diagnosis", "Remote rehab plan updated.", author_id=doc_east.doctor_id)

    bill_svc.invoice(admin, pat_ca.patient_id, code="Q0506", amount=200.0, description="Telehealth consult")
    bill_svc.post_payment(admin, pat_ca.patient_id, method="card", amount=60.0, reference="RCPT-445")

    bed_secondary = ip_svc.admit(nurse, pat_ca.patient_id, doc_east.doctor_id, hours=8, start_dt=tele_end_utc + timedelta(hours=1))

    conflict_note = ""
    try:
        conflict_start = tele_start_halifax + timedelta(minutes=30)
        conflict_end = conflict_start + timedelta(minutes=45)
        conflict_start_utc = conflict_start.astimezone(UTC)
        conflict_end_utc = conflict_end.astimezone(UTC)
        appt_svc.book(clerk, pat.patient_id, doc_east.doctor_id, cardio.dept_id, conflict_start_utc, conflict_end_utc, "Attempted overlap")
    except SchedulingConflictError as exc:
        conflict_note = f"Double-booking prevented for {doc_east.name}: {exc}"

    rec_primary = records.find(patient_id=pat.patient_id)[0]
    rec_secondary = records.find(patient_id=pat_ca.patient_id)[0]
    acct_primary = billing.find(patient_id=pat.patient_id)[0]
    acct_secondary = billing.find(patient_id=pat_ca.patient_id)[0]
    bed_primary_view = beds.get(bed_primary.bed_id)
    bed_secondary_view = beds.get(bed_secondary.bed_id)

    audit_counts: Dict[str, int] = {}
    for ev in audit.events:
        audit_counts[ev.what] = audit_counts.get(ev.what, 0) + 1
    audit_breakdown = ", ".join(f"{k}={v}" for k, v in sorted(audit_counts.items()))

    sections: List[str] = []
    sections.append(
        format_section(
            "Appointments",
            [
                f"{pat.name}'s visit ({doc.timezone}): {appt.start_dt.astimezone(doc_tz).strftime('%Y-%m-%d %H:%M %Z')} - {appt.end_dt.astimezone(doc_tz).strftime('%H:%M %Z')} [{appt.status}]",
                f"{pat_ca.name}'s telehealth ({doc_east.timezone}): {tele_appt.start_dt.astimezone(halifax_tz).strftime('%Y-%m-%d %H:%M %Z')} - {tele_appt.end_dt.astimezone(halifax_tz).strftime('%H:%M %Z')} [{tele_appt.status}]",
            ],
        )
    )
    reminders_primary = sum(1 for entry in rec_primary.entries if entry.type == "reminder")
    reminders_secondary = sum(1 for entry in rec_secondary.entries if entry.type == "reminder")
    sections.append(
        format_section(
            "Medical Records",
            [
                f"{pat.name}: {len(rec_primary.entries)} entries (latest {rec_primary.entries[-1].type}), attachments {len(rec_primary.attachments)}, reminders {reminders_primary}",
                f"{pat_ca.name}: {len(rec_secondary.entries)} entries (latest {rec_secondary.entries[-1].type}), attachments {len(rec_secondary.attachments)}, reminders {reminders_secondary}",
            ],
        )
    )
    sections.append(
        format_section(
            "Billing Accounts",
            [
                f"{pat.name}: balance ${acct_primary.balance()} from {len(acct_primary.charges)} charge(s) / {len(acct_primary.payments)} payment(s)",
                f"{pat_ca.name}: balance ${acct_secondary.balance()} from {len(acct_secondary.charges)} charge(s) / {len(acct_secondary.payments)} payment(s)",
            ],
        )
    )
    sections.append(
        format_section(
            "Inpatient Beds",
            [
                f"{bed_primary_view.bed_id}: status={bed_primary_view.status}",
                f"{bed_secondary_view.bed_id}: status={bed_secondary_view.status}, occupant={bed_secondary_view.occupant_patient_id}",
            ],
        )
    )
    audit_lines = [f"events recorded: {len(audit.events)}"]
    if audit_breakdown:
        audit_lines.append(f"by action: {audit_breakdown}")
    sections.append(format_section("Audit Trail", audit_lines))
    if conflict_note:
        sections.append(format_section("Conflict Handling", [conflict_note]))

    return "\n\n".join(sections)

def prompt_input(message: str, *, required: bool=False, default: Optional[str]=None) -> str:
    suffix = ""
    if default is not None:
        suffix = f" [{default}]"
    prompt_msg = f"{message}{suffix}: "
    while True:
        value = input(prompt_msg).strip()
        if not value and default is not None:
            return default
        if value or not required:
            return value
        print("A value is required. Please try again.")

def prompt_password(message: str) -> str:
    while True:
        if getpass:
            value = getpass(f"{message}: ")
        else:
            value = input(f"{message}: ")
        value = value.strip()
        if value:
            return value
        print("Password cannot be empty. Please try again.")

def prompt_new_password() -> str:
    while True:
        pwd = prompt_password("New password")
        confirm = prompt_password("Confirm password")
        if pwd != confirm:
            print("Passwords do not match. Try again.")
            continue
        if len(pwd) < 4:
            print("Password must be at least 4 characters.")
            continue
        return pwd

def prompt_date(message: str) -> datetime:
    while True:
        raw = prompt_input(message, required=True)
        try:
            parsed = datetime.strptime(raw, "%Y-%m-%d")
            return parsed.replace(tzinfo=UTC)
        except ValueError:
            print("Use YYYY-MM-DD (e.g., 1980-05-17).")

def prompt_datetime_local(message: str, tzinfo) -> datetime:
    while True:
        raw = prompt_input(message, required=True)
        try:
            parsed = datetime.strptime(raw, "%Y-%m-%d %H:%M")
            return parsed.replace(tzinfo=tzinfo)
        except ValueError:
            print("Use YYYY-MM-DD HH:MM (e.g., 2025-10-12 09:30).")

def register_physician(ctx: SystemContext, existing_user: Optional[User]=None) -> Tuple[Doctor, User]:
    print("Welcome! Let's set up your physician profile.\n")
    name = prompt_input("Physician name", required=True)
    dob = prompt_date("Date of birth (YYYY-MM-DD)")
    sex = prompt_input("Sex (M/F/X)", default="U").upper() or "U"
    email = prompt_input("Email address", default="")
    specialty = prompt_input("Specialty", default="Family Medicine")
    license_no = prompt_input("License number", default="N/A")

    print("\nSelect preferred timezone:")
    for idx, (label, value) in enumerate(TIMEZONE_CHOICES, start=1):
        print(f"{idx}. {label} ({value})")
    while True:
        tz_choice = prompt_input("Timezone number", default="1")
        if tz_choice.isdigit():
            pos = int(tz_choice)
            if 1 <= pos <= len(TIMEZONE_CHOICES):
                tz_name = TIMEZONE_CHOICES[pos - 1][1]
                break
        print("Please choose a valid option.")

    dept_name = prompt_input("Department name", default="General Practice")
    dept_location = prompt_input("Department location", default="Virtual Clinic")
    username = None
    password = None
    existing = existing_user
    if existing is None:
        while True:
            candidate = prompt_input("Choose a login name", required=True)
            if candidate in ctx.users:
                print("That username is already taken.")
                continue
            username = candidate
            break
        password = prompt_new_password()
    else:
        username = existing.user_id
    doctor, user = create_physician(
        ctx,
        name=name,
        dob=dob,
        sex=sex,
        email=email,
        specialty=specialty,
        license_no=license_no,
        timezone_name=tz_name,
        department_name=dept_name,
        department_location=dept_location,
        username=username,
        password=password,
        existing_user=existing,
    )

    print(f"\nGreat! Dr. {doctor.name} is ready. Your doctor id is {doctor.doctor_id}.\n")
    return doctor, user

def register_patient(ctx: SystemContext, doctor: Doctor) -> None:
    print("\n--- Register a new patient ---")
    name = prompt_input("Patient name", required=True)
    dob = prompt_date("Date of birth (YYYY-MM-DD)")
    sex = prompt_input("Sex (M/F/X)", default="U").upper() or "U"
    email = prompt_input("Email address", default="")
    allergies_raw = prompt_input("Allergies (comma separated)", default="")
    allergies = [a.strip() for a in allergies_raw.split(",") if a.strip()]
    wants_insurance = prompt_input("Does the patient have insurance? (y/n)", default="y").lower()
    if wants_insurance.startswith("y"):
        providers = ctx.providers.all()
        if not providers:
            print("No insurance providers configured. Skipping insurance capture.\n")
            insurance_provider = None
            plan_name = ""
            member_no = ""
            copay_val = 0.2
        else:
            print("\nChoose an insurance provider:")
            for idx, provider in enumerate(providers, start=1):
                print(f"{idx}. {provider.name} ({provider.country})")
            provider_choice: Optional[InsuranceProvider] = None
            while True:
                selection = prompt_input("Provider number", required=True)
                if not selection.isdigit():
                    print("Enter a number from the list.")
                    continue
                position = int(selection)
                if 1 <= position <= len(providers):
                    provider_choice = providers[position - 1]
                    break
                print("Choice out of range.")
            if provider_choice:
                plan_name = prompt_input("Plan name", default="Standard")
                member_no = prompt_input("Member number", required=True)
                while True:
                    copay_raw = prompt_input("Copay percent (0.0-1.0)", default="0.2")
                    try:
                        copay_val = float(copay_raw)
                        if not 0 <= copay_val <= 1:
                            raise ValueError("Copay must be between 0 and 1.")
                        break
                    except ValueError as exc:
                        print(f"Invalid value: {exc}")
                insurance_provider = provider_choice.provider_id
                print(f"Insurance recorded with provider {provider_choice.name}.\n")
            else:
                insurance_provider = None
                plan_name = ""
                member_no = ""
                copay_val = 0.2
    else:
        insurance_provider = None
        plan_name = ""
        member_no = ""
        copay_val = 0.2

    patient = create_patient(
        ctx,
        doctor,
        name=name,
        dob=dob,
        sex=sex,
        email=email,
        allergies=allergies,
        insurance_provider_id=insurance_provider,
        insurance_plan=plan_name,
        insurance_member_no=member_no,
        insurance_copay=copay_val,
    )
    print(f"Patient registered with id {patient.patient_id}.\n")

def add_availability(ctx: SystemContext, doctor: Doctor) -> None:
    print("\n--- Add availability ---")
    tz = get_timezone(doctor.timezone)
    start = prompt_datetime_local("Start (YYYY-MM-DD HH:MM)", tz)
    duration_minutes = int(prompt_input("Duration in minutes", required=True))
    end = start + timedelta(minutes=duration_minutes)
    label = prompt_input("Label", default="Clinic availability")

    block = TimeBlock(start, end, label, "availability")
    doctor.schedule.add_block(block)
    ctx.doctors.update(doctor)
    print(f"Availability added from {start.strftime('%Y-%m-%d %H:%M %Z')} to {end.strftime('%H:%M %Z')}.\n")

def select_patient(ctx: SystemContext, doctor: Doctor) -> Optional[Patient]:
    patients = ctx.patients.find(primary_doctor_id=doctor.doctor_id)
    if not patients:
        print("You have no patients yet. Register one first.\n")
        return None
    print("\nChoose a patient:")
    for idx, pat in enumerate(patients, start=1):
        print(f"{idx}. {pat.name} (ID: {pat.patient_id[:8]}...) DOB {pat.dob.date()}")
    while True:
        raw = prompt_input("Enter number", required=True)
        if not raw.isdigit():
            print("Enter a number from the list.")
            continue
        index = int(raw)
        if 1 <= index <= len(patients):
            return patients[index - 1]
        print("Choice out of range.")

def schedule_appointment(ctx: SystemContext, doctor: Doctor, user: User) -> None:
    patient = select_patient(ctx, doctor)
    if not patient:
        return
    tz = get_timezone(doctor.timezone)
    print(f"\nScheduling for {patient.name}. Times are interpreted in {doctor.timezone}.")
    start = prompt_datetime_local("Appointment start (YYYY-MM-DD HH:MM)", tz)
    duration_min = int(prompt_input("Duration in minutes", required=True))
    end = start + timedelta(minutes=duration_min)
    reason = prompt_input("Reason for visit", default="Follow-up")
    try:
        appt = ctx.appt_svc.book(user, patient.patient_id, doctor.doctor_id, doctor.department_id or "", start, end, reason)
    except (SchedulingConflictError, TimezoneError, ValidationError) as exc:
        print(f"Could not schedule appointment: {exc}\n")
        return
    print(f"Appointment booked with id {appt.appt_id}. Status: {appt.status}.\n")

def record_note(ctx: SystemContext, doctor: Doctor, user: User) -> None:
    patient = select_patient(ctx, doctor)
    if not patient:
        return
    entry_type = prompt_input("Entry type (visit/diagnosis/prescription/etc.)", default="visit")
    notes = prompt_input("Notes", required=True)
    entry = ctx.rec_svc.append_entry(user, patient.patient_id, entry_type, notes, author_id=doctor.doctor_id)
    print(f"Record entry saved with id {entry.entry_id}.\n")

def change_own_password(user: User, auth: AuthService) -> None:
    print("\n--- Change Password ---")
    current = prompt_password("Current password")
    if not auth.verify_password(user, current):
        print("Incorrect password. No changes made.\n")
        return
    new_password = prompt_new_password()
    if not auth.change_password(user, current, new_password):
        print("Incorrect password. No changes made.\n")
        return
    # Issue a fresh session token so the caller remains authenticated.
    auth.authenticate(user.user_id, new_password)
    print("Password updated.\n")

def reset_user_password(ctx: SystemContext, actor: User) -> None:
    if "admin" not in actor.roles:
        print("Only admins can reset other users' passwords.\n")
        return
    print("\n--- Reset User Password ---")
    usernames = sorted(ctx.users.keys())
    for idx, name in enumerate(usernames, start=1):
        print(f"{idx}. {name}")
    while True:
        choice = prompt_input("Select user", required=True)
        if not choice.isdigit():
            print("Enter a number from the list.")
            continue
        index = int(choice)
        if 1 <= index <= len(usernames):
            target_name = usernames[index - 1]
            break
        print("Choice out of range.")
    target = ctx.users[target_name]
    if target.user_id == actor.user_id:
        print("Use the regular password change option for your own account.\n")
        return
    new_pwd = prompt_new_password()
    ctx.auth.reset_password(target, new_pwd)
    print(f"Password for {target.user_id} has been reset.\n")

def ensure_doctor_profile(ctx: SystemContext, user: User) -> Optional[Doctor]:
    if user.person_id:
        try:
            return ctx.doctors.get(user.person_id)
        except NotFoundError:
            pass
    print("\nNo physician profile is linked to this account.")
    choice = prompt_input("Create one now? (y/n)", default="y").lower()
    if choice.startswith("y"):
        doctor, _ = register_physician(ctx, existing_user=user)
        return doctor
    print("Returning to main menu.\n")
    return None

def build_physician_summary(ctx: SystemContext, doctor: Doctor) -> str:
    patients = ctx.patients.find(primary_doctor_id=doctor.doctor_id)
    patient_lines = [
        f"{pat.name} (age {pat.age()}, allergies: {', '.join(pat.allergies) if pat.allergies else 'none'}, insurance: {pat.insurance.provider.name if pat.insurance else 'self-pay'})"
        for pat in patients
    ] or ["No patients yet."]

    tz = get_timezone(doctor.timezone)
    appts = sorted(
        [a for a in ctx.appts.all() if a.doctor_id == doctor.doctor_id],
        key=lambda a: a.start_dt,
    )
    appt_lines = [
        f"{ctx.patients.get(a.patient_id).name}: {a.start_dt.astimezone(tz).strftime('%Y-%m-%d %H:%M %Z')} ({a.status})"
        for a in appts
    ] or ["No appointments scheduled."]

    record_lines = []
    for pat in patients:
        matches = ctx.records.find(patient_id=pat.patient_id)
        if matches:
            record = matches[0]
            entry_count = len(record.entries)
            attachment_count = len(record.attachments)
            reminder_count = sum(1 for entry in record.entries if entry.type == "reminder")
            if entry_count:
                latest = record.entries[-1]
                record_lines.append(
                    f"{pat.name}: {entry_count} entry(ies) (latest {latest.type}), attachments {attachment_count}, reminders {reminder_count}"
                )
            else:
                record_lines.append(f"{pat.name}: no entries yet, attachments {attachment_count}, reminders {reminder_count}")
        else:
            record_lines.append(f"{pat.name}: no records yet")

    billing_lines = []
    for pat in patients:
        accts = ctx.billing.find(patient_id=pat.patient_id)
        if accts:
            acct = accts[0]
            billing_lines.append(
                f"{pat.name}: balance ${acct.balance()} (charges: {len(acct.charges)}, payments: {len(acct.payments)})"
            )
        else:
            billing_lines.append(f"{pat.name}: no billing activity")

    audit_recent = ctx.audit.events[-5:]
    audit_lines = [
        f"{ev.when.astimezone(tz).strftime('%m-%d %H:%M')}: {ev.what}"
        for ev in audit_recent
    ] or ["No audit events recorded."]

    sections = [
        format_section("Patients", patient_lines),
        format_section("Appointments", appt_lines),
        format_section("Medical Records", record_lines),
        format_section("Billing", billing_lines),
        format_section("Recent Activity", audit_lines),
    ]
    return "\n\n".join(sections)

def physician_loop(ctx: SystemContext, doctor: Doctor, user: User) -> None:
    menu = (
        "\nPhysician workspace - select an option:\n"
        "1. Register new patient\n"
        "2. Add availability\n"
        "3. Schedule appointment\n"
        "4. Record visit note\n"
        "5. View summary\n"
        "6. Change password\n"
        "Q. Log out\n"
    )
    while True:
        try:
            doctor = ctx.doctors.get(doctor.doctor_id)
        except NotFoundError:
            print("Doctor profile missing; logging out.")
            return
        print(menu)
        choice = prompt_input("Choice", required=True).lower()
        if choice in ("q", "quit", "exit"):
            print("Logging out of physician workspace.\n")
            break
        actions = {
            "1": lambda: register_patient(ctx, doctor),
            "2": lambda: add_availability(ctx, doctor),
            "3": lambda: schedule_appointment(ctx, doctor, user),
            "4": lambda: record_note(ctx, doctor, user),
            "5": lambda: print("\n" + build_physician_summary(ctx, doctor) + "\n"),
            "6": lambda: change_own_password(user, ctx.auth),
        }
        action = actions.get(choice)
        if not action:
            print("Please choose a valid option.")
            continue
        try:
            action()
        except AuthorizationError as exc:
            print(f"Action not permitted: {exc}")
        except Exception as exc:
            print(f"An unexpected error occurred: {exc}")

def login_user(ctx: SystemContext) -> Optional[User]:
    print("\n--- Staff login ---")
    for attempt in range(3):
        username = prompt_input("Username", required=True)
        password = prompt_password("Password")
        auth_result = ctx.auth.authenticate(username, password)
        if auth_result:
            user, _token = auth_result
            print(f"\nWelcome, {username}. Roles: {', '.join(user.roles)}.\n")
            return user
        print("Invalid username or password.\n")
    print("Too many failed attempts. Returning to main menu.\n")
    return None

def handle_user_session(ctx: SystemContext, user: User) -> None:
    handled = False
    if "doctor" in user.roles:
        doctor = ensure_doctor_profile(ctx, user)
        if doctor:
            physician_loop(ctx, doctor, user)
            handled = True
    other_roles = [r for r in user.roles if r != "doctor"]
    if not other_roles:
        return
    staff_menu(ctx, user, handled)

def staff_menu(ctx: SystemContext, user: User, prelude_shown: bool) -> None:
    if not prelude_shown:
        print(f"\nLogged in as {user.user_id}. Roles: {', '.join(user.roles)}.\n")
    menu_lines = [
        "1. Change password",
    ]
    actions: Dict[str, Any] = {
        "1": lambda: change_own_password(user, ctx.auth),
    }
    if "admin" in user.roles:
        menu_lines.append("2. Reset another user's password")
        actions["2"] = lambda: reset_user_password(ctx, user)
    menu_lines.append("Q. Log out")
    menu = "\nStaff tools - choose an option:\n" + "\n".join(menu_lines) + "\n"
    while True:
        print(menu)
        choice = prompt_input("Choice", required=True).lower()
        if choice in ("q", "quit", "exit"):
            print("Logging out of staff tools.\n")
            break
        action = actions.get(choice)
        if not action:
            print("Please choose a valid option.")
            continue
        action()

class HospitalGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Hospital Management System")
        self.geometry("780x560")
        self.ctx = initialize_system()
        self.current_user: Optional[User] = None
        self.style = ttk.Style(self)
        self.base_theme = self.style.theme_use()
        self.high_contrast_var = tk.BooleanVar(value=False)
        self.font_size_offset = 0
        self._base_fonts: Dict[str, int] = {}
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkFixedFont"):
            try:
                self._base_fonts[name] = tkfont.nametofont(name).cget("size")
            except tk.TclError:
                pass
        self.container = ttk.Frame(self, padding=20)
        self.container.pack(fill="both", expand=True)
        for i in range(2):
            self.container.columnconfigure(i, weight=1)
        self.summary_text: Optional[tk.Text] = None
        self.nurse_bed_text: Optional[tk.Text] = None
        self.configure_menu()
        self.bind_shortcuts()
        self.show_start()
        self.configure(bg="#203040")

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#203040")
        style.configure("TLabel", background="#203040", foreground="#f0f4ff", font=("Segoe UI", 11)),
        style.configure("Accent.TButton", background="#3a7db8", foreground="white", padding=0,)
        style.map("Accent.TButton", background=[("active", "#4895d9"), ("pressed", "#2c5f92")],)

    # ---------- Utility ----------
    def configure_menu(self) -> None:
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="New Session", command=self.reset_context)
        file_menu.add_command(label="Load...", command=self.load_context_dialog)
        file_menu.add_command(label="Save...", command=self.save_context_dialog)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.destroy)
        menubar.add_cascade(label="File", menu=file_menu)
        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(label="Increase Font Size", command=self.increase_font_event, accelerator="Ctrl++")
        view_menu.add_command(label="Decrease Font Size", command=self.decrease_font_event, accelerator="Ctrl+-")
        view_menu.add_command(label="Reset Font Size", command=self.reset_font_event, accelerator="Ctrl+0")
        view_menu.add_separator()
        view_menu.add_checkbutton(
            label="High Contrast Mode",
            variable=self.high_contrast_var,
            command=self.on_high_contrast_menu,
            accelerator="Ctrl+Shift+H",
        )
        menubar.add_cascade(label="View", menu=view_menu)
        self.config(menu=menubar)
        self.menubar = menubar

    def bind_shortcuts(self) -> None:
        self.bind_all("<Control-s>", self.save_shortcut)
        self.bind_all("<Control-o>", self.load_shortcut)
        self.bind_all("<Control-n>", self.new_session_shortcut)
        self.bind_all("<Control-plus>", self.increase_font_event)
        self.bind_all("<Control-KP_Add>", self.increase_font_event)
        self.bind_all("<Control-minus>", self.decrease_font_event)
        self.bind_all("<Control-KP_Subtract>", self.decrease_font_event)
        self.bind_all("<Control-0>", self.reset_font_event)
        self.bind_all("<Control-Shift-H>", self.toggle_high_contrast_event)

    def save_shortcut(self, event=None):
        self.save_context_dialog()
        return "break"

    def load_shortcut(self, event=None):
        self.load_context_dialog()
        return "break"

    def new_session_shortcut(self, event=None):
        self.reset_context()
        return "break"

    def increase_font_event(self, event=None):
        self.adjust_font_size(1)
        return "break"

    def decrease_font_event(self, event=None):
        self.adjust_font_size(-1)
        return "break"

    def reset_font_event(self, event=None):
        self.reset_font_size()
        return "break"

    def adjust_font_size(self, delta: int) -> None:
        new_offset = max(-4, min(6, self.font_size_offset + delta))
        if new_offset == self.font_size_offset:
            return
        self.font_size_offset = new_offset
        self._apply_font_offset()

    def reset_font_size(self) -> None:
        self.font_size_offset = 0
        self._apply_font_offset()

    def _apply_font_offset(self) -> None:
        for name, base in self._base_fonts.items():
            try:
                tkfont.nametofont(name).configure(size=base + self.font_size_offset)
            except tk.TclError:
                continue

    def on_high_contrast_menu(self) -> None:
        self.apply_high_contrast(self.high_contrast_var.get())

    def toggle_high_contrast_event(self, event=None):
        new_state = not self.high_contrast_var.get()
        self.high_contrast_var.set(new_state)
        self.apply_high_contrast(new_state)
        return "break"

    def apply_high_contrast(self, enabled: bool) -> None:
        if enabled:
            self.style.theme_use("clam")
            self.tk_setPalette(
                background="#1a1a1a",
                foreground="#f5f5f5",
                activeBackground="#333333",
                activeForeground="#ffffff",
                highlightColor="#f5f5f5",
                highlightBackground="#1a1a1a",
            )
            for style_name in ("TFrame", "TLabel", "TButton", "TNotebook", "TNotebook.Tab"):
                self.style.configure(style_name, background="#1a1a1a", foreground="#f5f5f5")
            self.style.configure("Treeview", background="#1a1a1a", fieldbackground="#1a1a1a", foreground="#f5f5f5")
            self.style.map("Treeview", background=[("selected", "#2f6fed")], foreground=[("selected", "#ffffff")])
            self.configure(bg="#1a1a1a")
            self._update_text_widget_palette("#1a1a1a", "#f5f5f5")
        else:
            self.tk_setPalette("")
            self.style.theme_use(self.base_theme)
            for style_name in ("TFrame", "TLabel", "TButton", "TNotebook", "TNotebook.Tab", "Treeview"):
                self.style.configure(style_name, background="", foreground="")
            self.style.map("Treeview", background=[], foreground=[])
            self.configure(bg="")
            self._update_text_widget_palette("white", "black")
        self._apply_font_offset()

    def _update_text_widget_palette(self, bg: str, fg: str) -> None:
        widgets = [self.summary_text, getattr(self, "nurse_bed_text", None)]
        for widget in widgets:
            if widget:
                try:
                    widget.configure(bg=bg, fg=fg, insertbackground=fg)
                except tk.TclError:
                    pass

    def reset_context(self) -> None:
        if not messagebox.askyesno("New Session", "Start a new session? Unsaved data will be lost.", parent=self):
            return
        self.ctx = initialize_system()
        self.current_user = None
        self.summary_text = None
        self.nurse_bed_text = None
        self.show_toast("System reset to defaults.")
        self.show_start()

    def load_context_dialog(self) -> None:
        path = filedialog.askopenfilename(
            title="Load Hospital Data",
            filetypes=[("Hospital data JSON", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            ctx = load_context_from_file(path)
        except Exception as exc:
            self.show_message("Load Failed", str(exc), error=True)
            return
        self.ctx = ctx
        self.current_user = None
        self.summary_text = None
        self.nurse_bed_text = None
        self.show_toast(f"Loaded {os.path.basename(path)}.")
        self.show_start()

    def save_context_dialog(self) -> None:
        if not self.current_user or not self.ctx.auth.validate_session(
            self.current_user.user_id, self.current_user.session_token or ""
        ):
            self.show_message("Sign In Required", "Sign in before saving hospital data.", error=True)
            return
        path = filedialog.asksaveasfilename(
            title="Save Hospital Data",
            defaultextension=".json",
            filetypes=[("Hospital data JSON", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            save_context_to_file(self.ctx, path)
        except Exception as exc:
            self.show_message("Save Failed", str(exc), error=True)
            return
        self.show_toast(f"Saved to {os.path.basename(path)}.")

    def prompt_save_new_account(self) -> None:
        if messagebox.askyesno(
            "Save New Account",
            "This account exists only in the current session until you save hospital data. "
            "Saved JSON is not encrypted; use synthetic data only. Save now?",
            parent=self,
        ):
            self.save_context_dialog()

    def clear_container(self) -> None:
        for child in self.container.winfo_children():
            child.destroy()

    def show_message(self, title: str, message: str, *, error: bool=False) -> None:
        if error:
            messagebox.showerror(title, message, parent=self)
        else:
            messagebox.showinfo(title, message, parent=self)

    def show_toast(self, message: str, duration: int=2500) -> None:
        toast = tk.Toplevel(self)
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        label = tk.Label(toast, text=message, bg="#333333", fg="white", padx=16, pady=8)
        label.pack()
        toast.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - toast.winfo_width()) // 2
        y = self.winfo_rooty() + self.winfo_height() - toast.winfo_height() - 40
        toast.geometry(f"+{x}+{y}")
        toast.after(duration, toast.destroy)

    def open_form(
        self,
        title: str,
        fields: List[Dict[str, Any]],
        on_submit: Callable[[Dict[str, Any]], bool],
    ) -> tk.Toplevel:
        win = tk.Toplevel(self)
        win.title(title)
        win.result = None  # type: ignore[attr-defined]
        frame = ttk.Frame(win, padding=12)
        frame.pack(fill="both", expand=True)
        entries: Dict[str, Dict[str, Any]] = {}
        for row, field in enumerate(fields):
            label = ttk.Label(frame, text=field["label"])
            label.grid(row=row, column=0, sticky="w", pady=4, padx=(0, 8))
            widget_type = field.get("widget", "entry")
            required = field.get("required", False)
            initial = field.get("initial", "")
            if widget_type == "combobox":
                choices = field.get("choices", [])
                choice_map = {label: value for label, value in choices}
                var = tk.StringVar(value=initial or (choices[0][0] if choices else ""))
                widget = ttk.Combobox(frame, textvariable=var, values=list(choice_map.keys()), state="readonly")
                widget.grid(row=row, column=1, sticky="ew", pady=4)
                entries[field["name"]] = {
                    "type": widget_type,
                    "widget": widget,
                    "var": var,
                    "choices": choice_map,
                    "required": required,
                }
            elif widget_type == "textarea":
                text_widget = tk.Text(frame, height=6, width=40)
                text_widget.grid(row=row, column=1, sticky="ew", pady=4)
                if initial:
                    text_widget.insert("1.0", initial)
                entries[field["name"]] = {
                    "type": widget_type,
                    "widget": text_widget,
                    "required": required,
                }
            elif widget_type == "label":
                label_widget = ttk.Label(frame, text=initial, anchor="w")
                label_widget.grid(row=row, column=1, sticky="ew", pady=4)
                entries[field["name"]] = {
                    "type": widget_type,
                    "widget": label_widget,
                    "value": initial,
                    "required": False,
                }
            else:
                var = tk.StringVar(value=initial)
                entry = ttk.Entry(frame, textvariable=var, show=field.get("show"))
                entry.grid(row=row, column=1, sticky="ew", pady=4)
                entries[field["name"]] = {
                    "type": widget_type,
                    "widget": entry,
                    "var": var,
                    "required": required,
                }
        frame.columnconfigure(1, weight=1)
        error_var = tk.StringVar()
        error_label = ttk.Label(frame, textvariable=error_var, foreground="#b22222")
        error_label.grid(row=len(fields), column=0, columnspan=2, sticky="w", pady=(6, 0))

        def submit():
            data: Dict[str, Any] = {}
            error_var.set("")
            for meta in entries.values():
                widget = meta["widget"]
                try:
                    widget.configure(foreground="")
                except tk.TclError:
                    pass
            for name, meta in entries.items():
                widget_type = meta["type"]
                required = meta["required"]
                if widget_type == "label":
                    raw = meta.get("value", "")
                elif widget_type == "textarea":
                    raw = meta["widget"].get("1.0", "end").strip()
                elif widget_type == "combobox":
                    raw_label = meta["var"].get().strip()
                    if required and not raw_label:
                        error_var.set("Please complete all required fields.")
                        try:
                            meta["widget"].configure(foreground="#b22222")
                        except tk.TclError:
                            pass
                        return
                    choices = meta["choices"]
                    if raw_label and raw_label not in choices:
                        error_var.set("Invalid selection.")
                        return
                    raw = choices.get(raw_label, "")
                else:
                    raw = meta["var"].get().strip()
                if required and not raw:
                    error_var.set("Please complete all required fields.")
                    try:
                        meta["widget"].configure(foreground="#b22222")
                    except tk.TclError:
                        pass
                    return
                data[name] = raw
            try:
                success = on_submit(data)
            except ValidationError as exc:
                error_var.set(str(exc))
                return
            except Exception as exc:
                messagebox.showerror(title, str(exc), parent=win)
                return
            if success:
                win.result = data  # type: ignore[attr-defined]
                win.destroy()
            else:
                error_var.set("Please review the highlighted fields.")

        button_bar = ttk.Frame(frame)
        button_bar.grid(row=len(fields)+1, column=0, columnspan=2, pady=(12, 0), sticky="e")
        ttk.Button(button_bar, text="Cancel", command=win.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(button_bar, text="Submit", command=submit).pack(side="right")
        win.transient(self)
        win.grab_set()
        fields_widgets = [meta["widget"] for meta in entries.values() if meta["type"] != "textarea"]
        if fields_widgets:
            fields_widgets[0].focus_set()
        return win

    def parse_date(self, value: str) -> datetime:
        try:
            return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            raise ValidationError("Use YYYY-MM-DD for dates.")

    def parse_datetime(self, value: str, tzname: str) -> datetime:
        try:
            dt = datetime.strptime(value, "%Y-%m-%d %H:%M")
        except ValueError as exc:
            raise ValidationError("Use YYYY-MM-DD HH:MM for date & time.") from exc
        tz = get_timezone(tzname)
        return dt.replace(tzinfo=tz)

    def get_current_doctor(self) -> Optional[Doctor]:
        if not self.current_user or not self.current_user.person_id:
            return None
        try:
            return self.ctx.doctors.get(self.current_user.person_id)
        except NotFoundError:
            return None

    def show_start(self) -> None:
        self.clear_container()
        ttk.Label(self.container, text="North American Hospital Management System", font=("Segoe UI", 18, "bold")).grid(row=0, column=0, columnspan=2, pady=(0, 20))
        ttk.Button(self.container, text="Staff Login", command=self.open_login).grid(row=1, column=0, sticky="ew", padx=10, pady=5)
        ttk.Button(self.container, text="Register New Physician", command=lambda: self.show_register_physician(None)).grid(row=1, column=1, sticky="ew", padx=10, pady=5)
        ttk.Button(self.container, text="Load Saved Data", command=self.load_context_dialog).grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=5)
        ttk.Label(self.container, text="New accounts are kept only for this session until you save hospital data.", wraplength=600).grid(row=3, column=0, columnspan=2, pady=10)

    # ---------- Authentication ----------
    def open_login(self) -> None:
        self.clear_container()
        ttk.Label(self.container, text="Staff Login", font=("Segoe UI", 16, "bold")).grid(row=0, column=0, columnspan=2, pady=(0, 20))
        ttk.Label(self.container, text="Username").grid(row=1, column=0, sticky="w")
        username_var = tk.StringVar()
        ttk.Entry(self.container, textvariable=username_var).grid(row=1, column=1, sticky="ew")
        ttk.Label(self.container, text="Password").grid(row=2, column=0, sticky="w", pady=(10, 0))
        password_var = tk.StringVar()
        ttk.Entry(self.container, textvariable=password_var, show="*").grid(row=2, column=1, sticky="ew", pady=(10, 0))

        def attempt_login():
            username = username_var.get().strip()
            password = password_var.get().strip()
            auth_result = self.ctx.auth.authenticate(username, password)
            if not auth_result:
                self.show_message("Login Failed", "Invalid username or password.", error=True)
                return
            user, _token = auth_result
            self.current_user = user
            if "doctor" in user.roles:
                doctor = self.get_current_doctor()
                if not doctor:
                    self.show_message("Welcome", "No physician profile found. Please create one.")
                    self.show_register_physician(user)
                    return
                self.show_doctor_dashboard(doctor)
            else:
                self.show_staff_view()

        button_bar = ttk.Frame(self.container)
        button_bar.grid(row=3, column=0, columnspan=2, pady=20, sticky="e")
        ttk.Button(button_bar, text="Back", command=self.show_start).pack(side="right", padx=(6, 0))
        ttk.Button(button_bar, text="Login", command=attempt_login).pack(side="right")

    def show_register_physician(self, existing_user: Optional[User]) -> None:
        self.clear_container()
        ttk.Label(self.container, text="Physician Registration", font=("Segoe UI", 16, "bold")).grid(row=0, column=0, columnspan=2, pady=(0, 20))

        def launch_form():
            tz_choices = TIMEZONE_CHOICES
            fields: List[Dict[str, Any]] = [
                {"name": "name", "label": "Name", "required": True},
                {"name": "dob", "label": "Date of Birth (YYYY-MM-DD)", "required": True},
                {"name": "sex", "label": "Sex (M/F/X)", "initial": "U"},
                {"name": "email", "label": "Email"},
                {"name": "specialty", "label": "Specialty", "initial": "Family Medicine"},
                {"name": "license", "label": "License Number", "initial": "N/A"},
                {"name": "timezone", "label": "Timezone", "widget": "combobox", "choices": tz_choices, "required": True},
                {"name": "dept", "label": "Department Name", "initial": "General Practice", "required": True},
                {"name": "dept_location", "label": "Department Location", "initial": "Virtual Clinic", "required": True},
            ]
            if existing_user is None:
                fields.extend([
                    {"name": "username", "label": "Desired Username", "required": True},
                    {"name": "password", "label": "Password", "widget": "entry", "show": "*", "required": True},
                    {"name": "confirm", "label": "Confirm Password", "widget": "entry", "show": "*", "required": True},
                ])
            def on_submit(values: Dict[str, Any]) -> bool:
                try:
                    dob = self.parse_date(values["dob"])
                except ValidationError as exc:
                    raise exc
                password = None
                username = None
                if existing_user is None:
                    if values["password"] != values["confirm"]:
                        raise ValidationError("Passwords do not match.")
                    password = values["password"]
                    username = values["username"]
                doctor, user = create_physician(
                    self.ctx,
                    name=values["name"],
                    dob=dob,
                    sex=values.get("sex", "U").upper(),
                    email=values.get("email", ""),
                    specialty=values.get("specialty", ""),
                    license_no=values.get("license", ""),
                    timezone_name=values["timezone"],
                    department_name=values["dept"],
                    department_location=values["dept_location"],
                    username=username,
                    password=password,
                    existing_user=existing_user,
                )
                self.current_user = user
                self.show_toast(f"Physician {doctor.name} registered.")
                self.show_doctor_dashboard(doctor)
                if existing_user is None:
                    self.after_idle(self.prompt_save_new_account)
                return True
            self.open_form("Register Physician", fields, on_submit)

        ttk.Button(self.container, text="Start Registration", command=launch_form).grid(row=1, column=0, sticky="ew")
        ttk.Button(self.container, text="Back", command=self.show_start).grid(row=1, column=1, sticky="ew")

    # ---------- Doctor Workspace ----------
    def show_doctor_dashboard(self, doctor: Doctor) -> None:
        self.clear_container()
        self.current_user = self.ctx.users.get(self.current_user.user_id) if self.current_user else None
        ttk.Label(self.container, text=f"Dr. {doctor.name}", font=("Segoe UI", 16, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Button(self.container, text="Log Out", command=self.logout).grid(row=0, column=1, sticky="e")
        button_frame = ttk.Frame(self.container)
        button_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=10)
        ttk.Button(button_frame, text="Register Patient", command=self.register_patient_gui).grid(row=0, column=0, padx=5, pady=5)
        ttk.Button(button_frame, text="Add Availability", command=self.add_availability_gui).grid(row=0, column=1, padx=5, pady=5)
        ttk.Button(button_frame, text="Schedule Appointment", command=self.schedule_appointment_gui).grid(row=0, column=2, padx=5, pady=5)
        ttk.Button(button_frame, text="Record Note", command=self.record_note_gui).grid(row=0, column=3, padx=5, pady=5)
        ttk.Button(button_frame, text="Edit Profile", command=self.edit_doctor_profile).grid(row=0, column=4, padx=5, pady=5)
        ttk.Button(button_frame, text="Change Password", command=self.change_password_gui).grid(row=0, column=5, padx=5, pady=5)
        ttk.Button(button_frame, text="Refresh Summary", command=self.update_summary).grid(row=0, column=6, padx=5, pady=5)
        ttk.Button(button_frame, text="Analytics", command=lambda d=doctor: self.open_analytics(d)).grid(row=0, column=7, padx=5, pady=5)
        ttk.Button(button_frame, text="Attach Document", command=self.attach_document_gui).grid(row=1, column=0, padx=5, pady=5, sticky="w")
        ttk.Button(button_frame, text="View Attachments", command=self.view_attachments_gui).grid(row=1, column=1, padx=5, pady=5, sticky="w")
        ttk.Button(button_frame, text="Add Reminder", command=self.add_reminder_gui).grid(row=1, column=2, padx=5, pady=5, sticky="w")
        summary_frame = ttk.LabelFrame(self.container, text="Summary")
        summary_frame.grid(row=2, column=0, columnspan=2, sticky="nsew")
        self.summary_text = tk.Text(summary_frame, wrap="word", height=18)
        self.summary_text.pack(fill="both", expand=True, padx=8, pady=8)
        self.update_summary()

    def update_summary(self) -> None:
        doctor = self.get_current_doctor()
        if not doctor or not self.summary_text:
            return
        summary = build_physician_summary(self.ctx, doctor)
        self.summary_text.configure(state="normal")
        self.summary_text.delete("1.0", "end")
        self.summary_text.insert("1.0", summary)
        self.summary_text.configure(state="disabled")

    def edit_doctor_profile(self) -> None:
        doctor = self.get_current_doctor()
        if not doctor:
            self.show_message("Profile Missing", "Unable to load physician profile.", error=True)
            return

        department: Optional[Department] = None
        if doctor.department_id:
            try:
                department = self.ctx.depts.get(doctor.department_id)
            except NotFoundError:
                department = None

        current_tz = doctor.timezone or "UTC"
        tz_choices: List[Tuple[str, str]] = list(TIMEZONE_CHOICES)
        tz_label = next((label for label, value in tz_choices if value == current_tz), None)
        if tz_label is None:
            tz_label = current_tz
            tz_choices.append((tz_label, current_tz))

        sex_choices: List[Tuple[str, str]] = [
            ("Male (M)", "M"),
            ("Female (F)", "F"),
            ("Non-binary (X)", "X"),
            ("Unknown (U)", "U"),
        ]
        sex_label = next((label for label, value in sex_choices if value == doctor.sex), "Unknown (U)")

        contact_email = doctor.contact_info.get("email", "")
        dept_name = department.name if department else ""
        dept_location = department.location if department else ""
        fields = [
            {"name": "name", "label": "Full Name", "initial": doctor.name, "required": True},
            {"name": "dob", "label": "Date of Birth (YYYY-MM-DD)", "initial": doctor.dob.date().isoformat(), "required": True},
            {"name": "sex", "label": "Sex", "widget": "combobox", "choices": sex_choices, "initial": sex_label, "required": True},
            {"name": "email", "label": "Email", "initial": contact_email},
            {"name": "specialty", "label": "Specialty", "initial": doctor.specialty},
            {"name": "license", "label": "License Number", "initial": doctor.license_no},
            {"name": "timezone", "label": "Timezone", "widget": "combobox", "choices": tz_choices, "initial": tz_label, "required": True},
            {"name": "dept", "label": "Department Name", "initial": dept_name, "required": True},
            {"name": "dept_location", "label": "Department Location", "initial": dept_location},
        ]

        def on_submit(values: Dict[str, Any]) -> bool:
            name = values["name"].strip()
            specialty = values.get("specialty", "").strip()
            license_no = values.get("license", "").strip()
            email_raw = values.get("email", "").strip()
            timezone_value = values.get("timezone", current_tz) or current_tz
            sex_value = values.get("sex", doctor.sex) or doctor.sex
            department_name = values.get("dept", "").strip()
            department_location = values.get("dept_location", "").strip()

            try:
                dob = self.parse_date(values["dob"])
            except ValidationError as exc:
                raise exc

            contact = dict(doctor.contact_info)
            if email_raw:
                contact["email"] = email_raw
            else:
                contact.pop("email", None)

            doctor.update_details(
                name=name,
                dob=dob,
                sex=sex_value,
                contact_info=contact,
                specialty=specialty,
                license_no=license_no,
                timezone=timezone_value,
            )

            dept_obj: Optional[Department] = None
            if doctor.department_id:
                try:
                    dept_obj = self.ctx.depts.get(doctor.department_id)
                except NotFoundError:
                    dept_obj = None
            if department_name:
                if dept_obj:
                    dept_obj.name = department_name
                    if department_location:
                        dept_obj.location = department_location
                    self.ctx.depts.update(dept_obj)
                else:
                    new_dept = Department(
                        dept_id=str(uuid.uuid4()),
                        name=department_name,
                        location=department_location or "Unknown",
                    )
                    self.ctx.depts.add(new_dept)
                    doctor.update_details(department_id=new_dept.dept_id)
            self.ctx.doctors.update(doctor)
            self.show_doctor_dashboard(doctor)
            self.show_toast("Profile updated.")
            return True

        self.open_form("Edit Profile", fields, on_submit)

    def register_patient_gui(self) -> None:
        doctor = self.get_current_doctor()
        if not doctor:
            return
        self.open_patient_form(doctor)

    def open_patient_form(self, doctor: Doctor) -> None:
        providers = self.ctx.providers.all()
        choices = [("Self-pay", "")]
        for provider in providers:
            choices.append((f"{provider.name} ({provider.country})", provider.provider_id))
        fields = [
            {"name": "name", "label": "Patient Name", "required": True},
            {"name": "dob", "label": "Date of Birth (YYYY-MM-DD)", "required": True},
            {"name": "sex", "label": "Sex (M/F/X)", "initial": "U"},
            {"name": "email", "label": "Email"},
            {"name": "allergies", "label": "Allergies (comma separated)"},
            {"name": "provider", "label": "Insurance Provider", "widget": "combobox", "choices": choices},
            {"name": "plan", "label": "Plan Name"},
            {"name": "member", "label": "Member Number"},
            {"name": "copay", "label": "Copay (0-1)", "initial": "0.2"},
        ]
        def on_submit(values: Dict[str, Any]) -> bool:
            try:
                dob = self.parse_date(values["dob"])
            except ValidationError as exc:
                raise exc
            allergies = [a.strip() for a in values.get("allergies", "").split(",") if a.strip()]
            provider_id = values.get("provider") or None
            copay_val = values.get("copay")
            try:
                copay = float(copay_val) if copay_val else 0.2
            except ValueError:
                raise ValidationError("Copay must be a number between 0 and 1.")
            if provider_id and not (0 <= copay <= 1):
                raise ValidationError("Copay must be between 0 and 1.")
            try:
                create_patient(
                    self.ctx,
                    doctor,
                    name=values["name"],
                    dob=dob,
                    sex=values.get("sex", "U").upper(),
                    email=values.get("email", ""),
                    allergies=allergies,
                    insurance_provider_id=provider_id,
                    insurance_plan=values.get("plan", ""),
                    insurance_member_no=values.get("member", ""),
                    insurance_copay=copay,
                )
            except Exception as exc:
                raise ValidationError(str(exc))
            self.show_toast("Patient registered.")
            self.update_summary()
            return True
        self.open_form("Register Patient", fields, on_submit)

    def add_availability_gui(self) -> None:
        doctor = self.get_current_doctor()
        if not doctor:
            return
        now_local = datetime.now(get_timezone(doctor.timezone)).strftime("%Y-%m-%d %H:%M")
        fields = [
            {"name": "start", "label": "Start (YYYY-MM-DD HH:MM)", "initial": now_local, "required": True},
            {"name": "duration", "label": "Duration (minutes)", "initial": "60", "required": True},
            {"name": "label", "label": "Label", "initial": "Clinic availability"},
        ]
        def on_submit(values: Dict[str, Any]) -> bool:
            try:
                start = self.parse_datetime(values["start"], doctor.timezone)
            except ValidationError as exc:
                raise exc
            try:
                duration = int(values["duration"])
            except ValueError:
                raise ValidationError("Duration must be an integer number of minutes.")
            end = start + timedelta(minutes=duration)
            block = TimeBlock(start, end, values.get("label", "Availability"), "availability")
            try:
                fresh_doc = self.ctx.doctors.get(doctor.doctor_id)
                fresh_doc.schedule.add_block(block)
                self.ctx.doctors.update(fresh_doc)
            except Exception as exc:
                raise ValidationError(str(exc))
            self.show_toast("Availability added.")
            self.update_summary()
            return True
        self.open_form("Add Availability", fields, on_submit)

    def schedule_appointment_gui(self) -> None:
        doctor = self.get_current_doctor()
        if not doctor:
            return
        self.open_schedule_form(doctor, self.current_user)

    def open_schedule_form(self, doctor: Doctor, actor: User) -> None:
        patients = self.ctx.patients.find(primary_doctor_id=doctor.doctor_id)
        if not patients:
            self.show_message("No Patients", "Register a patient before scheduling.", error=True)
            return
        doc_tz = get_timezone(doctor.timezone)
        choices = [(f"{pat.name} ({pat.patient_id[:8]})", pat.patient_id) for pat in patients]
        duration_default = 30
        suggestions = suggest_appointment_slots(doctor, duration_default)
        suggestion_text = "\n".join(
            f"{idx + 1}. {slot.strftime('%Y-%m-%d %H:%M %Z')} ({duration_default} mins)"
            for idx, slot in enumerate(suggestions)
        ) if suggestions else "No smart suggestions available."
        suggestion_choices = [("Select suggestion", "")]
        suggestion_choices.extend(
            [
                (
                    slot.strftime("%Y-%m-%d %H:%M %Z"),
                    f"{slot.astimezone(UTC).isoformat()}|{duration_default}"
                )
                for slot in suggestions
            ]
        )
        initial_start = (
            suggestions[0].strftime("%Y-%m-%d %H:%M")
            if suggestions else datetime.now(doc_tz).strftime("%Y-%m-%d %H:%M")
        )
        fields: List[Dict[str, Any]] = []
        fields.append({"name": "suggestion_info", "label": "Suggested slots", "widget": "label", "initial": suggestion_text})
        if len(suggestion_choices) > 1:
            fields.append({"name": "suggestion_choice", "label": "Use suggestion", "widget": "combobox", "choices": suggestion_choices, "initial": "Select suggestion"})
        fields.extend(
            [
                {"name": "patient", "label": "Patient", "widget": "combobox", "choices": choices, "required": True},
                {"name": "start", "label": "Start (YYYY-MM-DD HH:MM)", "initial": initial_start, "required": True},
                {"name": "duration", "label": "Duration (minutes)", "initial": str(duration_default), "required": True},
                {"name": "reason", "label": "Reason", "initial": "Consult"},
            ]
        )
        def on_submit(values: Dict[str, Any]) -> bool:
            patient_id = values["patient"]
            suggestion_choice = values.get("suggestion_choice")
            try:
                if suggestion_choice:
                    start_iso, duration_token = suggestion_choice.split("|")
                    start = datetime_from_iso(start_iso).astimezone(doc_tz)
                    duration = int(duration_token)
                else:
                    start = self.parse_datetime(values["start"], doctor.timezone)
                    duration = int(values["duration"])
            except ValidationError as exc:
                raise exc
            except ValueError:
                raise ValidationError("Duration must be an integer.")
            end = start + timedelta(minutes=duration)
            try:
                self.ctx.appt_svc.book(
                    actor,
                    patient_id,
                    doctor.doctor_id,
                    doctor.department_id or "",
                    start,
                    end,
                    values.get("reason", ""),
                )
            except Exception as exc:
                raise ValidationError(str(exc))
            self.show_toast("Appointment scheduled.")
            self.update_summary()
            return True
        self.open_form("Schedule Appointment", fields, on_submit)

    def record_note_gui(self) -> None:
        doctor = self.get_current_doctor()
        if not doctor:
            return
        patients = self.ctx.patients.find(primary_doctor_id=doctor.doctor_id)
        if not patients:
            self.show_message("No Patients", "Register a patient before recording notes.", error=True)
            return
        choices = [(f"{pat.name} ({pat.patient_id[:8]})", pat.patient_id) for pat in patients]
        template_choices = [("Select template", "")] + [(tpl["name"], tpl["id"]) for tpl in NOTE_TEMPLATES]
        fields = [
            {"name": "patient", "label": "Patient", "widget": "combobox", "choices": choices, "required": True},
            {"name": "entry_type", "label": "Entry Type", "initial": "visit", "required": True},
            {"name": "template", "label": "Note template", "widget": "combobox", "choices": template_choices, "initial": "Select template"},
            {"name": "notes", "label": "Notes", "widget": "textarea"},
        ]
        def on_submit(values: Dict[str, Any]) -> bool:
            template_id = values.get("template", "")
            template_text = NOTE_TEMPLATE_LOOKUP.get(template_id, {}).get("text", "") if template_id else ""
            note_text = values.get("notes", "").strip()
            if not note_text and template_text:
                note_text = template_text
            if not note_text:
                raise ValidationError("Please enter notes or select a template.")
            try:
                self.ctx.rec_svc.append_entry(
                    self.current_user,
                    values["patient"],
                    values["entry_type"],
                    note_text,
                    author_id=doctor.doctor_id,
                )
            except Exception as exc:
                raise ValidationError(str(exc))
            self.show_toast("Record entry added.")
            self.update_summary()
            return True
        self.open_form("Record Visit Note", fields, on_submit)

    def change_password_gui(self) -> None:
        if not self.current_user:
            return
        fields = [
            {"name": "current", "label": "Current Password", "widget": "entry", "show": "*", "required": True},
            {"name": "new", "label": "New Password", "widget": "entry", "show": "*", "required": True},
            {"name": "confirm", "label": "Confirm Password", "widget": "entry", "show": "*", "required": True},
        ]
        def on_submit(values: Dict[str, Any]) -> bool:
            if not self.ctx.auth.verify_password(self.current_user, values["current"]):
                raise ValidationError("Current password is incorrect.")
            if values["new"] != values["confirm"]:
                raise ValidationError("New passwords do not match.")
            if len(values["new"]) < 4:
                raise ValidationError("Password must be at least four characters.")
            if not self.ctx.auth.change_password(self.current_user, values["current"], values["new"]):
                raise ValidationError("Current password is incorrect.")
            self.ctx.auth.authenticate(self.current_user.user_id, values["new"])
            self.show_toast("Password updated.")
            return True
        self.open_form("Change Password", fields, on_submit)

    def attach_document_gui(self) -> None:
        doctor = self.get_current_doctor()
        if not doctor:
            return
        patients = self.ctx.patients.find(primary_doctor_id=doctor.doctor_id)
        if not patients:
            self.show_message("No Patients", "Register a patient before attaching documents.", error=True)
            return
        file_path = filedialog.askopenfilename(title="Select Document")
        if not file_path:
            return
        file_name = Path(file_path).name
        choices = [(f"{pat.name} ({pat.patient_id[:8]})", pat.patient_id) for pat in patients]
        fields = [
            {"name": "file", "label": "File Selected", "widget": "label", "initial": file_name},
            {"name": "patient", "label": "Patient", "widget": "combobox", "choices": choices, "required": True},
            {"name": "note", "label": "Note", "widget": "textarea"},
        ]
        def on_submit(values: Dict[str, Any]) -> bool:
            note = values.get("note", "")
            try:
                attachment = self.ctx.rec_svc.add_attachment(self.current_user, values["patient"], file_path, note)
            except FileNotFoundError:
                raise ValidationError("The selected file could not be found.")
            except Exception as exc:
                raise ValidationError(str(exc))
            self.show_toast(f"Attachment saved: {attachment.filename}")
            self.update_summary()
            return True
        self.open_form("Attach Document", fields, on_submit)

    def view_attachments_gui(self) -> None:
        doctor = self.get_current_doctor()
        if not doctor:
            return
        patient = self.select_patient_for_doctor(doctor, "Select Patient for Attachments")
        if not patient:
            return
        record = self.ctx.rec_svc.ensure_record(patient.patient_id)
        if not record.attachments:
            self.show_message("No Attachments", "No documents are attached to this record.", error=True)
            return
        attachments_by_id = {att.attachment_id: att for att in record.attachments}
        win = tk.Toplevel(self)
        win.title(f"Attachments - {patient.name}")
        win.geometry("600x400")
        tree = ttk.Treeview(win, columns=("filename", "uploaded", "note"), show="headings")
        tree.heading("filename", text="File")
        tree.heading("uploaded", text="Uploaded")
        tree.heading("note", text="Note")
        tree.column("filename", width=220)
        tree.column("uploaded", width=140)
        tree.column("note", width=220)
        tree.pack(fill="both", expand=True, padx=8, pady=8)
        for att in record.attachments:
            tree.insert(
                "",
                "end",
                iid=att.attachment_id,
                values=(
                    att.filename,
                    att.uploaded_dt.astimezone(get_timezone(doctor.timezone)).strftime("%Y-%m-%d %H:%M"),
                    att.note,
                ),
            )
        def open_selected():
            selection = tree.selection()
            if not selection:
                return
            att = attachments_by_id.get(selection[0])
            if not att:
                return
            self.open_attachment_file(att)
        tree.bind("<Double-1>", lambda _event: open_selected())
        button_bar = ttk.Frame(win)
        button_bar.pack(fill="x", padx=8, pady=4)
        ttk.Button(button_bar, text="Open", command=open_selected).pack(side="right", padx=(6, 0))
        ttk.Button(button_bar, text="Close", command=win.destroy).pack(side="right")
        win.transient(self)
        win.grab_set()

    def open_attachment_file(self, attachment: RecordAttachment) -> None:
        path = Path(attachment.stored_path)
        if not path.is_absolute():
            path = ATTACHMENTS_DIR / path
        if not path.exists():
            self.show_message("Missing File", f"File not found: {path}", error=True)
            return
        try:
            if os.name == "nt":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            self.show_message("Open Failed", str(exc), error=True)

    def add_reminder_gui(self) -> None:
        doctor = self.get_current_doctor()
        if not doctor:
            return
        patient = self.select_patient_for_doctor(doctor, "Select Patient for Reminder")
        if not patient:
            return
        template_choices = [("Select template", "")] + [(tpl["name"], tpl["id"]) for tpl in REMINDER_TEMPLATES]
        fields = [
            {"name": "template", "label": "Reminder template", "widget": "combobox", "choices": template_choices, "initial": "Select template"},
            {"name": "due", "label": "Due date (YYYY-MM-DD)"},
            {"name": "note", "label": "Reminder note", "widget": "textarea"},
        ]
        def on_submit(values: Dict[str, Any]) -> bool:
            template_id = values.get("template", "")
            template_text = REMINDER_TEMPLATE_LOOKUP.get(template_id, {}).get("text", "") if template_id else ""
            note = values.get("note", "").strip()
            if not note and template_text:
                note = template_text
            if not note:
                raise ValidationError("Please enter a reminder or select a template.")
            due = values.get("due", "").strip()
            if due:
                note = f"{note}\nDue: {due}"
            try:
                self.ctx.rec_svc.append_entry(
                    self.current_user,
                    patient.patient_id,
                    "reminder",
                    note,
                    author_id=doctor.doctor_id,
                )
            except Exception as exc:
                raise ValidationError(str(exc))
            self.show_toast("Reminder added.")
            self.update_summary()
            return True
        self.open_form("Add Reminder", fields, on_submit)

    # ---------- Staff (non-doctor) ----------
    def select_doctor_dialog(self, prompt_title: str="Select Doctor") -> Optional[Doctor]:
        doctors = self.ctx.doctors.all()
        if not doctors:
            self.show_message("No Doctors", "No doctors are registered in the system.", error=True)
            return None
        choices = [(f"Dr. {doc.name} ({doc.specialty})", doc.doctor_id) for doc in doctors]
        fields = [
            {"name": "doctor", "label": "Doctor", "widget": "combobox", "choices": choices, "required": True},
        ]
        win = self.open_form(prompt_title, fields, lambda data: True)
        self.wait_window(win)
        result = getattr(win, "result", None)
        if not result:
            return None
        doctor_id = result.get("doctor")
        try:
            return self.ctx.doctors.get(doctor_id)
        except NotFoundError:
            self.show_message("Error", "Selected doctor no longer exists.", error=True)
            return None

    def select_patient_for_doctor(self, doctor: Doctor, prompt_title: str="Select Patient") -> Optional[Patient]:
        patients = self.ctx.patients.find(primary_doctor_id=doctor.doctor_id)
        if not patients:
            self.show_message("No Patients", "No patients are assigned to this doctor.", error=True)
            return None
        choices = [(f"{pat.name} ({pat.patient_id[:8]})", pat.patient_id) for pat in patients]
        fields = [
            {"name": "patient", "label": "Patient", "widget": "combobox", "choices": choices, "required": True},
        ]
        win = self.open_form(prompt_title, fields, lambda data: True)
        self.wait_window(win)
        result = getattr(win, "result", None)
        if not result:
            return None
        try:
            return self.ctx.patients.get(result["patient"])
        except NotFoundError:
            self.show_message("Error", "Selected patient no longer exists.", error=True)
            return None

    def clerk_register_patient(self) -> None:
        doctor = self.select_doctor_dialog()
        if not doctor:
            return
        self.open_patient_form(doctor)

    def clerk_schedule_appointment(self) -> None:
        doctor = self.select_doctor_dialog("Select Doctor for Appointment")
        if not doctor:
            return
        self.open_schedule_form(doctor, self.current_user)

    def apply_billing_template_gui(self) -> None:
        patients = self.ctx.patients.all()
        if not patients:
            self.show_message("No Patients", "No patients are available for billing.", error=True)
            return
        patient_choices = sorted(
            [(f"{pat.name} ({pat.patient_id[:8]})", pat.patient_id) for pat in patients],
            key=lambda item: item[0],
        )
        template_choices = [("Select template", "")] + [(tpl["name"], tpl["id"]) for tpl in BILLING_TEMPLATES]
        fields = [
            {"name": "patient", "label": "Patient", "widget": "combobox", "choices": patient_choices, "required": True},
            {"name": "template", "label": "Billing template", "widget": "combobox", "choices": template_choices, "initial": "Select template"},
            {"name": "code", "label": "Billing code override"},
            {"name": "amount", "label": "Amount"},
            {"name": "description", "label": "Description", "widget": "textarea"},
        ]
        def on_submit(values: Dict[str, Any]) -> bool:
            template_id = values.get("template", "")
            template = BILLING_TEMPLATE_LOOKUP.get(template_id) if template_id else None
            if not template:
                raise ValidationError("Please select a billing template.")
            amount_text = values.get("amount", "").strip() or str(template["amount"])
            try:
                amount_val = float(amount_text)
            except ValueError:
                raise ValidationError("Amount must be numeric.")
            code = values.get("code", "").strip() or template["code"]
            description = values.get("description", "").strip() or template["description"]
            try:
                self.ctx.bill_svc.invoice(self.current_user, values["patient"], code, amount_val, description)
            except Exception as exc:
                raise ValidationError(str(exc))
            self.show_toast(f"Invoiced {code} for ${amount_val:.2f}.")
            return True
        self.open_form("Apply Billing Template", fields, on_submit)

    def nurse_refresh_beds(self) -> None:
        if not hasattr(self, "nurse_bed_text") or not self.nurse_bed_text:
            return
        beds = self.ctx.beds.all()
        self.nurse_bed_text.configure(state="normal")
        self.nurse_bed_text.delete("1.0", "end")
        if not beds:
            self.nurse_bed_text.insert("1.0", "No beds configured.")
        else:
            for bed in beds:
                line = f"{bed.bed_id} | room {bed.room_id} | status {bed.status}"
                if bed.occupant_patient_id:
                    try:
                        pat = self.ctx.patients.get(bed.occupant_patient_id)
                        line += f" | patient {pat.name}"
                    except NotFoundError:
                        line += f" | patient {bed.occupant_patient_id}"
                line += "\n"
                self.nurse_bed_text.insert("end", line)
        self.nurse_bed_text.configure(state="disabled")

    def nurse_admit_patient(self) -> None:
        doctor = self.select_doctor_dialog("Select admitting doctor")
        if not doctor:
            return
        patients = self.ctx.patients.find(primary_doctor_id=doctor.doctor_id)
        if not patients:
            self.show_message("No Patients", "Selected doctor has no patients to admit.", error=True)
            return
        beds = [bed for bed in self.ctx.beds.all() if bed.status == "free"]
        if not beds:
            self.show_message("No Beds", "No free beds are available.", error=True)
            return
        patient_choices = [(f"{pat.name} ({pat.patient_id[:8]})", pat.patient_id) for pat in patients]
        bed_choices = [(f"{bed.bed_id} ({bed.room_id})", bed.bed_id) for bed in beds]
        start_default = datetime.now(get_timezone(doctor.timezone)).strftime("%Y-%m-%d %H:%M")
        fields = [
            {"name": "patient", "label": "Patient", "widget": "combobox", "choices": patient_choices, "required": True},
            {"name": "bed", "label": "Bed", "widget": "combobox", "choices": bed_choices, "required": True},
            {"name": "start", "label": "Start (YYYY-MM-DD HH:MM)", "initial": start_default, "required": True},
            {"name": "hours", "label": "Duration hours", "initial": "24", "required": True},
        ]
        def on_submit(values: Dict[str, Any]) -> bool:
            try:
                start_dt = self.parse_datetime(values["start"], doctor.timezone)
            except ValidationError as exc:
                raise exc
            try:
                hours = int(values["hours"])
            except ValueError:
                raise ValidationError("Hours must be an integer.")
            try:
                self.ctx.ip_svc.admit(
                    self.current_user,
                    values["patient"],
                    doctor.doctor_id,
                    hours=hours,
                    start_dt=start_dt,
                )
            except Exception as exc:
                raise ValidationError(str(exc))
            self.show_toast("Patient admitted.")
            self.nurse_refresh_beds()
            return True
        self.open_form("Admit Patient", fields, on_submit)

    def nurse_discharge_bed(self) -> None:
        occupied = [bed for bed in self.ctx.beds.all() if bed.status != "free"]
        if not occupied:
            self.show_message("No Occupied Beds", "All beds are free or unavailable.", error=True)
            return
        bed_choices = [(f"{bed.bed_id} ({bed.status})", bed.bed_id) for bed in occupied]
        fields = [
            {"name": "bed", "label": "Bed", "widget": "combobox", "choices": bed_choices, "required": True},
        ]
        def on_submit(values: Dict[str, Any]) -> bool:
            try:
                self.ctx.ip_svc.discharge(self.current_user, values["bed"])
            except Exception as exc:
                raise ValidationError(str(exc))
            self.show_toast("Bed set to cleaning.")
            self.nurse_refresh_beds()
            return True
        self.open_form("Discharge Bed", fields, on_submit)

    def admin_view_audit(self) -> None:
        events = self.ctx.audit.events[-100:]
        win = tk.Toplevel(self)
        win.title("Audit Log")
        text = tk.Text(win, wrap="word", height=25, width=80)
        text.pack(fill="both", expand=True)
        if not events:
            text.insert("1.0", "No audit events recorded.")
        else:
            for ev in events:
                line = f"{ev.when.strftime('%Y-%m-%d %H:%M UTC')} | {ev.who} | {ev.what}\n"
                text.insert("end", line)
        text.configure(state="disabled")
        ttk.Button(win, text="Close", command=win.destroy).pack(pady=6)

    def admin_reset_password_gui(self) -> None:
        users = sorted(self.ctx.users.values(), key=lambda u: u.user_id)
        if len(users) <= 1:
            self.show_message("No Users", "No other users available to reset.", error=True)
            return
        choices = [(f"{user.user_id} ({'/'.join(user.roles)})", user.user_id) for user in users if user.user_id != self.current_user.user_id]
        if not choices:
            self.show_message("No Users", "No other users available to reset.", error=True)
            return
        fields = [
            {"name": "user", "label": "User", "widget": "combobox", "choices": choices, "required": True},
            {"name": "password", "label": "New Password", "widget": "entry", "show": "*", "required": True},
            {"name": "confirm", "label": "Confirm Password", "widget": "entry", "show": "*", "required": True},
        ]
        def on_submit(values: Dict[str, Any]) -> bool:
            if values["password"] != values["confirm"]:
                raise ValidationError("Passwords do not match.")
            if len(values["password"]) < 4:
                raise ValidationError("Password must be at least four characters.")
            target = self.ctx.users.get(values["user"])
            if not target:
                raise ValidationError("User not found.")
            self.ctx.auth.reset_password(target, values["password"])
            self.show_toast(f"Password updated for {target.user_id}.")
            return True
        self.open_form("Reset User Password", fields, on_submit)

    def open_analytics(self, doctor: Optional[Doctor]) -> None:
        win = tk.Toplevel(self)
        if doctor:
            win.title(f"Analytics - Dr. {doctor.name}")
        else:
            win.title("Analytics Dashboard")
        win.geometry("720x520")
        notebook = ttk.Notebook(win)
        notebook.pack(fill="both", expand=True, padx=8, pady=8)

        # Schedule tab
        schedule_frame = ttk.Frame(notebook)
        notebook.add(schedule_frame, text="Schedule")
        schedule_text = tk.Text(schedule_frame, wrap="word")
        schedule_text.pack(fill="both", expand=True)
        now = datetime.now(UTC)
        appointments = sorted(
            [
                appt for appt in self.ctx.appts.all()
                if appt.end_dt >= now and (not doctor or appt.doctor_id == doctor.doctor_id)
            ],
            key=lambda a: a.start_dt,
        )
        if appointments:
            daily_counts: Dict[str, int] = {}
            for appt in appointments:
                try:
                    doc = self.ctx.doctors.get(appt.doctor_id)
                    pat = self.ctx.patients.get(appt.patient_id)
                except NotFoundError:
                    continue
                doc_tz = get_timezone(doc.timezone)
                start_local = appt.start_dt.astimezone(doc_tz)
                day_key = start_local.strftime("%Y-%m-%d")
                daily_counts[day_key] = daily_counts.get(day_key, 0) + 1
                line = (
                    f"{start_local.strftime('%Y-%m-%d %H:%M %Z')} | "
                    f"Dr. {doc.name} with {pat.name} | status: {appt.status}\n"
                )
                schedule_text.insert("end", line)
            schedule_text.insert("end", "\nDaily totals:\n")
            for day, count in sorted(daily_counts.items()):
                schedule_text.insert("end", f"- {day}: {count} appointment(s)\n")
        else:
            schedule_text.insert("1.0", "No upcoming appointments found.")
        schedule_text.configure(state="disabled")

        # Billing tab
        billing_frame = ttk.Frame(notebook)
        notebook.add(billing_frame, text="Billing")
        billing_text = tk.Text(billing_frame, wrap="word")
        billing_text.pack(fill="both", expand=True)
        accounts = self.ctx.billing.all()
        if doctor:
            doctor_patients = {p.patient_id for p in self.ctx.patients.find(primary_doctor_id=doctor.doctor_id)}
            accounts = [acct for acct in accounts if acct.patient_id in doctor_patients]
        rows = []
        total_balance = 0.0
        for acct in accounts:
            try:
                pat = self.ctx.patients.get(acct.patient_id)
                name = pat.name
            except NotFoundError:
                name = acct.patient_id
            balance = acct.balance()
            total_balance += balance
            rows.append((balance, name, len(acct.charges), len(acct.payments)))
        rows.sort(reverse=True)
        billing_text.insert("end", f"Accounts: {len(rows)} | Outstanding balance: ${total_balance:.2f}\n\n")
        if rows:
            for balance, name, charges, payments in rows:
                billing_text.insert(
                    "end",
                    f"{name}: balance ${balance:.2f} (charges {charges}, payments {payments})\n",
                )
        else:
            billing_text.insert("end", "No billing accounts available for this view.")
        billing_text.configure(state="disabled")

        # Audit tab
        audit_frame = ttk.Frame(notebook)
        notebook.add(audit_frame, text="Audit")
        audit_text = tk.Text(audit_frame, wrap="word")
        audit_text.pack(fill="both", expand=True)
        events = self.ctx.audit.events
        if doctor:
            audit_text.insert("end", "Showing global audit activity.\n\n")
        if events:
            counts: Dict[str, int] = {}
            for ev in events:
                counts[ev.what] = counts.get(ev.what, 0) + 1
            audit_text.insert("end", "Event totals:\n")
            for action, count in sorted(counts.items(), key=lambda x: x[1], reverse=True):
                audit_text.insert("end", f"- {action}: {count}\n")
            audit_text.insert("end", "\nRecent events:\n")
            for ev in events[-20:]:
                audit_text.insert(
                    "end",
                    f"{ev.when.strftime('%Y-%m-%d %H:%M UTC')} | {ev.who} | {ev.what}\n",
                )
        else:
            audit_text.insert("1.0", "No audit events recorded.")
        audit_text.configure(state="disabled")

        ttk.Button(win, text="Close", command=win.destroy).pack(pady=4)
        win.transient(self)
        win.grab_set()

    def show_staff_view(self) -> None:
        self.clear_container()
        roles = self.current_user.roles if self.current_user else []
        self.nurse_bed_text = None
        ttk.Label(self.container, text=f"Welcome {self.current_user.user_id}", font=("Segoe UI", 16, "bold")).grid(row=0, column=0, sticky="w")
        top_bar = ttk.Frame(self.container)
        top_bar.grid(row=0, column=1, sticky="e")
        ttk.Button(top_bar, text="Change Password", command=self.change_password_gui).pack(side="right", padx=(6, 0))
        ttk.Button(top_bar, text="Log Out", command=self.logout).pack(side="right")

        notebook = ttk.Notebook(self.container)
        notebook.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=10)
        self.container.rowconfigure(1, weight=1)
        self.container.columnconfigure(0, weight=1)
        self.container.columnconfigure(1, weight=1)

        if "clerk" in roles or "admin" in roles:
            clerk_tab = ttk.Frame(notebook, padding=12)
            notebook.add(clerk_tab, text="Clerk")
            ttk.Button(clerk_tab, text="Register Patient", command=self.clerk_register_patient).grid(row=0, column=0, sticky="w", pady=4)
            ttk.Button(clerk_tab, text="Schedule Appointment", command=self.clerk_schedule_appointment).grid(row=1, column=0, sticky="w", pady=4)
            ttk.Label(clerk_tab, text="Clerks can register patients for any doctor and schedule visits.", wraplength=420).grid(row=2, column=0, pady=(10, 0), sticky="w")

        if "nurse" in roles or "admin" in roles:
            nurse_tab = ttk.Frame(notebook, padding=12)
            notebook.add(nurse_tab, text="Nurse")
            ttk.Button(nurse_tab, text="Admit Patient", command=self.nurse_admit_patient).grid(row=0, column=0, sticky="w", pady=4)
            ttk.Button(nurse_tab, text="Discharge Bed", command=self.nurse_discharge_bed).grid(row=1, column=0, sticky="w", pady=4)
            ttk.Button(nurse_tab, text="Refresh Bed Status", command=self.nurse_refresh_beds).grid(row=2, column=0, sticky="w", pady=4)
            self.nurse_bed_text = tk.Text(nurse_tab, height=12, width=50)
            self.nurse_bed_text.grid(row=3, column=0, pady=10, sticky="nsew")
            nurse_tab.rowconfigure(3, weight=1)
            self.nurse_refresh_beds()

        if "admin" in roles:
            admin_tab = ttk.Frame(notebook, padding=12)
            notebook.add(admin_tab, text="Admin")
            ttk.Button(admin_tab, text="Reset User Password", command=self.admin_reset_password_gui).grid(row=0, column=0, sticky="w", pady=4)
            ttk.Button(admin_tab, text="Apply Billing Template", command=self.apply_billing_template_gui).grid(row=1, column=0, sticky="w", pady=4)
            ttk.Button(admin_tab, text="View Audit Log", command=self.admin_view_audit).grid(row=2, column=0, sticky="w", pady=4)
            ttk.Button(admin_tab, text="Open Analytics Dashboard", command=lambda: self.open_analytics(None)).grid(row=3, column=0, sticky="w", pady=4)
            ttk.Label(admin_tab, text="Admin tools cover password resets, templated billing, and analytics.", wraplength=420).grid(row=4, column=0, pady=(10, 0), sticky="w")
            admin_tab.grid_rowconfigure(5, weight=1)

        if notebook.index("end") == 0:
            ttk.Label(self.container, text="No staff tools available for your roles.", wraplength=500).grid(row=2, column=0, pady=20, sticky="w")


    def logout(self) -> None:
        if self.current_user:
            self.current_user.clear_sessions()
        self.current_user = None
        self.show_start()

def run_cli() -> None:
    ctx = initialize_system()
    menu_primary = (
        "\nWelcome to the hospital system.\n"
        "1. Log in as staff\n"
        "2. Register a new physician\n"
        "Q. Quit\n"
    )
    while True:
        print(menu_primary)
        choice = prompt_input("Choice", required=True).lower()
        if choice in ("q", "quit", "exit"):
            print("Goodbye!")
            return
        if choice == "2":
            doctor, user = register_physician(ctx)
            physician_loop(ctx, doctor, user)
        elif choice == "1":
            user = login_user(ctx)
            if user:
                handle_user_session(ctx, user)
        else:
            print("Please choose a valid option.")

if __name__ == "__main__":
    if "--demo" in sys.argv:
        print(run_demo())
    elif "--smoke-test" in sys.argv:
        print(json.dumps(run_smoke_tests(), indent=2))
    else:
        app = HospitalGUI()
        app.mainloop()
