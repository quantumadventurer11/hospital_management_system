"""JSON serialization and atomic save/load for synthetic demo data."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
import json
import os
import tempfile
from .context import SystemContext, initialize_system
from .domain import (Appointment, Bed, BillingAccount, Charge, Department,
                     Doctor, InsurancePolicy, InsuranceProvider, MedicalRecord,
                     Patient, Payment, RecordAttachment, RecordEntry, Schedule,
                     TimeBlock)
from .errors import ValidationError
from .security import AuditEvent, User
from .timezones import UTC, get_timezone

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
    if not isinstance(data, dict):
        raise ValidationError("Hospital data must be a JSON object.")
    ctx = initialize_system(seed_defaults=False)
    ctx.users.clear()
    for user_info in data.get("users", []):
        if not isinstance(user_info, dict) or not isinstance(user_info.get("user_id"), str):
            raise ValidationError("Saved user information is invalid.")
        if user_info["user_id"] in ctx.users:
            raise ValidationError("Duplicate user ID in hospital data.")
        user = User(
            user_id=user_info["user_id"],
            roles=user_info.get("roles", []),
            person_id=user_info.get("person_id"),
        )
        password_hash = user_info.get("password_hash")
        password_salt = user_info.get("password_salt")
        if not isinstance(password_hash, str) or not isinstance(password_salt, str):
            raise ValidationError("Saved user is missing a password hash or salt.")
        try:
            hash_bytes = bytes.fromhex(password_hash)
            salt_bytes = bytes.fromhex(password_salt)
        except ValueError as exc:
            raise ValidationError("Saved user credentials are invalid.") from exc
        if len(hash_bytes) != 32 or len(salt_bytes) != 16:
            raise ValidationError("Saved user credentials have invalid lengths.")
        user.password_hash = password_hash
        user.password_salt = password_salt
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
        if "prev_hash" not in ev or "event_hash" not in ev:
            raise ValidationError("Audit log event is missing its chain hash.")
        expected_prev = ev["prev_hash"]
        expected_hash = ev["event_hash"]
        if logged.prev_hash != expected_prev:
            raise ValidationError("Audit log chain mismatch detected while loading data.")
        if logged.event_hash != expected_hash:
            raise ValidationError("Audit log hash mismatch detected while loading data.")
    return ctx

def save_context_to_file(ctx: SystemContext, path: str) -> None:
    payload = context_to_dict(ctx)
    target = Path(path)
    temporary_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=target.parent, prefix=f".{target.name}.",
            suffix=".tmp", delete=False,
        ) as fh:
            temporary_path = Path(fh.name)
            json.dump(payload, fh, indent=2, allow_nan=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temporary_path, target)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

def load_context_from_file(path: str) -> SystemContext:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return context_from_dict(data)
