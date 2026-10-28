# Improvement roadmap

## Addressed in the debugging pass

- New physician registration now creates an active session. The GUI explains that new accounts require an explicit save to survive a restart and provides a **Load Saved Data** button.
- Protected service actions require a registered user and an active session.
- The default `Appointment` and `Bed` constructors work, allowing the scripted demo to run.
- Booking rejects reversed time ranges; billing rejects nonpositive or nonfinite amounts and unsupported payment methods.
- Failed admissions no longer leave a bed occupied after a schedule conflict.
- Completing an appointment twice and discharging a free bed are rejected.
- Clinical service actions now check a doctor's patient and appointment assignments and prevent another author's ID on notes.
- Loading rejects users without valid stored password hashes and audit events without chain hashes. Saving replaces the target only after a complete temporary write.
- Attachment files are kept within the attachment folder, even if imported data contains unusual IDs or paths.
- Regression tests cover these cases; run `python -m unittest discover -s tests -v`.

## Next: patient data and access

- Apply patient-scope checks to every read and analytics path; repository objects are still directly accessible inside the desktop process.
- Design protected storage and backup for saved data and attachments. JSON currently contains clinical, financial, and credential-hash data and is written without encryption.
- Remove predictable seed credentials from any mode intended beyond a local demo.
- Decide how to protect audit integrity independently of an editable JSON file.

**Done when:** all patient views enforce the same scope rules, and saved data and attachments have a documented protection and recovery design.

## Next: domain and workflow rules

- Define appointment availability requirements and test time-zone edge cases, including daylight-saving transitions.
- Use `Decimal` for money, validate insurance copay ranges, and define whether overpayments create credits or are rejected.
- Add a workflow for moving a discharged bed from `cleaning` back to `free`; complete the remaining status-transition rules.
- Make multi-step state changes atomic beyond the specific admission conflict fixed above.

**Done when:** edge cases have explicit rules and regression tests, and errors leave no partial state.

## Next: maintainability and presentation

- Domain models, repositories, services, security, context wiring, persistence, GUI, CLI, and demos now live in `hospital/`; `hospital_management_system.py` keeps the established entry points. The GUI is grouped into shared, doctor, and staff modules. Save/load dialog success and failure paths now have automated checks. Extend coverage for remaining interactive workflows as those areas change.
- Extend automated tests to cover more audit and GUI paths, and run them in CI.
- Define supported Python versions and installation requirements, especially Tkinter and regional time-zone data. Expose the existing CLI function if that interface remains part of the project.
- Add screenshots or a short screen recording using synthetic data, and describe design choices and lessons learned for a portfolio audience.

**Done when:** a new reviewer can install, run, and test the prototype from the README and distinguish demonstrated features from planned safeguards.
