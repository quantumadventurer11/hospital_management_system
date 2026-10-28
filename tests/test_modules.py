"""Checks that the extracted modules and legacy entry point share one model."""

import unittest
from datetime import datetime, timezone

import hospital_management_system as app
from hospital.domain import Patient, Schedule, TimeBlock
from hospital.errors import ValidationError
from hospital.repositories import PatientRepo
from hospital.context import SystemContext
from hospital.persistence import context_from_dict, context_to_dict
from hospital.services import AppointmentService, MedicalRecordService
from hospital.cli import run_cli
from hospital.demo import run_demo, run_smoke_tests
from hospital.gui import HospitalGUI


class ModuleBoundaryTests(unittest.TestCase):
    def test_legacy_imports_reexport_the_module_classes(self):
        self.assertIs(app.Patient, Patient)
        self.assertIs(app.PatientRepo, PatientRepo)
        self.assertIs(app.Schedule, Schedule)
        self.assertIs(app.ValidationError, ValidationError)
        self.assertIs(app.SystemContext, SystemContext)
        self.assertIs(app.context_to_dict, context_to_dict)
        self.assertIs(app.context_from_dict, context_from_dict)
        self.assertIs(app.run_cli, run_cli)
        self.assertIs(app.run_demo, run_demo)
        self.assertIs(app.run_smoke_tests, run_smoke_tests)
        self.assertIs(app.HospitalGUI, HospitalGUI)

    def test_direct_module_objects_survive_existing_save_format(self):
        ctx = app.initialize_system(seed_defaults=False)
        patient = Patient(
            id="person-1", name="Synthetic Patient",
            dob=datetime(2000, 1, 1, tzinfo=timezone.utc),
            sex="X", contact_info={}, patient_id="patient-1",
        )
        ctx.patients.add(patient)
        self.assertIsInstance(ctx.appt_svc, AppointmentService)
        self.assertIsInstance(ctx.rec_svc, MedicalRecordService)
        restored = context_from_dict(context_to_dict(ctx))
        saved = restored.patients.get("patient-1")
        self.assertIsInstance(saved, Patient)
        self.assertEqual(saved.name, "Synthetic Patient")
        self.assertEqual(saved.dob, patient.dob)

    def test_direct_schedule_objects_obey_existing_overlap_policy(self):
        start = datetime(2026, 1, 1, 10, tzinfo=timezone.utc)
        first = TimeBlock(start, start.replace(hour=11), "first", "appt")
        second = TimeBlock(start.replace(hour=10, minute=30), start.replace(hour=11, minute=30), "second", "appt")
        schedule = Schedule()
        schedule.add_block(first)
        self.assertFalse(schedule.is_free((second.start_dt, second.end_dt)))
        self.assertEqual(schedule.protected_view, (first,))


if __name__ == "__main__":
    unittest.main()
