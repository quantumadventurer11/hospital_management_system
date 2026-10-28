"""Clerk, nurse, billing, and admin Tkinter screens."""
from __future__ import annotations
from datetime import datetime
import tkinter as tk
from tkinter import ttk
from .errors import NotFoundError, ValidationError
from .templates import BILLING_TEMPLATES, BILLING_TEMPLATE_LOOKUP
from .timezones import UTC, get_timezone
from .gui_theme import BACKGROUND, SURFACE, INK


class StaffGuiMixin:
    # ---------- Staff (non-doctor) ----------
    def select_doctor_dialog(self, prompt_title: str="Select Doctor") -> Optional[Doctor]:
        doctors = self.ctx.doctors.all()
        if not doctors:
            self.show_message("No Doctors", "No doctors are registered in the system.", error=True)
            return None
        choices = [(f"Dr. {doc.name} ({doc.specialty})", doc.doctor_id) for doc in doctors]
        fields = [
            {"name": "doctor", "label": "Doctor", "widget": "combobox", "choices": choices, "required": True},
        ]
        win = self.open_form(prompt_title, fields, lambda data: True)
        self.wait_window(win)
        result = getattr(win, "result", None)
        if not result:
            return None
        doctor_id = result.get("doctor")
        try:
            return self.ctx.doctors.get(doctor_id)
        except NotFoundError:
            self.show_message("Error", "Selected doctor no longer exists.", error=True)
            return None

    def select_patient_for_doctor(self, doctor: Doctor, prompt_title: str="Select Patient") -> Optional[Patient]:
        patients = self.ctx.patients.find(primary_doctor_id=doctor.doctor_id)
        if not patients:
            self.show_message("No Patients", "No patients are assigned to this doctor.", error=True)
            return None
        choices = [(f"{pat.name} ({pat.patient_id[:8]})", pat.patient_id) for pat in patients]
        fields = [
            {"name": "patient", "label": "Patient", "widget": "combobox", "choices": choices, "required": True},
        ]
        win = self.open_form(prompt_title, fields, lambda data: True)
        self.wait_window(win)
        result = getattr(win, "result", None)
        if not result:
            return None
        try:
            return self.ctx.patients.get(result["patient"])
        except NotFoundError:
            self.show_message("Error", "Selected patient no longer exists.", error=True)
            return None

    def clerk_register_patient(self) -> None:
        doctor = self.select_doctor_dialog()
        if not doctor:
            return
        self.open_patient_form(doctor)

    def clerk_schedule_appointment(self) -> None:
        doctor = self.select_doctor_dialog("Select Doctor for Appointment")
        if not doctor:
            return
        self.open_schedule_form(doctor, self.current_user)

    def apply_billing_template_gui(self) -> None:
        patients = self.ctx.patients.all()
        if not patients:
            self.show_message("No Patients", "No patients are available for billing.", error=True)
            return
        patient_choices = sorted(
            [(f"{pat.name} ({pat.patient_id[:8]})", pat.patient_id) for pat in patients],
            key=lambda item: item[0],
        )
        template_choices = [("Select template", "")] + [(tpl["name"], tpl["id"]) for tpl in BILLING_TEMPLATES]
        fields = [
            {"name": "patient", "label": "Patient", "widget": "combobox", "choices": patient_choices, "required": True},
            {"name": "template", "label": "Billing template", "widget": "combobox", "choices": template_choices, "initial": "Select template"},
            {"name": "code", "label": "Billing code override"},
            {"name": "amount", "label": "Amount"},
            {"name": "description", "label": "Description", "widget": "textarea"},
        ]
        def on_submit(values: Dict[str, Any]) -> bool:
            template_id = values.get("template", "")
            template = BILLING_TEMPLATE_LOOKUP.get(template_id) if template_id else None
            if not template:
                raise ValidationError("Please select a billing template.")
            amount_text = values.get("amount", "").strip() or str(template["amount"])
            try:
                amount_val = float(amount_text)
            except ValueError:
                raise ValidationError("Amount must be numeric.")
            code = values.get("code", "").strip() or template["code"]
            description = values.get("description", "").strip() or template["description"]
            try:
                self.ctx.bill_svc.invoice(self.current_user, values["patient"], code, amount_val, description)
            except Exception as exc:
                raise ValidationError(str(exc))
            self.show_toast(f"Invoiced {code} for ${amount_val:.2f}.")
            return True
        self.open_form("Apply Billing Template", fields, on_submit)

    def nurse_refresh_beds(self) -> None:
        self.refresh_staff_metrics()
        if not hasattr(self, "nurse_bed_text") or not self.nurse_bed_text:
            return
        beds = self.ctx.beds.all()
        self.nurse_bed_text.configure(state="normal")
        self.nurse_bed_text.delete("1.0", "end")
        if not beds:
            self.nurse_bed_text.insert("1.0", "No beds configured.")
        else:
            for bed in beds:
                line = f"{bed.bed_id} | room {bed.room_id} | status {bed.status}"
                if bed.occupant_patient_id:
                    try:
                        pat = self.ctx.patients.get(bed.occupant_patient_id)
                        line += f" | patient {pat.name}"
                    except NotFoundError:
                        line += f" | patient {bed.occupant_patient_id}"
                line += "\n"
                self.nurse_bed_text.insert("end", line)
        self.nurse_bed_text.configure(state="disabled")

    def nurse_admit_patient(self) -> None:
        doctor = self.select_doctor_dialog("Select admitting doctor")
        if not doctor:
            return
        patients = self.ctx.patients.find(primary_doctor_id=doctor.doctor_id)
        if not patients:
            self.show_message("No Patients", "Selected doctor has no patients to admit.", error=True)
            return
        beds = [bed for bed in self.ctx.beds.all() if bed.status == "free"]
        if not beds:
            self.show_message("No Beds", "No free beds are available.", error=True)
            return
        patient_choices = [(f"{pat.name} ({pat.patient_id[:8]})", pat.patient_id) for pat in patients]
        bed_choices = [(f"{bed.bed_id} ({bed.room_id})", bed.bed_id) for bed in beds]
        start_default = datetime.now(get_timezone(doctor.timezone)).strftime("%Y-%m-%d %H:%M")
        fields = [
            {"name": "patient", "label": "Patient", "widget": "combobox", "choices": patient_choices, "required": True},
            {"name": "bed", "label": "Bed", "widget": "combobox", "choices": bed_choices, "required": True},
            {"name": "start", "label": "Start (YYYY-MM-DD HH:MM)", "initial": start_default, "required": True},
            {"name": "hours", "label": "Duration hours", "initial": "24", "required": True},
        ]
        def on_submit(values: Dict[str, Any]) -> bool:
            try:
                start_dt = self.parse_datetime(values["start"], doctor.timezone)
            except ValidationError as exc:
                raise exc
            try:
                hours = int(values["hours"])
            except ValueError:
                raise ValidationError("Hours must be an integer.")
            try:
                self.ctx.ip_svc.admit(
                    self.current_user,
                    values["patient"],
                    doctor.doctor_id,
                    hours=hours,
                    start_dt=start_dt,
                )
            except Exception as exc:
                raise ValidationError(str(exc))
            self.show_toast("Patient admitted.")
            self.nurse_refresh_beds()
            return True
        self.open_form("Admit Patient", fields, on_submit)

    def nurse_discharge_bed(self) -> None:
        occupied = [bed for bed in self.ctx.beds.all() if bed.status != "free"]
        if not occupied:
            self.show_message("No Occupied Beds", "All beds are free or unavailable.", error=True)
            return
        bed_choices = [(f"{bed.bed_id} ({bed.status})", bed.bed_id) for bed in occupied]
        fields = [
            {"name": "bed", "label": "Bed", "widget": "combobox", "choices": bed_choices, "required": True},
        ]
        def on_submit(values: Dict[str, Any]) -> bool:
            try:
                self.ctx.ip_svc.discharge(self.current_user, values["bed"])
            except Exception as exc:
                raise ValidationError(str(exc))
            self.show_toast("Bed set to cleaning.")
            self.nurse_refresh_beds()
            return True
        self.open_form("Discharge Bed", fields, on_submit)

    def admin_view_audit(self) -> None:
        events = self.ctx.audit.events[-100:]
        win = tk.Toplevel(self)
        win.title("Audit Log")
        text = tk.Text(win, wrap="word", height=25, width=80)
        text.pack(fill="both", expand=True)
        if not events:
            text.insert("1.0", "No audit events recorded.")
        else:
            for ev in events:
                line = f"{ev.when.strftime('%Y-%m-%d %H:%M UTC')} | {ev.who} | {ev.what}\n"
                text.insert("end", line)
        text.configure(state="disabled")
        ttk.Button(win, text="Close", command=win.destroy).pack(pady=6)

    def admin_reset_password_gui(self) -> None:
        users = sorted(self.ctx.users.values(), key=lambda u: u.user_id)
        if len(users) <= 1:
            self.show_message("No Users", "No other users available to reset.", error=True)
            return
        choices = [(f"{user.user_id} ({'/'.join(user.roles)})", user.user_id) for user in users if user.user_id != self.current_user.user_id]
        if not choices:
            self.show_message("No Users", "No other users available to reset.", error=True)
            return
        fields = [
            {"name": "user", "label": "User", "widget": "combobox", "choices": choices, "required": True},
            {"name": "password", "label": "New Password", "widget": "entry", "show": "*", "required": True},
            {"name": "confirm", "label": "Confirm Password", "widget": "entry", "show": "*", "required": True},
        ]
        def on_submit(values: Dict[str, Any]) -> bool:
            if values["password"] != values["confirm"]:
                raise ValidationError("Passwords do not match.")
            if len(values["password"]) < 4:
                raise ValidationError("Password must be at least four characters.")
            target = self.ctx.users.get(values["user"])
            if not target:
                raise ValidationError("User not found.")
            self.ctx.auth.reset_password(target, values["password"])
            self.show_toast(f"Password updated for {target.user_id}.")
            return True
        self.open_form("Reset User Password", fields, on_submit)

    def open_analytics(self, doctor: Optional[Doctor]) -> None:
        win = tk.Toplevel(self)
        if doctor:
            win.title(f"Analytics - Dr. {doctor.name}")
        else:
            win.title("Analytics Dashboard")
        win.geometry("860x620")
        win.configure(bg="#151515" if self.high_contrast_var.get() else BACKGROUND)
        shell = ttk.Frame(win, padding=22)
        shell.pack(fill="both", expand=True)
        ttk.Label(shell, text="INSIGHTS  /  SYNTHETIC DATA",
                  style="Eyebrow.TLabel").pack(anchor="w")
        ttk.Label(shell, text="Operations overview",
                  style="Title.TLabel").pack(anchor="w", pady=(5, 0))
        ttk.Label(shell, text="Review upcoming visits, billing, and recorded activity.",
                  style="Subtitle.TLabel").pack(anchor="w", pady=(6, 18))
        ttk.Button(shell, text="Close", command=win.destroy).pack(
            side="bottom", anchor="e", pady=(14, 0))
        notebook = ttk.Notebook(shell)
        notebook.pack(fill="both", expand=True)

        def analytics_text(parent: ttk.Frame) -> tk.Text:
            text_bg = "#202020" if self.high_contrast_var.get() else SURFACE
            text_fg = "#FFFFFF" if self.high_contrast_var.get() else INK
            widget = tk.Text(parent, wrap="word", height=12, bg=text_bg, fg=text_fg,
                             relief="flat", borderwidth=0, font=("Consolas", 10),
                             padx=14, pady=14)
            widget.pack(fill="both", expand=True)
            return widget

        # Schedule tab
        schedule_frame = ttk.Frame(notebook, style="Card.TFrame", padding=8)
        notebook.add(schedule_frame, text="Schedule")
        schedule_text = analytics_text(schedule_frame)
        now = datetime.now(UTC)
        appointments = sorted(
            [
                appt for appt in self.ctx.appts.all()
                if appt.end_dt >= now and (not doctor or appt.doctor_id == doctor.doctor_id)
            ],
            key=lambda a: a.start_dt,
        )
        if appointments:
            daily_counts: Dict[str, int] = {}
            for appt in appointments:
                try:
                    doc = self.ctx.doctors.get(appt.doctor_id)
                    pat = self.ctx.patients.get(appt.patient_id)
                except NotFoundError:
                    continue
                doc_tz = get_timezone(doc.timezone)
                start_local = appt.start_dt.astimezone(doc_tz)
                day_key = start_local.strftime("%Y-%m-%d")
                daily_counts[day_key] = daily_counts.get(day_key, 0) + 1
                line = (
                    f"{start_local.strftime('%Y-%m-%d %H:%M %Z')} | "
                    f"Dr. {doc.name} with {pat.name} | status: {appt.status}\n"
                )
                schedule_text.insert("end", line)
            schedule_text.insert("end", "\nDaily totals:\n")
            for day, count in sorted(daily_counts.items()):
                schedule_text.insert("end", f"- {day}: {count} appointment(s)\n")
        else:
            schedule_text.insert("1.0", "No upcoming appointments found.")
        schedule_text.configure(state="disabled")

        # Billing tab
        billing_frame = ttk.Frame(notebook, style="Card.TFrame", padding=8)
        notebook.add(billing_frame, text="Billing")
        billing_text = analytics_text(billing_frame)
        accounts = self.ctx.billing.all()
        if doctor:
            doctor_patients = {p.patient_id for p in self.ctx.patients.find(primary_doctor_id=doctor.doctor_id)}
            accounts = [acct for acct in accounts if acct.patient_id in doctor_patients]
        rows = []
        total_balance = 0.0
        for acct in accounts:
            try:
                pat = self.ctx.patients.get(acct.patient_id)
                name = pat.name
            except NotFoundError:
                name = acct.patient_id
            balance = acct.balance()
            total_balance += balance
            rows.append((balance, name, len(acct.charges), len(acct.payments)))
        rows.sort(reverse=True)
        billing_text.insert("end", f"Accounts: {len(rows)} | Outstanding balance: ${total_balance:.2f}\n\n")
        if rows:
            for balance, name, charges, payments in rows:
                billing_text.insert(
                    "end",
                    f"{name}: balance ${balance:.2f} (charges {charges}, payments {payments})\n",
                )
        else:
            billing_text.insert("end", "No billing accounts available for this view.")
        billing_text.configure(state="disabled")

        # Audit tab
        audit_frame = ttk.Frame(notebook, style="Card.TFrame", padding=8)
        notebook.add(audit_frame, text="Audit")
        audit_text = analytics_text(audit_frame)
        events = self.ctx.audit.events
        if doctor:
            audit_text.insert("end", "Showing global audit activity.\n\n")
        if events:
            counts: Dict[str, int] = {}
            for ev in events:
                counts[ev.what] = counts.get(ev.what, 0) + 1
            audit_text.insert("end", "Event totals:\n")
            for action, count in sorted(counts.items(), key=lambda x: x[1], reverse=True):
                audit_text.insert("end", f"- {action}: {count}\n")
            audit_text.insert("end", "\nRecent events:\n")
            for ev in events[-20:]:
                audit_text.insert(
                    "end",
                    f"{ev.when.strftime('%Y-%m-%d %H:%M UTC')} | {ev.who} | {ev.what}\n",
                )
        else:
            audit_text.insert("1.0", "No audit events recorded.")
        audit_text.configure(state="disabled")

        win.transient(self)
        win.grab_set()

    def show_staff_view(self) -> None:
        self.clear_container()
        roles = self.current_user.roles if self.current_user else []
        self.nurse_bed_text = None
        ttk.Label(self.container, text="HOSPITAL OPERATIONS  /  STAFF WORKSPACE",
                  style="Eyebrow.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))
        ttk.Label(self.container, text=f"Welcome, {self.current_user.user_id}",
                  style="Title.TLabel").grid(row=1, column=0, sticky="w")
        top_bar = ttk.Frame(self.container)
        top_bar.grid(row=1, column=1, sticky="e")
        ttk.Button(top_bar, text="Change Password", command=self.change_password_gui).pack(side="right", padx=(6, 0))
        ttk.Button(top_bar, text="Log Out", command=self.logout).pack(side="right")
        ttk.Label(self.container, text="Choose a role tab to manage the synthetic demo workflow.",
                  style="Subtitle.TLabel").grid(row=2, column=0, columnspan=2,
                                                 sticky="w", pady=(6, 18))

        metrics = self._staff_metrics()
        self.staff_metric_vars = {}
        metric_row = ttk.Frame(self.container)
        metric_row.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 18))
        for index, (label, value) in enumerate(metrics):
            metric_row.columnconfigure(index, weight=1)
            card = ttk.Frame(metric_row, style="Card.TFrame", padding=(18, 12))
            card.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 6, 0))
            ttk.Label(card, text=label.upper(), style="CardMuted.TLabel").pack(anchor="w")
            variable = tk.StringVar(value=str(value))
            self.staff_metric_vars[label] = variable
            ttk.Label(card, textvariable=variable, style="Metric.TLabel").pack(anchor="w", pady=(4, 0))

        notebook = ttk.Notebook(self.container)
        notebook.grid(row=4, column=0, columnspan=2, sticky="nsew")
        self.container.rowconfigure(4, weight=1)
        self.container.columnconfigure(0, weight=1)
        self.container.columnconfigure(1, weight=1)

        if "clerk" in roles or "admin" in roles:
            clerk_tab = ttk.Frame(notebook, style="Card.TFrame", padding=24)
            notebook.add(clerk_tab, text="Clerk")
            ttk.Label(clerk_tab, text="Front desk", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
            ttk.Label(clerk_tab, text="Register patients and coordinate visits for a clinician.",
                      style="CardMuted.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(5, 20))
            ttk.Button(clerk_tab, text="Register Patient", style="Primary.TButton",
                       command=self.clerk_register_patient).grid(row=2, column=0, sticky="w", padx=(0, 10))
            ttk.Button(clerk_tab, text="Schedule Appointment",
                       command=self.clerk_schedule_appointment).grid(row=2, column=1, sticky="w")

        if "nurse" in roles or "admin" in roles:
            nurse_tab = ttk.Frame(notebook, style="Card.TFrame", padding=24)
            notebook.add(nurse_tab, text="Nurse")
            ttk.Label(nurse_tab, text="Inpatient beds", style="CardTitle.TLabel").grid(
                row=0, column=0, columnspan=3, sticky="w")
            ttk.Label(nurse_tab, text="Review bed status and coordinate admissions.",
                      style="CardMuted.TLabel").grid(row=1, column=0, columnspan=3,
                                                       sticky="w", pady=(5, 20))
            ttk.Button(nurse_tab, text="Admit Patient", style="Primary.TButton",
                       command=self.nurse_admit_patient).grid(row=2, column=0, sticky="w", padx=(0, 10))
            ttk.Button(nurse_tab, text="Discharge Bed",
                       command=self.nurse_discharge_bed).grid(row=2, column=1, sticky="w", padx=(0, 10))
            ttk.Button(nurse_tab, text="Refresh Bed Status",
                       command=self.nurse_refresh_beds).grid(row=2, column=2, sticky="w")
            text_bg = "#202020" if self.high_contrast_var.get() else SURFACE
            text_fg = "#FFFFFF" if self.high_contrast_var.get() else INK
            self.nurse_bed_text = tk.Text(nurse_tab, height=10, width=50,
                                          bg=text_bg, fg=text_fg, relief="flat",
                                          font=("Consolas", 10), padx=10, pady=10)
            self.nurse_bed_text.grid(row=3, column=0, columnspan=3, pady=(18, 0), sticky="nsew")
            nurse_tab.rowconfigure(3, weight=1)
            nurse_tab.columnconfigure(2, weight=1)
            self.nurse_refresh_beds()

        if "admin" in roles:
            admin_tab = ttk.Frame(notebook, style="Card.TFrame", padding=24)
            notebook.add(admin_tab, text="Admin")
            ttk.Label(admin_tab, text="Administration", style="CardTitle.TLabel").grid(
                row=0, column=0, columnspan=2, sticky="w")
            ttk.Label(admin_tab, text="Review activity and manage demonstration accounts and billing.",
                      style="CardMuted.TLabel").grid(row=1, column=0, columnspan=2,
                                                       sticky="w", pady=(5, 20))
            ttk.Button(admin_tab, text="Open Analytics Dashboard", style="Primary.TButton",
                       command=lambda: self.open_analytics(None)).grid(
                           row=2, column=0, sticky="ew", padx=(0, 10), pady=5)
            ttk.Button(admin_tab, text="View Audit Log", command=self.admin_view_audit).grid(
                row=2, column=1, sticky="ew", pady=5)
            ttk.Button(admin_tab, text="Reset User Password", command=self.admin_reset_password_gui).grid(
                row=3, column=0, sticky="ew", padx=(0, 10), pady=5)
            ttk.Button(admin_tab, text="Apply Billing Template", command=self.apply_billing_template_gui).grid(
                row=3, column=1, sticky="ew", pady=5)
            admin_tab.columnconfigure(0, weight=1)
            admin_tab.columnconfigure(1, weight=1)

        if notebook.index("end") == 0:
            ttk.Label(self.container, text="No staff tools available for your roles.",
                      wraplength=500).grid(row=5, column=0, pady=20, sticky="w")

    def _staff_metrics(self):
        return (
            ("Patients", len(tuple(self.ctx.patients.all()))),
            ("Scheduled visits", sum(1 for appt in self.ctx.appts.all()
                                     if appt.status == "scheduled")),
            ("Available beds", sum(1 for bed in self.ctx.beds.all()
                                    if bed.status == "free")),
        )

    def refresh_staff_metrics(self) -> None:
        variables = getattr(self, "staff_metric_vars", {})
        for label, value in self._staff_metrics():
            if label in variables:
                variables[label].set(str(value))


    def logout(self) -> None:
        if self.current_user:
            self.current_user.clear_sessions()
        self.current_user = None
        self.show_start()
