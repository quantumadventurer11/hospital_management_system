# Improvement roadmap

This is a plan for future code changes. The repository cleanup that added this document did not modify `hospital_management_system.py`.

## 1. Protect patient data and access

- Require a valid, active session for every protected service action. The current role helper skips session validation when the token is `None` ([`require_role`](../hospital_management_system.py#L859-L873)).
- Check patient and clinician relationships for clinical actions, rather than relying on a role alone ([appointment booking](../hospital_management_system.py#L908-L949), [record entry](../hospital_management_system.py#L993-L1013)).
- Restrict save/load and access to stored attachments. JSON currently includes clinical, financial, and credential-hash data and is written without encryption ([serialization](../hospital_management_system.py#L1340-L1496), [save/load](../hospital_management_system.py#L1689-L1697)).
- Remove predictable seed credentials from any mode intended beyond a local demo ([default users](../hospital_management_system.py#L638-L646)).

**Done when:** unauthenticated and out-of-scope actions are denied in automated tests; demo data is clearly separated from any future protected storage; saved data and attachments have a documented protection and recovery design.

## 2. Fix correctness and validation

- Validate appointment start/end order and duration, availability, and time-zone edge cases before booking ([booking](../hospital_management_system.py#L908-L940)).
- Validate positive finite charges and payments, copay ranges, and payment methods; use `Decimal` for money ([billing](../hospital_management_system.py#L1084-L1115)).
- Make admission atomic: reserve a bed only after patient, clinician, and schedule checks succeed ([admission](../hospital_management_system.py#L1140-L1170)).
- Fix default `status` construction for `Appointment` and `Bed`, where the `InitVar` and property share a name ([appointment](../hospital_management_system.py#L317-L344), [bed](../hospital_management_system.py#L383-L406)).

**Done when:** regression tests cover each failure and the relevant operations leave no partial state after an error.

## 3. Make the project easier to maintain and assess

- Move domain models, repositories, services, persistence, and GUI into separate modules while keeping the same behavior.
- Add a conventional automated test suite for authorization, scheduling, billing, save/load, audit history, and the GUI-independent service layer. Run it in CI. The current built-in smoke check covers only a few paths ([smoke check](../hospital_management_system.py#L1699-L1808)).
- Define supported Python versions and installation requirements, especially Tkinter and regional time-zone data. Add a repeatable launch command for the existing CLI function if that interface remains part of the project ([entry point](../hospital_management_system.py#L3807-L3838)).
- Decide how to package attachment bytes with exports and how to protect audit integrity independently of an editable JSON file.
- Add screenshots or a short screen recording using synthetic data, and describe design choices and lessons learned for a portfolio audience.

**Done when:** a new reviewer can install, run, and test the prototype from the README, and can distinguish demonstrated features from planned production safeguards.
