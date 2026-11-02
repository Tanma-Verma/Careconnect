# ERP security review

## Boundaries reviewed

- Session validation remains PostgreSQL-backed with opaque hashed session tokens,
  Argon2 password hashes, HttpOnly/SameSite cookies and the existing write-origin
  and CSRF checks. Public registration remains PATIENT-only.
- Doctor access requires PRACTITIONER role, active assignment and current scoped
  consent. Assignment alone, consent alone and ADMIN role do not grant records.
- Records, clinical history/notes and AI have separate permissions. AI needs both
  records and AI consent. The RAG callback checks fresh PostgreSQL state before
  generation and after generation; source routes check permission independently.
- Chroma filters are not the authorization boundary. Canonical PostgreSQL chunk
  ownership, readiness and pipeline validation reject foreign vector candidates.
- API SQL uses parameterized values. Search text is a parameter; SQL clauses and
  table names in application routes are server constants. User IDs never confer
  authorization by themselves.
- Doctor source access checks both document ownership and storage-path containment.
  Files remain outside public frontend storage. Doctor citations use authenticated
  doctor routes, not the owner-only patient route or model-provided URLs.
- Clinical notes remain structured PostgreSQL data and are not indexed as RAG
  evidence. Directory responses exclude account passwords and email addresses.
- Sensitive doctor operations produce audit actions without report contents.
- Seeding is explicitly enabled, deterministic, synthetic-only and idempotent;
  it does not reset existing consent decisions, appointment states or passwords.
  Indexing requires real successfully stored vectors before READY is persisted.

## Automated checks added

`tests/test_erp.py` uses a separate temporary PostgreSQL database per ERP test,
temporary original-file storage and unique Chroma collections. Only external
provider HTTP responses are mocked. Existing tests are unchanged.

Checks cover default seed counts and relations, idempotency and disabled seeding,
both account roles, dashboards, scoped directory access, assignments without
consent, consent changes, scope separation, CSRF, appointments, notes, literal
HTML note storage, parameterized search, real test-vector indexing and retries,
original-file hash mismatch, foreign vector rejection, doctor citation access,
in-flight revocation at embedding and generation boundaries, provider failures,
and application restart persistence.

Passing these isolated provider tests does not verify live Gemini. Actual test
counts, browser rendering and real-provider outcomes belong in the principal's
integration verification report.

## Remaining limitations

- Local hackathon deployment and synthetic data only; not a clinical compliance
  assessment or comprehensive penetration test.
- Doctor provisioning/assignments are controlled through local seeding; there is
  no administrator management UI. Booking does not automatically create clinical
  access or assignments.
- Appointment availability does not implement a full clinical scheduling engine.
- Consent controls future requests and in-flight generation checks; it cannot
  withdraw information already downloaded by an authorized user.
- Audit events contain action/time/account, not an immutable forensic event model.
- Existing development infrastructure credentials, external provider quotas and
  environment-based secret handling still need deployment-specific review.
