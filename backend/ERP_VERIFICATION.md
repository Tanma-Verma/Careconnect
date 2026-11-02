# ERP implementation verification — 2 November 2026

All changes remain local. No commit, push, merge, reset, Git credential/author changes,
blockchain implementation, embedding-model change or volume deletion occurred.

## Team and file ownership

Five Codex subagents were used, with at most three active concurrently due to the
environment's concurrency limit. Shared-file integration remained with principal.

| Agent | Owned implementation files |
|---|---|
| Database/synthetic data | app/schema.sql; scripts/seed_demo.py; scripts/index_demo.py |
| Doctor portal | ../frontend/doctor/index.html; ../frontend/doctor/js/app.js |
| Patient portal | ../frontend/patient/index.html; ../frontend/patient/js/app.js |
| Backend authorization | app/erp_access.py; app/doctor_routes.py; app/patient_routes.py |
| QA/security | tests/test_erp.py; ERP_SECURITY_REVIEW.md |

Principal integrated app/main.py, app/security.py, app/rag.py,
../frontend/shared/js/api.js, Dockerfile, ../.env.example, ignored local ../.env,
../README.md and ERP_CONTRACT.md. Principal added scripts/erp_live_demo.py and
scripts/erp_browser_smoke.cjs and this report. Integration corrections included
an explicit active-assignment guard for consent changes, doctor history summary
rendering, and a grounding-prompt clarification in app/provider.py.
app/db.py, provider models/dependencies and Compose topology were unchanged.
Earlier uncommitted RAG changes remain present.

## Data and actual indexing

Seeding executed twice successfully with defaults, without duplicate records.
The password came from ignored local DEMO_PASSWORD, never from source code.
Startup does not seed and DEMO_SEED_ENABLED remains false by default.

| Seeded entity | Count |
|---|---:|
| Fictional doctor profiles | 100 |
| Fictional patient profiles | 100 |
| Original synthetic medical reports | 100 |
| Doctor-patient assignments | 124 |
| Explicit primary-doctor consent records | 100 |
| Appointments | 150 |
| Structured clinical notes | 60 |
| Source-linked numeric observations | 269 |
| Reports actually indexed with real Gemini embeddings | 100 |
| Failed indexing operations | 0 |
| Demo-patient reports indexed first | 5 |

Browser write verification subsequently created one cancelled synthetic appointment
and one explicitly synthetic structured note: current totals are 151 appointments
and 61 notes. Those are real persisted operations, not extra seed duplicates.

Existing eight document rows and seven canonical chunks were compared against a
pre-implementation snapshot and remain unchanged. All 108 original files match
their PostgreSQL SHA-256 values. Application totals are 108 documents, 107 READY
documents, 107 canonical chunks and 107 vectors. The one pre-existing non-READY
document remains unchanged. The Chroma collection ID remains
29eb11fe-2ddb-4714-8294-b659a7d0e48c. Vector IDs, document IDs and owner metadata
match PostgreSQL canonical READY chunks.

## Automated tests

Final application suite after the grounding clarification:

`53 passed, 1 warning in 18.31s`.

The original 41 tests remain unchanged; 12 ERP cases were added. Tests use real
isolated PostgreSQL databases and test Chroma collections. External HTTP provider
responses alone are mocked. The warning is the existing Starlette TestClient
HTTPX deprecation; dependency versions were not changed.

Coverage includes counts, safe/idempotent seeding, role separation, dashboards,
assignment plus scoped consent, appointment and note operations, CSRF, poisoned
vector rejection, doctor citation ownership, in-flight revocation before/after
generation, indexing failure/retry, original-hash checks and restart persistence.

## Real provider and browser verification

Configured models remain gemini-embedding-001 (3072 dimensions) and
gemini-3.5-flash-lite. No fake vectors, simulated model answers or model fallback
were used for live verification.

`scripts/erp_live_demo.py --extended` completed with live_erp_verified=true.

- Patient latest blood pressure: 124/80 mmHg, 2026-11-01, with the November report citation.
- Doctor latest hemoglobin: 14.6 g/dL, 2026-11-01, using the selected patient's
  authorized source route.
- Patient fasting glucose comparison: 126 mg/dL on July 1 to 102 mg/dL on November 1.
- Citation excerpts matched the actual authenticated original files.
- Missing clinical-note content returned insufficient evidence and zero citations.
- Unrelated doctor was denied chart/source/RAG access.
- Revoking consent denied subsequent assigned-doctor source and RAG operations;
  restoration restored source access.

An initial missing-note check returned an honest disclaimer with a report citation,
rather than the required insufficient-evidence form. The prompt was clarified to
distinguish evidence about a record's absence from evidence of its contents. The
real retry returned the required form; citation validation was not relaxed.

Real Edge browser verification used an already-installed Playwright module;
no frontend framework or application dependency was added. Both portals passed:
login, database dashboard values, directory/history/report rendering, duplicate
upload, real AI answer and expandable citation rendering/source HTTP 200, note
creation, appointment request/cancellation, consent revoke/save, logout PHI
cleanup, practitioner availability rendering and unrelated-doctor HTTP 403.
The patient mobile menu was visible at 390px. Zero page JavaScript errors occurred.
Controlled browser offline mode displayed a useful network error and restored Send;
the next online request succeeded. Upstream failure sanitization is also covered
by isolated provider tests; no new live provider error was encountered in this run.

## Docker and persistence

Backend was built and recreated with Docker; PostgreSQL, Chroma and backend were
then all restarted without deleting volumes. Hash snapshots of users, document
metadata, canonical chunks, profiles, assignments, consents, appointments, notes
and observations were identical before and after. Original hashes and vector
count/collection ID were unchanged. A previously issued patient session remained
valid (HTTP 200), listed all five demo reports and opened its source (HTTP 200).
All three app services reported healthy afterward. MinIO remains unused.

## Remaining boundaries

- Synthetic local hackathon deployment; no compliance certification or real-patient approval.
- No blockchain implementation or assumed blockchain contract.
- Notes are structured-only, not RAG sources. Do not claim AI can retrieve them.
- No administrator UI or public doctor registration. Provisioning and assignments
  are controlled by the explicit local seed. An unrelated booking does not create
  clinical access, and requires controlled assignment/consent before doctor visibility.
- Availability is informational; no full scheduling/capacity engine or profile editor.
- Fixed synthetic dates age over time; dashboard upcoming/today counts use real database time.
- Retrieval is top-five evidence, not an exhaustive unlimited-history summary.
- Gemini quota, latency and output consistency remain external risks.
- Audit is account/action/time rather than an immutable forensic event system.
- Existing development database/MinIO passwords remain in the original Compose file.
  Configured Gemini keys and demo password remain server-side/local and must not be committed.
