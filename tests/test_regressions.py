"""Regression checks for account access and core workflow failures."""

import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import hospital_management_system as h


class HospitalRegressionTests(unittest.TestCase):
    def setUp(self):
        self.ctx = h.initialize_system()
        self.admin = self.ctx.auth.authenticate("admin", "admin123")[0]
        self.dept = h.Department("test-dept", "General", "Test site")
        self.ctx.depts.add(self.dept)
        self.doctor = h.Doctor(
            "test-person-doctor", "Test Doctor", datetime(1980, 1, 1, tzinfo=h.UTC),
            "U", {}, department_id=self.dept.dept_id, timezone="UTC",
        )
        self.ctx.doctors.add(self.doctor)
        self.patient = h.Patient(
            "test-person-patient", "Test Patient", datetime(1990, 1, 1, tzinfo=h.UTC),
            "U", {}, primary_doctor_id=self.doctor.doctor_id,
        )
        self.ctx.patients.add(self.patient)

    def test_new_account_logs_in_and_survives_explicit_save_load(self):
        doctor, user = h.create_physician(
            self.ctx, name="New Doctor", dob=datetime(1985, 1, 1, tzinfo=h.UTC),
            sex="U", email="", specialty="General", license_no="TEST",
            timezone_name="UTC", department_name="General", department_location="Test",
            username="newdoctor", password="test-password",
        )
        self.assertEqual(user.person_id, doctor.doctor_id)
        self.assertTrue(self.ctx.auth.validate_session(user.user_id, user.session_token))
        self.assertIsNotNone(self.ctx.auth.authenticate("newdoctor", "test-password"))
        with TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
            path = Path(tmp) / "synthetic-hospital-data.json"
            h.save_context_to_file(self.ctx, str(path))
            restored = h.load_context_from_file(str(path))
            self.assertIsNotNone(restored.auth.authenticate("newdoctor", "test-password"))

    def test_duplicate_account_does_not_create_orphan_profile(self):
        before = (len(list(self.ctx.depts.all())), len(list(self.ctx.doctors.all())))
        with self.assertRaises(h.DuplicateError):
            h.create_physician(
                self.ctx, name="Duplicate", dob=datetime(1985, 1, 1, tzinfo=h.UTC),
                sex="U", email="", specialty="General", license_no="TEST",
                timezone_name="UTC", department_name="General", department_location="Test",
                username="admin", password="test-password",
            )
        self.assertEqual(before, (len(list(self.ctx.depts.all())), len(list(self.ctx.doctors.all()))))

    def test_existing_account_needs_session_to_add_physician_profile(self):
        existing = self.ctx.users["doctor"]
        with self.assertRaises(h.AuthorizationError):
            h.create_physician(
                self.ctx, name="New Profile", dob=datetime(1985, 1, 1, tzinfo=h.UTC),
                sex="U", email="", specialty="General", license_no="TEST",
                timezone_name="UTC", department_name="General", department_location="Test",
                existing_user=existing,
            )
        self.assertEqual(len(list(self.ctx.doctors.all())), 1)

    def test_status_defaults_and_validation(self):
        start = datetime.now(h.UTC) + timedelta(days=1)
        appointment = h.Appointment("a", "p", "d", "dept", start, start + timedelta(minutes=30))
        bed = h.Bed("b", "room")
        self.assertEqual(appointment.status, "scheduled")
        self.assertEqual(bed.status, "free")
        with self.assertRaises(h.ValidationError):
            appointment.status = "unknown"
        with self.assertRaises(h.ValidationError):
            bed.status = "unknown"

    def test_unregistered_and_forged_users_cannot_book(self):
        start = datetime.now(h.UTC) + timedelta(days=1)
        fake = h.User("unregistered", ["doctor"])
        with self.assertRaises(h.AuthorizationError):
            self.ctx.appt_svc.book(fake, self.patient.patient_id, self.doctor.doctor_id,
                                   self.dept.dept_id, start, start + timedelta(minutes=30), "test")
        forged_admin = h.User("admin", ["admin"], session_token=self.admin.session_token)
        with self.assertRaises(h.AuthorizationError):
            self.ctx.appt_svc.book(forged_admin, self.patient.patient_id, self.doctor.doctor_id,
                                   self.dept.dept_id, start, start + timedelta(minutes=30), "test")
        self.assertEqual(len(list(self.ctx.appts.all())), 0)

    def test_reversed_appointment_time_is_rejected(self):
        start = datetime.now(h.UTC) + timedelta(days=1)
        with self.assertRaises(h.ValidationError):
            self.ctx.appt_svc.book(self.admin, self.patient.patient_id, self.doctor.doctor_id,
                                   self.dept.dept_id, start, start - timedelta(minutes=5), "test")
        self.assertEqual(len(list(self.ctx.appts.all())), 0)

    def test_bad_payments_and_charges_are_rejected(self):
        for value in (-100, 0, float("nan"), float("inf")):
            with self.subTest(value=value):
                with self.assertRaises(h.ValidationError):
                    self.ctx.bill_svc.post_payment(self.admin, self.patient.patient_id, "cash", value)
                with self.assertRaises(h.ValidationError):
                    self.ctx.bill_svc.invoice(self.admin, self.patient.patient_id, "T", value, "test")
        with self.assertRaises(h.ValidationError):
            self.ctx.bill_svc.post_payment(self.admin, self.patient.patient_id, "unknown", 10)
        self.assertEqual(len(list(self.ctx.billing.all())), 0)

    def test_failed_admission_leaves_bed_free(self):
        start = datetime.now(h.UTC) + timedelta(days=1)
        self.doctor.schedule.add_block(
            h.TimeBlock(start, start + timedelta(hours=2), "busy", "appt")
        )
        bed = h.Bed("bed-1", "room-1")
        self.ctx.beds.add(bed)
        with self.assertRaises(h.SchedulingConflictError):
            self.ctx.ip_svc.admit(self.admin, self.patient.patient_id,
                                  self.doctor.doctor_id, start_dt=start)
        self.assertEqual(bed.status, "free")
        self.assertIsNone(bed.occupant_patient_id)
        self.assertEqual(len(self.ctx.audit.events), 0)

    def test_completed_appointment_cannot_be_completed_twice(self):
        start = datetime.now(h.UTC) + timedelta(days=1)
        appointment = self.ctx.appt_svc.book(
            self.admin, self.patient.patient_id, self.doctor.doctor_id,
            self.dept.dept_id, start, start + timedelta(minutes=30), "test",
        )
        self.ctx.appt_svc.complete(self.admin, appointment.appt_id)
        with self.assertRaises(h.ValidationError):
            self.ctx.appt_svc.complete(self.admin, appointment.appt_id)
        self.assertEqual(appointment.status, "completed")

    def test_free_bed_cannot_be_discharged(self):
        bed = h.Bed("bed-1", "room-1")
        self.ctx.beds.add(bed)
        with self.assertRaises(h.ValidationError):
            self.ctx.ip_svc.discharge(self.admin, bed.bed_id)
        self.assertEqual(bed.status, "free")

    def test_doctor_cannot_access_another_doctors_patient(self):
        other_doctor = h.Doctor(
            "other-person", "Other Doctor", datetime(1980, 1, 1, tzinfo=h.UTC),
            "U", {}, department_id=self.dept.dept_id, timezone="UTC",
        )
        self.ctx.doctors.add(other_doctor)
        other_patient = h.Patient(
            "other-patient", "Other Patient", datetime(1990, 1, 1, tzinfo=h.UTC),
            "U", {}, primary_doctor_id=other_doctor.doctor_id,
        )
        self.ctx.patients.add(other_patient)
        doctor_user = h.User("assigned-doctor", ["doctor", "clerk"], person_id=self.doctor.doctor_id)
        self.ctx.auth.register_user(doctor_user, "test-password")
        self.ctx.auth.authenticate(doctor_user.user_id, "test-password")
        start = datetime.now(h.UTC) + timedelta(days=1)

        with self.assertRaises(h.AuthorizationError):
            self.ctx.appt_svc.book(doctor_user, other_patient.patient_id,
                                   other_doctor.doctor_id, self.dept.dept_id,
                                   start, start + timedelta(minutes=30), "test")
        with self.assertRaises(h.AuthorizationError):
            self.ctx.rec_svc.ensure_record(doctor_user, other_patient.patient_id)
        with self.assertRaises(h.AuthorizationError):
            self.ctx.rec_svc.append_entry(doctor_user, other_patient.patient_id,
                                          "visit", "wrong patient", other_doctor.doctor_id)
        appointment = self.ctx.appt_svc.book(
            self.admin, other_patient.patient_id, other_doctor.doctor_id,
            self.dept.dept_id, start, start + timedelta(minutes=30), "test",
        )
        with self.assertRaises(h.AuthorizationError):
            self.ctx.appt_svc.complete(doctor_user, appointment.appt_id)
        self.assertEqual(len(list(self.ctx.records.all())), 0)
        self.assertEqual(appointment.status, "scheduled")

    def test_doctor_cannot_claim_another_author(self):
        doctor_user = h.User("assigned-doctor", ["doctor"], person_id=self.doctor.doctor_id)
        self.ctx.auth.register_user(doctor_user, "test-password")
        self.ctx.auth.authenticate(doctor_user.user_id, "test-password")
        with self.assertRaises(h.AuthorizationError):
            self.ctx.rec_svc.append_entry(doctor_user, self.patient.patient_id,
                                          "visit", "test", "someone-else")
        self.assertEqual(len(list(self.ctx.records.all())), 0)
        entry = self.ctx.rec_svc.append_entry(doctor_user, self.patient.patient_id,
                                               "visit", "test", self.doctor.doctor_id)
        self.assertEqual(entry.author_id, self.doctor.doctor_id)

    def test_missing_saved_credentials_are_rejected(self):
        with self.assertRaises(h.ValidationError):
            h.context_from_dict({"users": [{"user_id": "surprise_admin", "roles": ["admin"]}]})

    def test_missing_audit_hash_is_rejected(self):
        self.ctx.bill_svc.invoice(self.admin, self.patient.patient_id, "T", 10, "test")
        data = h.context_to_dict(self.ctx)
        del data["audit"][0]["event_hash"]
        with self.assertRaises(h.ValidationError):
            h.context_from_dict(data)

    def test_failed_save_preserves_previous_file(self):
        with TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
            path = Path(tmp) / "synthetic-hospital-data.json"
            h.save_context_to_file(self.ctx, str(path))
            previous_bytes = path.read_bytes()
            self.patient.contact_info["bad"] = object()
            with self.assertRaises(TypeError):
                h.save_context_to_file(self.ctx, str(path))
            self.assertEqual(path.read_bytes(), previous_bytes)
            self.assertEqual(list(Path(tmp).glob("*.tmp")), [])

    def test_attachment_paths_stay_inside_attachment_folder(self):
        with TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
            root = Path(tmp) / "attachments"
            source = Path(tmp) / "synthetic.txt"
            source.write_text("synthetic test content", encoding="utf-8")
            unusual_patient = h.Patient(
                "person", "Synthetic Patient", datetime(1990, 1, 1, tzinfo=h.UTC),
                "U", {}, patient_id="../outside", primary_doctor_id=self.doctor.doctor_id,
            )
            self.ctx.patients.add(unusual_patient)
            self.ctx.rec_svc._attachments_dir = root
            attachment = self.ctx.rec_svc.add_attachment(
                self.admin, unusual_patient.patient_id, str(source),
            )
            saved = h.resolve_attachment_path(attachment.stored_path, root)
            self.assertTrue(saved.is_file())
            self.assertEqual(saved.read_text(encoding="utf-8"), "synthetic test content")
            with self.assertRaises(h.ValidationError):
                h.resolve_attachment_path("../synthetic.txt", root)
            with self.assertRaises(h.ValidationError):
                h.resolve_attachment_path(str(source), root)


if __name__ == "__main__":
    unittest.main()
