# How the application is organized

This is a learning project. It uses **synthetic data only**. It is not a system for real patient records.

## Start here

Run `python hospital_management_system.py` from the repository root to open the desktop app. The same file accepts `--demo` for a printed example and `--smoke-test` for a quick check. It is deliberately short: it chooses which mode to start and imports names from the `hospital` package so existing code that imports `hospital_management_system` still works.

A **module** is one Python file. A **package** is a folder of modules with an `__init__.py` file. Splitting the project this way lets you find one kind of work without reading the whole application.

## The layers

```text
GUI / CLI / demo          What a person sees and types
        ↓
Context and services     How actions are coordinated
        ↓
Domain and repositories  Objects and in-memory collections
        ↓
Persistence              Converts those objects to and from JSON
```

- `hospital/domain.py` defines the things the app works with: patients, doctors, appointments, beds, bills, and schedules. A class is a blueprint; an object is one instance, such as one appointment. A scheduling policy is also an object, so the rule can be swapped without changing the appointment service.
- `hospital/repositories.py` stores objects in memory and finds them by ID. Think of a repository as a labeled collection. It is not a database.
- `hospital/security.py` holds demo users, password checks, sessions, and audit events. `hospital/errors.py` gives services shared error types. These controls demonstrate concepts but do not make the app suitable for real medical data.
- `hospital/services.py` carries out actions such as booking an appointment, writing a note, billing, or admitting a patient. A service checks the rules, updates repositories, and records an audit event.
- `hospital/context.py` builds a `SystemContext`: one bundle containing the repositories, services, and security objects that work together. It also contains registration helpers and appointment suggestions.
- `hospital/persistence.py` converts the context to and from JSON and saves files using a temporary file before replacement. The GUI asks before a load replaces the current in-memory session. `hospital/attachments.py` handles attachment paths. Saved JSON and attachments are not encrypted.
- `hospital/gui.py` starts the Tkinter window. `gui_common.py` holds shared controls and forms, `gui_doctor.py` holds login and doctor screens, and `gui_staff.py` holds clerk, nurse, billing, and admin screens. These screen groups are **mixins**: classes that contribute methods to `HospitalGUI` while sharing the same window and context. `hospital/cli.py` contains a text menu that can be called from Python. `hospital/demo.py` supplies the scripted example and built-in smoke check. `hospital/templates.py` holds reusable example text and form choices; `hospital/timezones.py` finds time zones.

## Follow one appointment

1. A person enters an appointment in the GUI.
2. The GUI calls `ctx.appt_svc.book(...)` on the service in `SystemContext`.
3. The service checks the signed-in user's role, the patient and doctor IDs, the time zone, and schedule conflicts.
4. If valid, it creates an `Appointment` object, stores it in a repository, updates the doctor's schedule, and adds an audit event.
5. If the person chooses **Save**, persistence turns the current context into JSON. Loading later reconstructs the same kinds of objects.

This separation means a scheduling rule can be inspected in the domain or service code without editing the window layout. It also lets tests call a service directly without clicking through the GUI.

## Why the desktop screens changed

`hospital/gui_theme.py` keeps the colors, type sizes, buttons, and tab styles in one place. That makes the welcome, login, clinician, staff, and analytics screens feel like one application. Each screen now starts with a clear heading, puts common actions in a white card, and shows a few counts that update as in-memory data changes. The clinician summary has a visible scrollbar when there is more information than fits on screen. The **View** menu still offers high contrast and font-size controls. These changes affect presentation; the services still decide what actions are allowed and how data is stored.

## How to check a change

From the repository root:

```bash
python -m unittest discover -s tests -v
python hospital_management_system.py --smoke-test
python hospital_management_system.py --demo
```

The tests cover selected workflows, saved-data behavior, old import paths, and Tkinter login, forms, save, and load. They use temporary folders and synthetic records; temporary files are removed afterward. GUI tests skip when no display is available. For a visual check, open the GUI and try a workflow with synthetic data. Interactive paths beyond those tests still need coverage.
