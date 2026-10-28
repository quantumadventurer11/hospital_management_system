"""Scheduling policies and domain objects for the educational demo."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, ClassVar, Dict, List, Mapping, Optional, Sequence, Tuple
import uuid
try:
    from typing import Protocol, runtime_checkable
except Exception:
    from typing_extensions import Protocol, runtime_checkable  # type: ignore
from .errors import SchedulingConflictError, ValidationError
from .timezones import UTC, get_timezone

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
