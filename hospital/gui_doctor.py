"""Login and clinician-facing Tkinter screens."""
from __future__ import annotations
from datetime import datetime, timedelta
from pathlib import Path
import os
import subprocess
import sys
import uuid
import tkinter as tk
from tkinter import ttk, filedialog
from .attachments import resolve_attachment_path
from .cli import build_physician_summary
from .context import create_physician, create_patient, suggest_appointment_slots
from .domain import Department, TimeBlock
from .errors import NotFoundError, ValidationError
from .persistence import datetime_from_iso
from .templates import (NOTE_TEMPLATES, NOTE_TEMPLATE_LOOKUP,
                        REMINDER_TEMPLATES, REMINDER_TEMPLATE_LOOKUP)
from .timezones import TIMEZONE_CHOICES, UTC, get_timezone
from .gui_theme import SURFACE, INK


class DoctorGuiMixin:
    # ---------- Authentication ----------
    def open_login(self) -> None:
        self.clear_container()
        ttk.Label(self.container, text="WELCOME BACK  /  STAFF ACCESS",
                  style="Eyebrow.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(16, 12))
        ttk.Label(self.container, text="Sign in to your workspace",
                  style="Title.TLabel").grid(row=1, column=0, columnspan=2, sticky="w")
        ttk.Label(self.container, text="Use a demonstration account to explore the local prototype.",
                  style="Subtitle.TLabel").grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 28))
        card = ttk.Frame(self.container, style="Card.TFrame", padding=30)
        card.grid(row=3, column=0, columnspan=2, sticky="ew")
        card.columnconfigure(1, weight=1)
        ttk.Label(card, text="Staff login", style="CardTitle.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 22))
        ttk.Label(card, text="Username", style="Card.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 18))
        username_var = tk.StringVar()
        username_entry = ttk.Entry(card, textvariable=username_var, width=36)
        username_entry.grid(row=1, column=1, sticky="ew")
        ttk.Label(card, text="Password", style="Card.TLabel").grid(
            row=2, column=0, sticky="w", pady=(14, 0), padx=(0, 18))
        password_var = tk.StringVar()
        password_entry = ttk.Entry(card, textvariable=password_var, show="*")
        password_entry.grid(row=2, column=1, sticky="ew", pady=(14, 0))
        username_entry.focus_set()

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

        button_bar = ttk.Frame(card, style="Card.TFrame")
        button_bar.grid(row=3, column=0, columnspan=2, pady=(24, 0), sticky="e")
        ttk.Button(button_bar, text="Back", command=self.show_start).pack(side="right", padx=(6, 0))
        ttk.Button(button_bar, text="Login", style="Primary.TButton",
                   command=attempt_login).pack(side="right")

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
        ttk.Label(self.container, text="CLINICIAN WORKSPACE  /  OVERVIEW",
                  style="Eyebrow.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))
        ttk.Label(self.container, text=f"Dr. {doctor.name}",
                  style="Title.TLabel").grid(row=1, column=0, sticky="w")
        ttk.Button(self.container, text="Log Out", command=self.logout).grid(row=1, column=1, sticky="e")
        ttk.Label(self.container, text=f"{doctor.specialty or 'Clinical care'}  •  {doctor.timezone}",
                  style="Subtitle.TLabel").grid(row=2, column=0, sticky="w", pady=(6, 18))

        metrics = self._doctor_metrics(doctor)
        self.doctor_metric_vars = {}
        metric_row = ttk.Frame(self.container)
        metric_row.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 18))
        for index, (label, value) in enumerate(metrics):
            metric_row.columnconfigure(index, weight=1)
            card = ttk.Frame(metric_row, style="Card.TFrame", padding=(18, 12))
            card.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 6, 0))
            ttk.Label(card, text=label.upper(), style="CardMuted.TLabel").pack(anchor="w")
            variable = tk.StringVar(value=str(value))
            self.doctor_metric_vars[label] = variable
            ttk.Label(card, textvariable=variable, style="Metric.TLabel").pack(anchor="w", pady=(4, 0))

        actions = ttk.Frame(self.container, style="Card.TFrame", padding=18)
        actions.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 18))
        ttk.Label(actions, text="Quick actions", style="CardTitle.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 12))
        controls = (
            ("Register Patient", self.register_patient_gui, "Primary.TButton"),
            ("Schedule Appointment", self.schedule_appointment_gui, "Primary.TButton"),
            ("Record Note", self.record_note_gui, "TButton"),
            ("Add Availability", self.add_availability_gui, "TButton"),
            ("Attach Document", self.attach_document_gui, "TButton"),
            ("View Attachments", self.view_attachments_gui, "TButton"),
            ("Add Reminder", self.add_reminder_gui, "TButton"),
            ("Analytics", lambda d=doctor: self.open_analytics(d), "TButton"),
            ("Edit Profile", self.edit_doctor_profile, "TButton"),
            ("Change Password", self.change_password_gui, "TButton"),
            ("Refresh Summary", self.update_summary, "TButton"),
        )
        for index, (label, command, style) in enumerate(controls):
            column, row = index % 4, index // 4 + 1
            actions.columnconfigure(column, weight=1)
            ttk.Button(actions, text=label, style=style, command=command).grid(
                row=row, column=column, sticky="ew", padx=5, pady=5)

        summary_frame = ttk.Frame(self.container, style="Card.TFrame", padding=18)
        summary_frame.grid(row=5, column=0, columnspan=2, sticky="nsew")
        self.container.rowconfigure(5, weight=1)
        ttk.Label(summary_frame, text="Care summary", style="CardTitle.TLabel").pack(anchor="w", pady=(0, 10))
        text_bg = "#202020" if self.high_contrast_var.get() else SURFACE
        text_fg = "#FFFFFF" if self.high_contrast_var.get() else INK
        self.summary_text = tk.Text(summary_frame, wrap="word", height=10,
                                    bg=text_bg, fg=text_fg, relief="flat", borderwidth=0,
                                    font=("Consolas", 10), padx=8, pady=8)
        scrollbar = ttk.Scrollbar(summary_frame, orient="vertical", command=self.summary_text.yview)
        self.summary_text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.summary_text.pack(side="left", fill="both", expand=True)
        self.update_summary()

    def _doctor_metrics(self, doctor: Doctor):
        patients = [patient for patient in self.ctx.patients.all()
                    if patient.primary_doctor_id == doctor.doctor_id]
        patient_ids = {patient.patient_id for patient in patients}
        return (
            ("Assigned patients", len(patients)),
            ("Scheduled visits", sum(1 for appt in self.ctx.appts.all()
                                      if appt.doctor_id == doctor.doctor_id and appt.status == "scheduled")),
            ("Patient records", sum(1 for record in self.ctx.records.all()
                                    if record.patient_id in patient_ids)),
        )

    def update_summary(self) -> None:
        self.refresh_staff_metrics()
        doctor = self.get_current_doctor()
        if not doctor or not self.summary_text:
            return
        for label, value in self._doctor_metrics(doctor):
            variable = getattr(self, "doctor_metric_vars", {}).get(label)
            if variable is not None:
                variable.set(str(value))
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
        record = self.ctx.rec_svc.ensure_record(self.current_user, patient.patient_id)
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
        try:
            path = resolve_attachment_path(attachment.stored_path)
        except ValidationError as exc:
            self.show_message("Invalid Attachment", str(exc), error=True)
            return
        if not path.is_file():
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
