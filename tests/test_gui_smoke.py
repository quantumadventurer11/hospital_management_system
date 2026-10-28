"""Small GUI workflow checks; skipped when Tk has no display."""

import tkinter as tk
from tkinter import ttk
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from hospital.context import create_physician
from hospital.domain import Patient
from hospital.gui import HospitalGUI


def widgets(root, kind):
    found = []
    for child in root.winfo_children():
        if isinstance(child, kind):
            found.append(child)
        found.extend(widgets(child, kind))
    return found


class GuiSmokeTests(unittest.TestCase):
    def setUp(self):
        try:
            self.app = HospitalGUI()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        self.app.withdraw()

    def tearDown(self):
        if hasattr(self, "app"):
            self.app.destroy()

    def login(self, username, password):
        self.app.open_login()
        entries = widgets(self.app.container, ttk.Entry)
        self.assertEqual(len(entries), 2)
        entries[0].insert(0, username)
        entries[1].insert(0, password)
        next(button for button in widgets(self.app.container, ttk.Button)
             if button.cget("text") == "Login").invoke()
        self.app.update_idletasks()

    def test_admin_login_analytics_and_logout(self):
        self.login("admin", "admin123")
        self.assertIs(self.app.current_user, self.app.ctx.users["admin"])
        self.assertEqual(self.app.staff_metric_vars["Patients"].get(), "0")
        self.app.open_analytics(None)
        windows = widgets(self.app, tk.Toplevel)
        self.assertTrue(windows)
        for window in windows:
            window.destroy()
        self.app.logout()
        self.assertIsNone(self.app.current_user)

    def test_synthetic_doctor_reaches_dashboard(self):
        doctor, user = create_physician(
            self.app.ctx, name="Synthetic Doctor",
            dob=datetime(1980, 1, 1, tzinfo=timezone.utc), sex="U",
            email="", specialty="General", license_no="DEMO-ONLY",
            timezone_name="UTC", department_name="Synthetic Department",
            department_location="Demo", username="synthetic_doctor",
            password="demo-password",
        )
        self.login("synthetic_doctor", "demo-password")
        self.assertIs(self.app.current_user, user)
        self.assertEqual(self.app.get_current_doctor(), doctor)
        self.assertTrue(self.app.summary_text.winfo_exists())
        self.assertEqual(self.app.doctor_metric_vars["Assigned patients"].get(), "0")
        self.app.ctx.patients.add(Patient(
            id="synthetic-person", name="Synthetic Patient",
            dob=datetime(2000, 1, 1, tzinfo=timezone.utc), sex="U",
            contact_info={}, patient_id="synthetic-patient",
            primary_doctor_id=doctor.doctor_id,
        ))
        self.app.update_summary()
        self.assertEqual(self.app.doctor_metric_vars["Assigned patients"].get(), "1")

    def test_form_requires_input_then_submits(self):
        received = []
        win = self.app.open_form(
            "Synthetic Form", [{"name": "label", "label": "Label", "required": True}],
            lambda values: received.append(values) or True,
        )
        submit = next(button for button in widgets(win, ttk.Button)
                      if button.cget("text") == "Submit")
        submit.invoke()
        self.assertEqual(received, [])
        self.assertTrue(win.winfo_exists())
        widgets(win, ttk.Entry)[0].insert(0, "Synthetic value")
        submit.invoke()
        self.assertEqual(received, [{"label": "Synthetic value"}])
        self.assertFalse(win.winfo_exists())

    def test_save_requires_active_session_before_opening_dialog(self):
        with patch("hospital.gui_common.filedialog.asksaveasfilename") as choose, \
             patch.object(self.app, "show_message") as message:
            self.app.save_context_dialog()
        choose.assert_not_called()
        message.assert_called_once_with(
            "Sign In Required", "Sign in before saving hospital data.", error=True,
        )
        self.login("admin", "admin123")
        self.app.current_user.clear_sessions()
        with patch("hospital.gui_common.filedialog.asksaveasfilename") as choose, \
             patch.object(self.app, "show_message") as message:
            self.app.save_context_dialog()
        choose.assert_not_called()
        self.assertEqual(message.call_args.args[0], "Sign In Required")

    def test_cancelled_file_dialogs_leave_context_untouched(self):
        self.login("admin", "admin123")
        old_context = self.app.ctx
        old_user = self.app.current_user
        with patch("hospital.gui_common.filedialog.asksaveasfilename", return_value=""), \
             patch("hospital.gui_common.filedialog.askopenfilename", return_value=""), \
             patch.object(self.app, "show_toast") as toast, \
             patch.object(self.app, "show_message") as message:
            self.app.save_context_dialog()
            self.app.load_context_dialog()
        self.assertIs(self.app.ctx, old_context)
        self.assertIs(self.app.current_user, old_user)
        toast.assert_not_called()
        message.assert_not_called()

    def test_save_and_load_dialogs_restore_synthetic_data(self):
        self.login("admin", "admin123")
        patient = Patient(
            id="synthetic-person", name="Synthetic Patient",
            dob=datetime(2000, 1, 1, tzinfo=timezone.utc),
            sex="U", contact_info={}, patient_id="synthetic-patient",
        )
        self.app.ctx.patients.add(patient)
        old_context = self.app.ctx
        with TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
            path = Path(tmp) / "synthetic-hospital-data.json"
            with patch("hospital.gui_common.filedialog.asksaveasfilename", return_value=str(path)), \
                 patch.object(self.app, "show_toast") as toast:
                self.app.save_context_dialog()
            self.assertTrue(path.is_file())
            toast.assert_called_once()
            patient.name = "Changed after save"
            with patch("hospital.gui_common.filedialog.askopenfilename", return_value=str(path)), \
                 patch("hospital.gui_common.messagebox.askyesno", return_value=False) as confirm, \
                 patch.object(self.app, "show_toast") as toast:
                self.app.load_context_dialog()
            confirm.assert_called_once()
            toast.assert_not_called()
            self.assertIs(self.app.ctx, old_context)
            self.assertEqual(self.app.ctx.patients.get("synthetic-patient").name, "Changed after save")
            with patch("hospital.gui_common.filedialog.askopenfilename", return_value=str(path)), \
                 patch("hospital.gui_common.messagebox.askyesno", return_value=True) as confirm, \
                 patch.object(self.app, "show_toast") as toast:
                self.app.load_context_dialog()
            confirm.assert_called_once()
            toast.assert_called_once()
        self.assertIsNot(self.app.ctx, old_context)
        self.assertEqual(self.app.ctx.patients.get("synthetic-patient").name, "Synthetic Patient")
        self.assertIsNone(self.app.current_user)

    def test_invalid_load_keeps_current_session_and_data(self):
        self.login("admin", "admin123")
        old_context = self.app.ctx
        old_user = self.app.current_user
        with TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
            path = Path(tmp) / "invalid.json"
            path.write_text("{invalid", encoding="utf-8")
            with patch("hospital.gui_common.filedialog.askopenfilename", return_value=str(path)), \
                 patch.object(self.app, "show_message") as message, \
                 patch.object(self.app, "show_toast") as toast:
                self.app.load_context_dialog()
            self.assertEqual(message.call_args.args[0], "Load Failed")
            toast.assert_not_called()
        self.assertIs(self.app.ctx, old_context)
        self.assertIs(self.app.current_user, old_user)

    def test_failed_save_preserves_existing_file(self):
        self.login("admin", "admin123")
        with TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
            path = Path(tmp) / "synthetic-hospital-data.json"
            path.write_text("previous synthetic save", encoding="utf-8")
            self.app.ctx.users["admin"].person_id = object()
            with patch("hospital.gui_common.filedialog.asksaveasfilename", return_value=str(path)), \
                 patch.object(self.app, "show_message") as message, \
                 patch.object(self.app, "show_toast") as toast:
                self.app.save_context_dialog()
            self.assertEqual(path.read_text(encoding="utf-8"), "previous synthetic save")
            self.assertEqual(list(Path(tmp).glob("*.tmp")), [])
            self.assertEqual(message.call_args.args[0], "Save Failed")
            toast.assert_not_called()

    def test_new_session_requires_confirmation(self):
        old_context = self.app.ctx
        with patch("hospital.gui_common.messagebox.askyesno", return_value=False), \
             patch.object(self.app, "show_toast") as toast:
            self.app.reset_context()
        self.assertIs(self.app.ctx, old_context)
        toast.assert_not_called()
        with patch("hospital.gui_common.messagebox.askyesno", return_value=True), \
             patch.object(self.app, "show_toast") as toast:
            self.app.reset_context()
        self.assertIsNot(self.app.ctx, old_context)
        self.assertIsNone(self.app.current_user)
        toast.assert_called_once()

    def test_high_contrast_can_be_toggled_and_restored(self):
        original_background = self.app.style.lookup("TFrame", "background")
        self.app.toggle_high_contrast_event()
        self.assertTrue(self.app.high_contrast_var.get())
        self.assertEqual(self.app.style.lookup("TFrame", "background"), "#151515")
        self.app.toggle_high_contrast_event()
        self.assertFalse(self.app.high_contrast_var.get())
        self.assertEqual(self.app.style.lookup("TFrame", "background"), original_background)


if __name__ == "__main__":
    unittest.main()
