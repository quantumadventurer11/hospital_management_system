# Assignment #4: Hospital Management System v2.0
# Developer: Benjamin Charles Brumm
# Student #: W0305413
# Course: Data Movement and Integration
# Instructor: Dr. Cheolsoon Im
# Date Completed: October 12th, 2025

# -----------------------------
# Imports
# -----------------------------

from __future__ import annotations
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import hashlib
import hmac
import secrets
# Prefer stdlib zoneinfo, fall back to backports for older Python versions
try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except Exception:
    from backports.zoneinfo import ZoneInfo, ZoneInfoNotFoundError  # type: ignore
from typing import Any, Callable, ClassVar, Dict, Generic, Iterable, List, Mapping, Optional, Sequence, Tuple, TypeVar
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox, filedialog
# Secure password input when available
try:
    from getpass import getpass
except Exception:
    getpass = None  # type: ignore
# Protocol may live in typing (modern Python) or typing_extensions (older)
try:
    from typing import Protocol, runtime_checkable  # type: ignore
except Exception:
    from typing_extensions import Protocol, runtime_checkable  # type: ignore
import uuid
from types import MappingProxyType

from hospital.errors import (ValidationError, AuthorizationError,
                             SchedulingConflictError, NotFoundError, DuplicateError,
                             TimezoneError)
from hospital.timezones import FALLBACK_TIMEZONES, TIMEZONE_CHOICES, get_timezone, UTC
from hospital.domain import (TimeBlock, Charge, Payment, ConflictPolicy,
                             HardNoOverlapPolicy, AllowBufferPolicy, Person, Patient,
                             Doctor, Department, Appointment, MedicalRecord,
                             RecordEntry, RecordAttachment, Bed, InsuranceProvider,
                             InsurancePolicy, BillingAccount, BillingStrategy,
                             SelfPayStrategy, InsuranceStrategy, Schedule)
from hospital.repositories import (Repo, MemoryRepo, PatientRepo, DoctorRepo,
                                   DepartmentRepo, AppointmentRepo, RecordRepo,
                                   BillingRepo, BedRepo, InsuranceProviderRepo, PolicyRepo)

from hospital.attachments import ATTACHMENTS_DIR, resolve_attachment_path
from hospital.security import User, AuditEvent, AuditLog, AuthService, require_role
from hospital.services import (AppointmentService, MedicalRecordService,
                               BillingService, InpatientService)
from hospital.context import (SystemContext, seed_insurers, initialize_system,
                              create_physician, create_patient, suggest_appointment_slots)
from hospital.persistence import (datetime_to_iso, datetime_from_iso,
                                  context_to_dict, context_from_dict,
                                  save_context_to_file, load_context_from_file)

from hospital.templates import (format_section, NOTE_TEMPLATES,
                                NOTE_TEMPLATE_LOOKUP, BILLING_TEMPLATES,
                                BILLING_TEMPLATE_LOOKUP, REMINDER_TEMPLATES,
                                REMINDER_TEMPLATE_LOOKUP)
from hospital.demo import run_smoke_tests, run_demo
from hospital.cli import (prompt_input, prompt_password, prompt_new_password,
                          prompt_date, prompt_datetime_local, register_physician,
                          register_patient, add_availability, select_patient,
                          schedule_appointment, record_note, change_own_password,
                          reset_user_password, ensure_doctor_profile,
                          build_physician_summary, physician_loop, login_user,
                          handle_user_session, staff_menu, run_cli)
from hospital.gui import HospitalGUI

if __name__ == "__main__":
    if "--demo" in sys.argv:
        print(run_demo())
    elif "--smoke-test" in sys.argv:
        print(json.dumps(run_smoke_tests(), indent=2))
    else:
        app = HospitalGUI()
        app.mainloop()
