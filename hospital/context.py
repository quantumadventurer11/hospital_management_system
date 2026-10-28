"""System composition and demo registration workflows."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import uuid
from .domain import (Appointment, Bed, BillingAccount, Department, Doctor,
                     InsurancePolicy, InsuranceProvider, MedicalRecord, Patient)
from .errors import AuthorizationError, DuplicateError, ValidationError
from .repositories import (Repo, PatientRepo, DoctorRepo, DepartmentRepo,
                           AppointmentRepo, RecordRepo, BillingRepo, BedRepo,
                           InsuranceProviderRepo, PolicyRepo)
from .security import AuditLog, AuthService, User
from .services import (AppointmentService, MedicalRecordService, BillingService,
                       InpatientService)
from .domain import HardNoOverlapPolicy
from .timezones import get_timezone

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
