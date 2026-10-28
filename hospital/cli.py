"""Interactive text menu for the educational demo."""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
try:
    from getpass import getpass
except Exception:
    getpass = None  # type: ignore
from .context import (SystemContext, initialize_system, create_physician,
                      create_patient)
from .domain import Doctor, Patient, TimeBlock
from .errors import (AuthorizationError, NotFoundError, SchedulingConflictError,
                     TimezoneError, ValidationError)
from .security import AuthService, User
from .templates import format_section
from .timezones import TIMEZONE_CHOICES, UTC, get_timezone

def prompt_input(message: str, *, required: bool=False, default: Optional[str]=None) -> str:
    suffix = ""
    if default is not None:
        suffix = f" [{default}]"
    prompt_msg = f"{message}{suffix}: "
    while True:
        value = input(prompt_msg).strip()
        if not value and default is not None:
            return default
        if value or not required:
            return value
        print("A value is required. Please try again.")

def prompt_password(message: str) -> str:
    while True:
        if getpass:
            value = getpass(f"{message}: ")
        else:
            value = input(f"{message}: ")
        value = value.strip()
        if value:
            return value
        print("Password cannot be empty. Please try again.")

def prompt_new_password() -> str:
    while True:
        pwd = prompt_password("New password")
        confirm = prompt_password("Confirm password")
        if pwd != confirm:
            print("Passwords do not match. Try again.")
            continue
        if len(pwd) < 4:
            print("Password must be at least 4 characters.")
            continue
        return pwd

def prompt_date(message: str) -> datetime:
    while True:
        raw = prompt_input(message, required=True)
        try:
            parsed = datetime.strptime(raw, "%Y-%m-%d")
            return parsed.replace(tzinfo=UTC)
        except ValueError:
            print("Use YYYY-MM-DD (e.g., 1980-05-17).")

def prompt_datetime_local(message: str, tzinfo) -> datetime:
    while True:
        raw = prompt_input(message, required=True)
        try:
            parsed = datetime.strptime(raw, "%Y-%m-%d %H:%M")
            return parsed.replace(tzinfo=tzinfo)
        except ValueError:
            print("Use YYYY-MM-DD HH:MM (e.g., 2025-10-12 09:30).")

def register_physician(ctx: SystemContext, existing_user: Optional[User]=None) -> Tuple[Doctor, User]:
    print("Welcome! Let's set up your physician profile.\n")
    name = prompt_input("Physician name", required=True)
    dob = prompt_date("Date of birth (YYYY-MM-DD)")
    sex = prompt_input("Sex (M/F/X)", default="U").upper() or "U"
    email = prompt_input("Email address", default="")
    specialty = prompt_input("Specialty", default="Family Medicine")
    license_no = prompt_input("License number", default="N/A")

    print("\nSelect preferred timezone:")
    for idx, (label, value) in enumerate(TIMEZONE_CHOICES, start=1):
        print(f"{idx}. {label} ({value})")
    while True:
        tz_choice = prompt_input("Timezone number", default="1")
        if tz_choice.isdigit():
            pos = int(tz_choice)
            if 1 <= pos <= len(TIMEZONE_CHOICES):
                tz_name = TIMEZONE_CHOICES[pos - 1][1]
                break
        print("Please choose a valid option.")

    dept_name = prompt_input("Department name", default="General Practice")
    dept_location = prompt_input("Department location", default="Virtual Clinic")
    username = None
    password = None
    existing = existing_user
    if existing is None:
        while True:
            candidate = prompt_input("Choose a login name", required=True)
            if candidate in ctx.users:
                print("That username is already taken.")
                continue
            username = candidate
            break
        password = prompt_new_password()
    else:
        username = existing.user_id
    doctor, user = create_physician(
        ctx,
        name=name,
        dob=dob,
        sex=sex,
        email=email,
        specialty=specialty,
        license_no=license_no,
        timezone_name=tz_name,
        department_name=dept_name,
        department_location=dept_location,
        username=username,
        password=password,
        existing_user=existing,
    )

    print(f"\nGreat! Dr. {doctor.name} is ready. Your doctor id is {doctor.doctor_id}.\n")
    return doctor, user

def register_patient(ctx: SystemContext, doctor: Doctor) -> None:
    print("\n--- Register a new patient ---")
    name = prompt_input("Patient name", required=True)
    dob = prompt_date("Date of birth (YYYY-MM-DD)")
    sex = prompt_input("Sex (M/F/X)", default="U").upper() or "U"
    email = prompt_input("Email address", default="")
    allergies_raw = prompt_input("Allergies (comma separated)", default="")
    allergies = [a.strip() for a in allergies_raw.split(",") if a.strip()]
    wants_insurance = prompt_input("Does the patient have insurance? (y/n)", default="y").lower()
    if wants_insurance.startswith("y"):
        providers = ctx.providers.all()
        if not providers:
            print("No insurance providers configured. Skipping insurance capture.\n")
            insurance_provider = None
            plan_name = ""
            member_no = ""
            copay_val = 0.2
        else:
            print("\nChoose an insurance provider:")
            for idx, provider in enumerate(providers, start=1):
                print(f"{idx}. {provider.name} ({provider.country})")
            provider_choice: Optional[InsuranceProvider] = None
            while True:
                selection = prompt_input("Provider number", required=True)
                if not selection.isdigit():
                    print("Enter a number from the list.")
                    continue
                position = int(selection)
                if 1 <= position <= len(providers):
                    provider_choice = providers[position - 1]
                    break
                print("Choice out of range.")
            if provider_choice:
                plan_name = prompt_input("Plan name", default="Standard")
                member_no = prompt_input("Member number", required=True)
                while True:
                    copay_raw = prompt_input("Copay percent (0.0-1.0)", default="0.2")
                    try:
                        copay_val = float(copay_raw)
                        if not 0 <= copay_val <= 1:
                            raise ValueError("Copay must be between 0 and 1.")
                        break
                    except ValueError as exc:
                        print(f"Invalid value: {exc}")
                insurance_provider = provider_choice.provider_id
                print(f"Insurance recorded with provider {provider_choice.name}.\n")
            else:
                insurance_provider = None
                plan_name = ""
                member_no = ""
                copay_val = 0.2
    else:
        insurance_provider = None
        plan_name = ""
        member_no = ""
        copay_val = 0.2

    patient = create_patient(
        ctx,
        doctor,
        name=name,
        dob=dob,
        sex=sex,
        email=email,
        allergies=allergies,
        insurance_provider_id=insurance_provider,
        insurance_plan=plan_name,
        insurance_member_no=member_no,
        insurance_copay=copay_val,
    )
    print(f"Patient registered with id {patient.patient_id}.\n")

def add_availability(ctx: SystemContext, doctor: Doctor) -> None:
    print("\n--- Add availability ---")
    tz = get_timezone(doctor.timezone)
    start = prompt_datetime_local("Start (YYYY-MM-DD HH:MM)", tz)
    duration_minutes = int(prompt_input("Duration in minutes", required=True))
    end = start + timedelta(minutes=duration_minutes)
    label = prompt_input("Label", default="Clinic availability")

    block = TimeBlock(start, end, label, "availability")
    doctor.schedule.add_block(block)
    ctx.doctors.update(doctor)
    print(f"Availability added from {start.strftime('%Y-%m-%d %H:%M %Z')} to {end.strftime('%H:%M %Z')}.\n")

def select_patient(ctx: SystemContext, doctor: Doctor) -> Optional[Patient]:
    patients = ctx.patients.find(primary_doctor_id=doctor.doctor_id)
    if not patients:
        print("You have no patients yet. Register one first.\n")
        return None
    print("\nChoose a patient:")
    for idx, pat in enumerate(patients, start=1):
        print(f"{idx}. {pat.name} (ID: {pat.patient_id[:8]}...) DOB {pat.dob.date()}")
    while True:
        raw = prompt_input("Enter number", required=True)
        if not raw.isdigit():
            print("Enter a number from the list.")
            continue
        index = int(raw)
        if 1 <= index <= len(patients):
            return patients[index - 1]
        print("Choice out of range.")

def schedule_appointment(ctx: SystemContext, doctor: Doctor, user: User) -> None:
    patient = select_patient(ctx, doctor)
    if not patient:
        return
    tz = get_timezone(doctor.timezone)
    print(f"\nScheduling for {patient.name}. Times are interpreted in {doctor.timezone}.")
    start = prompt_datetime_local("Appointment start (YYYY-MM-DD HH:MM)", tz)
    duration_min = int(prompt_input("Duration in minutes", required=True))
    end = start + timedelta(minutes=duration_min)
    reason = prompt_input("Reason for visit", default="Follow-up")
    try:
        appt = ctx.appt_svc.book(user, patient.patient_id, doctor.doctor_id, doctor.department_id or "", start, end, reason)
    except (SchedulingConflictError, TimezoneError, ValidationError) as exc:
        print(f"Could not schedule appointment: {exc}\n")
        return
    print(f"Appointment booked with id {appt.appt_id}. Status: {appt.status}.\n")

def record_note(ctx: SystemContext, doctor: Doctor, user: User) -> None:
    patient = select_patient(ctx, doctor)
    if not patient:
        return
    entry_type = prompt_input("Entry type (visit/diagnosis/prescription/etc.)", default="visit")
    notes = prompt_input("Notes", required=True)
    entry = ctx.rec_svc.append_entry(user, patient.patient_id, entry_type, notes, author_id=doctor.doctor_id)
    print(f"Record entry saved with id {entry.entry_id}.\n")

def change_own_password(user: User, auth: AuthService) -> None:
    print("\n--- Change Password ---")
    current = prompt_password("Current password")
    if not auth.verify_password(user, current):
        print("Incorrect password. No changes made.\n")
        return
    new_password = prompt_new_password()
    if not auth.change_password(user, current, new_password):
        print("Incorrect password. No changes made.\n")
        return
    # Issue a fresh session token so the caller remains authenticated.
    auth.authenticate(user.user_id, new_password)
    print("Password updated.\n")

def reset_user_password(ctx: SystemContext, actor: User) -> None:
    if "admin" not in actor.roles:
        print("Only admins can reset other users' passwords.\n")
        return
    print("\n--- Reset User Password ---")
    usernames = sorted(ctx.users.keys())
    for idx, name in enumerate(usernames, start=1):
        print(f"{idx}. {name}")
    while True:
        choice = prompt_input("Select user", required=True)
        if not choice.isdigit():
            print("Enter a number from the list.")
            continue
        index = int(choice)
        if 1 <= index <= len(usernames):
            target_name = usernames[index - 1]
            break
        print("Choice out of range.")
    target = ctx.users[target_name]
    if target.user_id == actor.user_id:
        print("Use the regular password change option for your own account.\n")
        return
    new_pwd = prompt_new_password()
    ctx.auth.reset_password(target, new_pwd)
    print(f"Password for {target.user_id} has been reset.\n")

def ensure_doctor_profile(ctx: SystemContext, user: User) -> Optional[Doctor]:
    if user.person_id:
        try:
            return ctx.doctors.get(user.person_id)
        except NotFoundError:
            pass
    print("\nNo physician profile is linked to this account.")
    choice = prompt_input("Create one now? (y/n)", default="y").lower()
    if choice.startswith("y"):
        doctor, _ = register_physician(ctx, existing_user=user)
        return doctor
    print("Returning to main menu.\n")
    return None

def build_physician_summary(ctx: SystemContext, doctor: Doctor) -> str:
    patients = ctx.patients.find(primary_doctor_id=doctor.doctor_id)
    patient_lines = [
        f"{pat.name} (age {pat.age()}, allergies: {', '.join(pat.allergies) if pat.allergies else 'none'}, insurance: {pat.insurance.provider.name if pat.insurance else 'self-pay'})"
        for pat in patients
    ] or ["No patients yet."]

    tz = get_timezone(doctor.timezone)
    appts = sorted(
        [a for a in ctx.appts.all() if a.doctor_id == doctor.doctor_id],
        key=lambda a: a.start_dt,
    )
    appt_lines = [
        f"{ctx.patients.get(a.patient_id).name}: {a.start_dt.astimezone(tz).strftime('%Y-%m-%d %H:%M %Z')} ({a.status})"
        for a in appts
    ] or ["No appointments scheduled."]

    record_lines = []
    for pat in patients:
        matches = ctx.records.find(patient_id=pat.patient_id)
        if matches:
            record = matches[0]
            entry_count = len(record.entries)
            attachment_count = len(record.attachments)
            reminder_count = sum(1 for entry in record.entries if entry.type == "reminder")
            if entry_count:
                latest = record.entries[-1]
                record_lines.append(
                    f"{pat.name}: {entry_count} entry(ies) (latest {latest.type}), attachments {attachment_count}, reminders {reminder_count}"
                )
            else:
                record_lines.append(f"{pat.name}: no entries yet, attachments {attachment_count}, reminders {reminder_count}")
        else:
            record_lines.append(f"{pat.name}: no records yet")

    billing_lines = []
    for pat in patients:
        accts = ctx.billing.find(patient_id=pat.patient_id)
        if accts:
            acct = accts[0]
            billing_lines.append(
                f"{pat.name}: balance ${acct.balance()} (charges: {len(acct.charges)}, payments: {len(acct.payments)})"
            )
        else:
            billing_lines.append(f"{pat.name}: no billing activity")

    audit_recent = ctx.audit.events[-5:]
    audit_lines = [
        f"{ev.when.astimezone(tz).strftime('%m-%d %H:%M')}: {ev.what}"
        for ev in audit_recent
    ] or ["No audit events recorded."]

    sections = [
        format_section("Patients", patient_lines),
        format_section("Appointments", appt_lines),
        format_section("Medical Records", record_lines),
        format_section("Billing", billing_lines),
        format_section("Recent Activity", audit_lines),
    ]
    return "\n\n".join(sections)

def physician_loop(ctx: SystemContext, doctor: Doctor, user: User) -> None:
    menu = (
        "\nPhysician workspace - select an option:\n"
        "1. Register new patient\n"
        "2. Add availability\n"
        "3. Schedule appointment\n"
        "4. Record visit note\n"
        "5. View summary\n"
        "6. Change password\n"
        "Q. Log out\n"
    )
    while True:
        try:
            doctor = ctx.doctors.get(doctor.doctor_id)
        except NotFoundError:
            print("Doctor profile missing; logging out.")
            return
        print(menu)
        choice = prompt_input("Choice", required=True).lower()
        if choice in ("q", "quit", "exit"):
            print("Logging out of physician workspace.\n")
            break
        actions = {
            "1": lambda: register_patient(ctx, doctor),
            "2": lambda: add_availability(ctx, doctor),
            "3": lambda: schedule_appointment(ctx, doctor, user),
            "4": lambda: record_note(ctx, doctor, user),
            "5": lambda: print("\n" + build_physician_summary(ctx, doctor) + "\n"),
            "6": lambda: change_own_password(user, ctx.auth),
        }
        action = actions.get(choice)
        if not action:
            print("Please choose a valid option.")
            continue
        try:
            action()
        except AuthorizationError as exc:
            print(f"Action not permitted: {exc}")
        except Exception as exc:
            print(f"An unexpected error occurred: {exc}")

def login_user(ctx: SystemContext) -> Optional[User]:
    print("\n--- Staff login ---")
    for attempt in range(3):
        username = prompt_input("Username", required=True)
        password = prompt_password("Password")
        auth_result = ctx.auth.authenticate(username, password)
        if auth_result:
            user, _token = auth_result
            print(f"\nWelcome, {username}. Roles: {', '.join(user.roles)}.\n")
            return user
        print("Invalid username or password.\n")
    print("Too many failed attempts. Returning to main menu.\n")
    return None

def handle_user_session(ctx: SystemContext, user: User) -> None:
    handled = False
    if "doctor" in user.roles:
        doctor = ensure_doctor_profile(ctx, user)
        if doctor:
            physician_loop(ctx, doctor, user)
            handled = True
    other_roles = [r for r in user.roles if r != "doctor"]
    if not other_roles:
        return
    staff_menu(ctx, user, handled)

def staff_menu(ctx: SystemContext, user: User, prelude_shown: bool) -> None:
    if not prelude_shown:
        print(f"\nLogged in as {user.user_id}. Roles: {', '.join(user.roles)}.\n")
    menu_lines = [
        "1. Change password",
    ]
    actions: Dict[str, Any] = {
        "1": lambda: change_own_password(user, ctx.auth),
    }
    if "admin" in user.roles:
        menu_lines.append("2. Reset another user's password")
        actions["2"] = lambda: reset_user_password(ctx, user)
    menu_lines.append("Q. Log out")
    menu = "\nStaff tools - choose an option:\n" + "\n".join(menu_lines) + "\n"
    while True:
        print(menu)
        choice = prompt_input("Choice", required=True).lower()
        if choice in ("q", "quit", "exit"):
            print("Logging out of staff tools.\n")
            break
        action = actions.get(choice)
        if not action:
            print("Please choose a valid option.")
            continue
        action()

def run_cli() -> None:
    ctx = initialize_system()
    menu_primary = (
        "\nWelcome to the hospital system.\n"
        "1. Log in as staff\n"
        "2. Register a new physician\n"
        "Q. Quit\n"
    )
    while True:
        print(menu_primary)
        choice = prompt_input("Choice", required=True).lower()
        if choice in ("q", "quit", "exit"):
            print("Goodbye!")
            return
        if choice == "2":
            doctor, user = register_physician(ctx)
            physician_loop(ctx, doctor, user)
        elif choice == "1":
            user = login_user(ctx)
            if user:
                handle_user_session(ctx, user)
        else:
            print("Please choose a valid option.")
