"""Appointment, record, billing, and inpatient workflows."""
from __future__ import annotations
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import hashlib
import math
import shutil
import uuid
from .attachments import ATTACHMENTS_DIR
from .domain import (Appointment, Bed, BillingAccount, BillingStrategy, Charge,
                     ConflictPolicy, Department, Doctor, HardNoOverlapPolicy,
                     InsurancePolicy, InsuranceStrategy, MedicalRecord, Patient,
                     Payment, RecordAttachment, RecordEntry, SelfPayStrategy,
                     TimeBlock)
from .errors import (AuthorizationError, SchedulingConflictError, TimezoneError,
                     ValidationError)
from .repositories import Repo
from .security import AuditEvent, AuditLog, AuthService, User, require_role
from .timezones import UTC, get_timezone

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
        if "doctor" in user.roles and "admin" not in user.roles:
            if user.person_id != doctor_id or patient.primary_doctor_id != doctor_id:
                raise AuthorizationError("Doctor can book only their own patients and schedule.")
        if doctor.department_id and doctor.department_id != dept_id:
            raise ValidationError("Appointment department does not match the doctor's department.")
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
        if "doctor" in user.roles and "admin" not in user.roles and user.person_id != appt.doctor_id:
            raise AuthorizationError("Doctor can complete only their own appointments.")
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

    def _require_patient_access(self, user: User, patient_id: str) -> Patient:
        require_role(user, ["admin", "doctor", "nurse"], auth=self._auth, token=user.session_token)
        patient = self._patients.get(patient_id)
        if "doctor" in user.roles and "admin" not in user.roles:
            if not user.person_id or patient.primary_doctor_id != user.person_id:
                raise AuthorizationError("Doctor cannot access an unassigned patient.")
        return patient

    def ensure_record(self, user: User, patient_id: str) -> MedicalRecord:
        """Return the existing medical record or create a new chart."""
        patient = self._require_patient_access(user, patient_id)
        for record in self._records.all():
            if record.patient_id == patient_id:
                return record
        record = MedicalRecord(record_id=str(uuid.uuid4()), patient_id=patient.patient_id)
        self._records.add(record)
        return record

    def append_entry(self, user: User, patient_id: str, entry_type: str, notes: str, author_id: str) -> RecordEntry:
        """Append a structured clinical note."""
        self._require_patient_access(user, patient_id)
        if "admin" not in user.roles:
            expected_author = user.person_id if "doctor" in user.roles else user.user_id
            if author_id != expected_author:
                raise AuthorizationError("Record author must match the signed-in user.")
        record = self.ensure_record(user, patient_id)
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
        self._require_patient_access(user, patient_id)
        src = Path(source_path)
        if not src.exists() or not src.is_file():
            raise FileNotFoundError(f"File not found: {source_path}")
        record = self.ensure_record(user, patient_id)
        # Hash the patient ID so an imported ID cannot become a filesystem path.
        patient_dir = self._attachments_dir / hashlib.sha256(patient_id.encode("utf-8")).hexdigest()
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
