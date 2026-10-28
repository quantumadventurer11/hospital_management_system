"""Scripted demonstration and lightweight smoke checks."""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Any, Dict
import uuid
from .context import SystemContext, initialize_system
from .domain import (AllowBufferPolicy, Bed, Department, Doctor,
                     InsurancePolicy, InsuranceProvider, Patient, TimeBlock)
from .errors import SchedulingConflictError
from .security import User
from .templates import format_section
from .timezones import UTC, get_timezone

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
    doctor_user.person_id = doc.doctor_id

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
    east_user = User(user_id="doctor_east", roles=["doctor"], person_id=doc_east.doctor_id)
    ctx.auth.register_user(east_user, "demo_east123")
    ctx.auth.authenticate(east_user.user_id, "demo_east123")

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

    appt_svc.complete(east_user, tele_appt.appt_id)
    _ = rec_svc.append_entry(east_user, pat_ca.patient_id, "diagnosis", "Remote rehab plan updated.", author_id=doc_east.doctor_id)

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
