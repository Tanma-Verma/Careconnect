# CareConnect ERP integration contract

The existing patient document ownership, Gemini adapters and Chroma collection are
preserved. New ERP APIs live under `/api/v1/patient` and `/api/v1/doctor`; existing
patient upload, chat and source APIs retain their contracts. Both portals share
the existing PostgreSQL-backed, HttpOnly cookie sessions and CSRF protection.
Public registration accepts PATIENT only. Practitioner accounts are provisioned
through the explicitly enabled synthetic seeder, not a public registration API.

## Relationships

`cc_patient_profiles` and `cc_doctor_profiles` reference `cc_users`.
`cc_assignments` relates doctors to patients independently of `cc_consents`.
Consent has independent `records`, `clinical` and `ai` booleans. Appointment
requests and directory discovery do not confer medical-record access.
`cc_appointments` and `cc_notes` identify both participants; notes may reference an
appointment. `cc_observations` associates numeric measurements with patient-owned
source documents. Existing `cc_documents` and `cc_chunks` remain authoritative
for document ownership and RAG evidence.

## Authorization

Every doctor patient-data request requires PRACTITIONER authentication, an active
assignment and applicable current consent. Record/source access needs `records`;
structured clinical history and notes need `clinical`; RAG needs `records` plus
`ai`. Current consent is checked again before and after external generation, and
on every source-document open. PostgreSQL canonical chunk checks remain in place
after patient-filtered vector search. ADMIN is not an implicit clinical-access
bypass. Patient routes always derive the patient identity from the session.

Doctor-generated citations use the doctor-specific authorized source route.
Clinical notes are not embedded and are not claimed as RAG evidence.

## Response conventions

List envelopes use `patients`, `doctors`, `documents`, `appointments`, `notes`,
`consents`, or `observations`. Profiles use `profile`. History returns `history`,
`notes`, `observations`, and `documents`. Chat retains `answer`, `citations` and
`request_id`. All state-changing requests retain existing origin and CSRF checks.

Doctor dashboard `stats`: `assigned_patients`, `today_appointments`,
`upcoming_appointments`, `recent_reports`, `pending_tasks`.
Patient dashboard `stats`: `reports`, `indexed_reports`,
`upcoming_appointments`, `assigned_doctors`.

## Demo lifecycle

Seeding requires explicit `DEMO_SEED_ENABLED=true` and a local `DEMO_PASSWORD`.
Stable IDs and conflict handling make repeated seeding non-destructive. Original
TXT reports, SHA-256 metadata and structured observations are generated without
claiming AI success. Sequential resumable indexing uses real configured Gemini
embeddings; only successfully stored embeddings and canonical chunks make a
document READY. Demo-patient longitudinal records take priority.

No blockchain interface, commitment, schema or UI is implemented by this change.
