# Hospital Management System

An educational Python prototype exploring appointment scheduling, clinical records, billing, inpatient beds, role-based actions, and an audit trail. The code is separated into a `hospital` package. `hospital_management_system.py` is a short entry point that starts the GUI, scripted demo, or smoke check.

> **Use synthetic data only.** This is a course project, not a production hospital system. Its saved JSON and copied attachments are not encrypted, and the current authorization, validation, and persistence behavior needs more work before any real patient information could be used. An ignore file reduces accidental commits but does not secure local data.

## Run it

The application was checked with Python 3.13. Run commands from the repository root so Python can import the `hospital` package. Python's Tkinter module and an IANA time-zone database must be available for the desktop interface and correct regional time handling. On some systems, Tkinter needs a separate operating-system package. The source also has optional fallbacks for `backports.zoneinfo` and `typing_extensions` on older Python versions; those versions have not been verified here.

```bash
python hospital_management_system.py --smoke-test
python hospital_management_system.py --demo
python -m unittest discover -s tests -v
python hospital_management_system.py
```

The last command opens the Tkinter GUI; `--smoke-test` runs lightweight integration checks, and `--demo` prints a scripted example. A `run_cli()` function is present in the source, but the current command-line entry point does not expose it.

New to Python projects? Read [How the application is organized](docs/ARCHITECTURE.md) for a plain-language tour of the files and a booking example.

The desktop interface uses a shared light theme, clear section headings, action cards, and compact activity counts. High contrast mode remains available from the **View** menu.

Newly registered accounts stay in memory until you explicitly save hospital data. The registration flow offers to save, and **Load Saved Data** on the start screen restores a saved account after restarting the app. A save file is unencrypted JSON, so use synthetic data only.

The GUI starts with demonstration accounts (`admin`, `clerk`, `nurse`, and `doctor`) and predictable passwords in the source. They are for local demonstration only. Do not use them to protect sensitive information.

## What it demonstrates

- In-memory repositories and service classes for patients, doctors, appointments, records, billing, and beds.
- A no-overlap scheduling policy and an optional appointment buffer policy.
- Self-pay and insurance copay billing strategies.
- Password hashing with PBKDF2, role checks, and a hash-chained audit log.
- A Tkinter interface with data entry, summaries, and JSON save/load.

## Data handling and limitations

- Saving writes patient, clinical, billing, credential-hash, and audit information as readable JSON. Choose a location appropriate for **synthetic** demo data, and do not publish save files.
- A save replaces an existing file only after the new JSON is fully written. Loading requires saved accounts to include valid password hashes and salts; plaintext-only legacy account files are not supported.
- Attachments are copied to `hospital_attachments/` relative to the working directory. A JSON save contains attachment paths, not the attachment bytes, so moving the JSON file by itself can break links.
- The audit chain can detect some changes to a saved history, but it is not independently protected against someone who can rewrite the file.
- The built-in smoke check covers a few successful paths and scheduling conflicts. The regression suite covers specific bugs, but neither is a comprehensive test suite.
- No web service, multi-user database, encryption at rest, backup process, or production deployment is provided.

For specific code and security improvements, see [the prioritized roadmap](docs/ROADMAP.md).

## Repository layout

```text
hospital_management_system.py  Short entry point and compatibility imports
hospital/attachments.py       Attachment path handling
hospital/context.py           System wiring and registration workflows
hospital/errors.py             Shared application exceptions
hospital/timezones.py          Time-zone choices and fallback lookup
hospital/domain.py             OOP entities, value objects, and scheduling/billing policies
hospital/repositories.py       Typed in-memory repository classes
hospital/security.py           User, authentication, and audit classes
hospital/services.py           Appointment, record, billing, and inpatient services
hospital/persistence.py        JSON save/load and context serialization
hospital/templates.py          Synthetic form templates and text formatting
hospital/demo.py               Scripted demo and built-in smoke check
hospital/cli.py                Interactive text menu functions
hospital/gui.py                Tkinter window assembly and startup
hospital/gui_theme.py          Shared colors, type, buttons, and tabs
hospital/gui_common.py         Shared GUI controls and dialogs
hospital/gui_doctor.py         Login and doctor screens
hospital/gui_staff.py          Clerk, nurse, billing, and admin screens
tests/                         Workflow and module-boundary regression checks
docs/ARCHITECTURE.md           Beginner's guide to the code layout
README.md                      Setup, scope, and limitations
docs/ROADMAP.md                Proposed improvement plan
.gitignore                     Local data and generated-file exclusions
```

The repository does not currently include a license. Public visibility alone does not grant permission to reuse the code; the author should choose a license if reuse is intended.
