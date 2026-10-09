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
        with TemporaryDirectory() as tmp:
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


if __name__ == "__main__":
    unittest.main()
