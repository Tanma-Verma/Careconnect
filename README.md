# CareConnect — patient and practitioner ERP demo

FastAPI serves the existing HTML/CSS/JavaScript patient and doctor portals. PostgreSQL persists
role-scoped accounts, profiles, assignments, consent, appointments, clinical notes,
observations, opaque sessions, document metadata, canonical chunks and audit
events. Private Chroma stores embeddings; a private volume stores original files.
The backend has no fake embedding provider, scripted AI answers or fabricated records.
The separate CareConnect_Prototype.html remains a visual reference and is not served.

## Two-portal synthetic ERP demonstration

The patient portal is **http://localhost:3000/patient/** and the practitioner
portal is **http://localhost:3000/doctor/**. Both use the same backend and database.
Practitioner access requires an active assignment **and** current patient consent
for records, clinical operations, or AI. AI additionally requires record access.
Public registration remains patient-only; ADMIN does not bypass medical consent.

The deterministic seed defaults to 100 fictional doctors, 100 fictional patients,
100 original medical reports, 150 appointments, 124 assignments and 60 notes.
The demonstration patient has five July–November 2026 reports containing blood
pressure, fasting glucose, CBC and HbA1c. Other reports cover lipid, thyroid,
kidney, liver and routine observations. No real patient information is used.

Configure Gemini and start Docker using the next section. Then, in PowerShell:

```powershell
Set-Location D:\Careconnect
# Set a 12–128 character password in the ignored local .env first.
# The implementation run already generated DEMO_PASSWORD there; never print/share .env.
$env:DEMO_PASSWORD = ((Get-Content .env | Where-Object { $_ -like 'DEMO_PASSWORD=*' } | Select-Object -Last 1) -replace '^DEMO_PASSWORD=', '')
if (-not $env:DEMO_PASSWORD) { throw 'Configure DEMO_PASSWORD in local .env first.' }
docker compose -f docker-compose.yml -f docker-compose.rag.yml exec -T -e DEMO_PASSWORD -e DEMO_SEED_ENABLED=true backend python scripts/seed_demo.py
Remove-Item Env:\DEMO_PASSWORD

# Sequential real Gemini indexing; resumable, prioritizing the five demo reports.
docker compose -f docker-compose.yml -f docker-compose.rag.yml exec -T -e DEMO_SEED_ENABLED=true backend python scripts/index_demo.py --max-documents 100 --max-seconds 600 --delay 1 --attempts 2
docker compose -f docker-compose.yml -f docker-compose.rag.yml exec -T -e DEMO_SEED_ENABLED=true backend python scripts/index_demo.py --status-only
```

Use unquoted values for `DEMO_PASSWORD` with the PowerShell extraction above.
The password is not sent to the frontend until you enter it in the login form.
`DEMO_SEED_ENABLED` is disabled by default; neither startup nor registration seeds
data. Counts can be configured with `--doctors`, `--patients`, `--reports`,
`--appointments`, and `--notes`. Stable UUID5 identifiers and conflict checks
preserve existing records, passwords, consent revocations and appointment updates.
Lowering counts never deletes previously seeded records. Changing DEMO_PASSWORD
does not reset existing seeded accounts' passwords.

Seeding creates originals, hashes, metadata and observations, **not embeddings**.
Awaiting-index documents show FAILED with an explicit awaiting-real-embeddings
message until indexing succeeds. READY requires stored real vectors and canonical
PostgreSQL chunks. Quota/auth/configuration errors stop indexing with visible
progress; fix the reported cause and rerun. The time limit governs starting new
operations, not cancellation of an in-progress provider call. Never remove volumes.

Demo logins (all passwords come from local `DEMO_PASSWORD`):

| Portal | Account | Purpose |
|---|---|---|
| Patient | demo.patient@example.test | Five longitudinal reports and consent controls |
| Doctor | demo.doctor@example.test | Assigned, consented doctor for that patient |
| Doctor | demo.unrelated@example.test | Cannot open the demonstration patient's records |

Patient: view dashboard, records and history; ask "What was my latest blood
pressure?" or "How has my fasting blood glucose changed from July to November
2026?" Expand citations and open the original. Sign out before switching roles.
Doctor: select **Demo Patient 001** in Patient chart context, review history,
appointments and clinical notes, then ask which report contains the latest
hemoglobin result. Confirm the source citation opens. The unrelated doctor must
be denied that patient's API/source/RAG requests. The patient can revoke all
consent and verify subsequent assigned-doctor access is denied, then grant it
again for the demonstration.

Clinical notes are structured-only and explicitly **not indexed**. Questions about
appointment notes cannot be answered from reports; use the clinical-history view.
This is not an unrestricted whole-record summarizer.

For a real HTTP/provider verification (not mocks):

```powershell
$env:DEMO_PASSWORD = ((Get-Content .env | Where-Object { $_ -like 'DEMO_PASSWORD=*' } | Select-Object -Last 1) -replace '^DEMO_PASSWORD=', '')
docker compose -f docker-compose.yml -f docker-compose.rag.yml exec -T -e DEMO_PASSWORD backend python scripts/erp_live_demo.py --extended
Remove-Item Env:\DEMO_PASSWORD
```

This checks both roles, real Gemini answers, exact source excerpts, unrelated-doctor
denial, and consent revocation/restoration. It temporarily changes only the demo
patient's consent and restores it in `finally`. Provider failures remain errors.

The new authenticated API groups are `/api/v1/patient/{dashboard,doctors,
appointments,history,observations,consents,profile}` and `/api/v1/doctor/
{dashboard,patients,appointments,profile}`. Doctor patient-specific routes expose
details, documents/source, history, notes and `ai/chat`. GET lists, POST booking/
notes/chat, PATCH appointment statuses, and PUT consent are implemented. Consult
`/openapi.json` for exact request schemas. Existing patient document/chat routes
remain compatible. See [ERP contract](backend/ERP_CONTRACT.md) and
[security review](backend/ERP_SECURITY_REVIEW.md).

Observed implementation results are recorded in
[ERP verification](backend/ERP_VERIFICATION.md): 100/100 synthetic reports indexed,
53 automated tests passing, both real browser RAG flows verified, and persistent
data/session checks after restarting all three services. Browser verification
adds one cancelled synthetic appointment and one structured synthetic note.

Optional browser automation is `node backend/scripts/erp_browser_smoke.cjs` when
Playwright or playwright-core is already installed. Set `PLAYWRIGHT_MODULE` to its
module path if needed; default browser channel is `msedge` (`BROWSER_CHANNEL` can
select another installed channel). The script reads the local demo password without
printing it, uses real Gemini by default and creates a cancelled test appointment
and structured test note. `--skip-ai` skips live generation for focused UI checks.

## Start (PowerShell)

Requires Docker Desktop and Compose 2.24.4+ (the overlay uses !override to restrict
PostgreSQL to loopback). Ports 3000 and 5432 must be available.

```powershell
Set-Location D:\Careconnect
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Edit .env with your provider configuration before expecting live AI results.
docker compose -f docker-compose.yml -f docker-compose.rag.yml up -d --build --wait backend
docker compose -f docker-compose.yml -f docker-compose.rag.yml ps
Invoke-RestMethod http://localhost:3000/health
docker compose -f docker-compose.yml -f docker-compose.rag.yml logs --tail 50 backend
```

Open **http://localhost:3000/patient/**. Frontend and API use the same origin.
Use localhost, not 127.0.0.1, unless APP_ORIGIN is changed too. /openapi.json lists APIs.
/health checks PostgreSQL and Chroma and reports provider configuration presence;
it does not send a paid provider request or prove that credentials/models work.
Account creation works without provider credentials; ingestion/generation fails
explicitly when an unconfigured provider is needed.

## Environment

### Google Gemini setup and observed verification

Use a Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey).
Set the following in your ignored local `.env`; never put a key in frontend code:

```dotenv
EMBEDDING_API_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
EMBEDDING_API_KEY=<your server-side Gemini key>
EMBEDDING_MODEL=gemini-embedding-001
LLM_API_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
LLM_API_KEY=<your server-side Gemini key>
LLM_MODEL=gemini-3.5-flash-lite
```

The same key can be used for both variables. Do not copy the angle-bracket
placeholders literally. Existing `.env` files must be edited rather than overwritten.
After changing it, recreate backend with the command below under configuration changes.

[Google's compatibility documentation](https://ai.google.dev/gemini-api/docs/openai)
specifies bearer authorization and the `/embeddings` and `/chat/completions` routes.
The adapter strips trailing slashes so the version prefix is preserved and there
is exactly one slash before each endpoint. It uses HTTP JSON directly; no SDK was added.

For Gemini generation, the adapter requests `response_format.type=json_schema`,
with required `answer:string`, `sources:integer[]`, `insufficient_evidence:boolean`.
This follows Google's documented structured-output compatibility flow. For other
providers the existing JSON-object request remains unchanged. Parsed output must
still pass local type checks and authorized citation-label validation; schema mode
does not bypass these checks. Gemini 3.5 Flash-Lite is the user-approved demo model;
the embedding model remains `gemini-embedding-001`.
Both selected Flash-Lite and optional 3.8 Flash use low reasoning and a 512-token
output cap. The measured authenticated request fell from 38.96 seconds on 3.8 to
2.21 seconds on Flash-Lite, with real embeddings, retrieval and validated citations.
This is a small live sample, not an SLA. See [stage timings](backend/PERFORMANCE.md).
An additional final supported request on Flash-Lite took 43.41 seconds despite
one attempt and only 57 output tokens. It still returned a correct validated answer.
The switch therefore improves the observed fast case, not a guaranteed latency bound.
`PROVIDER_TIMEOUT_SECONDS=120` remains a failure allowance. The single 503 retry
shares the remaining timeout budget; a late overload response cannot start another
full timeout. Authentication, model-access and quota errors are not retried or
replaced. The portal displays loading/error states and re-enables Send after errors.
Gemini connections currently stay fresh. TCP+TLS was only ~0.13 seconds of the
38-second generation: connection setup was not the main bottleneck.

Gemini's live embedding response omitted `data[].index`. To preserve unambiguous
chunk/vector alignment, Google embedding requests send one input at a time and
accept an omitted index only on a singleton response. Other providers still require
valid indexes. This increases requests for large documents; respect project quotas.

**Observed:** Gemini returned 3072-dimensional finite nonzero vectors. This matches
the [documented default](https://ai.google.dev/gemini-api/docs/embeddings) for
`gemini-embedding-001`. The adapter enforces 3072 for this model; no output-dimension
override/truncation is sent. Cosine search is used. Endpoint/model/chunking changes
select a separate collection; re-upload to reindex, and never delete shared volumes.

The project initially migrated generation to `gemini-3.8-flash` after Google's
[model-access notice](https://ai.google.dev/gemini-api/docs/deprecations) and a real
HTTP 404 for the restricted `gemini-2.5-flash` model. There is no silent alternative
model. This generation-only change retains the existing embedding pipeline and
Chroma collection; do not delete or recreate vector collections to change the LLM.
After a real same-evidence speed comparison, the user approved `gemini-3.5-flash-lite`
for the live demo. There is still no automatic fallback to a different model.
See `backend/VERIFICATION.md` for actual live-generation and retrieval results.
The exact fixture has passed the live HTTP smoke test, and a real generated answer
with an expandable, authorized citation has also been verified in the patient portal.
The unsupported out-of-document check returned insufficient evidence and no citations.
Provider availability and model output consistency remain demo risks. Previous 3.8
checks took 46–104 seconds or timed out. A later 3.8 request hit HTTP 429; the UI
showed the quota error, not a fabricated answer. Persistent failures remain visible.
The faster model passed the synthetic fixture, not a comprehensive clinical eval.

Google [rate limits](https://ai.google.dev/gemini-api/docs/rate-limits) are project-
and model-specific. HTTP 429 means rate/quota exhaustion; inspect AI Studio's active
quotas/billing and retry only after resolving the limit. HTTP 401/403 indicates key,
permission or restriction issues; some invalid keys can return 400. HTTP 404 may be
a model-access problem even when the model appears in the list endpoint. We observed
an actual 429 on 3.8 during the performance investigation. Its exact quota window
was not established; check the project's active AI Studio limits.

To use the exact fixture in the real demo script:

```powershell
docker compose -f docker-compose.yml -f docker-compose.rag.yml --profile tools run --build --rm --no-deps -v D:/Careconnect/demo:/demo:ro tests python scripts/live_demo.py --base-url http://backend:3000 --origin http://localhost:3000 --report /demo/synthetic-report.txt
```

Successful ingestion prints READY even if generation subsequently fails. Only the
final success JSON proves live generation and valid citations; no mocked response
is used by this script. Any real provider error is reported without simulated output.

The HTTP adapters use an **OpenAI-compatible wire format**, without a provider SDK.
Embedding and generation providers may differ. Providers exposing only another
protocol need an adapter. All six provider values below are required for live AI.

| Variable | Meaning |
|---|---|
| EMBEDDING_API_BASE_URL | HTTPS base including version prefix, usually /v1 |
| EMBEDDING_API_KEY | Embedding bearer credential |
| EMBEDDING_MODEL | Exact available embedding model ID |
| LLM_API_BASE_URL | HTTPS chat-completion API base including version prefix |
| LLM_API_KEY | Generation bearer credential |
| LLM_MODEL | Model supporting JSON Schema for Gemini, JSON-object for other providers |
| APP_ORIGIN | Browser origin, default http://localhost:3000 |
| COOKIE_SECURE | false for local HTTP; must be true for HTTPS |
| SESSION_HOURS | Default 12; range 1–168 |
| PROVIDER_TIMEOUT_SECONDS | Gemini example uses 120; fallback default 45; range 1–120 |
| MAX_COSINE_DISTANCE | Default 0.65; smaller means stricter, calibrate for model |
| DATABASE_URL | Default existing postgres service credentials; see .env.example |

POST <embedding-base>/embeddings sends model, input:[text,...], encoding_format:float
and requires data:[{index,embedding:[float,...]}]. POST <llm-base>/chat/completions
sends model, messages, temperature:0, max_tokens:512 for Gemini 3.8/3.5 Flash-Lite (1200 otherwise),
response_format:{type:json_object} for other providers, or the schema above for Gemini;
it reads choices[0].message.content as JSON.
Choose models supporting these parameters. There is no silent protocol fallback.
Invalid credentials/quota/model, timeouts, invalid vectors/JSON/citations are errors.
Keys stay server-side; .env is ignored by Git and excluded from Docker build context.

After configuration changes:

```powershell
docker compose -f docker-compose.yml -f docker-compose.rag.yml up -d --force-recreate --wait backend
```

Changing embedding model/endpoint or chunk configuration selects a different vector
collection. Re-upload existing files to index for that configuration. Old-model
vectors are not queried using a different model. Keep model dimensions stable.

## Reproduce the demo

1. Register a patient account; password must be 12–128 characters.
2. Medical records → Add record → upload demo/synthetic-report.txt.
3. Wait for READY. The modal shows indeterminate upload/indexing progress and the
   list refreshes during ingestion. FAILED displays the actual safe diagnostic;
   fix the problem and re-upload the same file to retry.
4. Ask: What blood pressure was recorded, and on what date?
5. Expand the citation, compare its exact excerpt, and open the original source.
6. Ask about a finding absent from the document; inspect insufficient-evidence behavior.
7. Log out, register a second patient: list is empty, and the first patient's source
   URL returns 404. Use synthetic documents only.

PDF/TXT only: up to 10 MiB, 50 PDF pages, 100,000 extracted characters. Scanned,
encrypted, malformed, binary, empty and non-UTF-8 documents are rejected. PDF pages
are 1-based; TXT citations have page:null. Same-owner duplicate uploads are idempotent.

## Automated tests and actual live-provider check

```powershell
docker compose -f docker-compose.yml -f docker-compose.rag.yml --profile tools run --build --rm tests
```

Tests use real PostgreSQL/Chroma and mock HTTP only at the external provider boundary.
They create/drop a uniquely named temporary database and clean test-only vector
collections; application/teammate tables are not truncated or replaced.
Coverage: auth/session invalidation, CSRF/origin, role denial, ownership, PDF/TXT
validation, ingestion/duplicate retry, real vector search, foreign vector rejection,
citation validation, provider failures, and insufficient evidence.

For an explicitly **real** embedding + LLM smoke test after configuring credentials:

```powershell
docker compose -f docker-compose.yml -f docker-compose.rag.yml --profile tools run --build --rm --no-deps tests python scripts/live_demo.py --base-url http://backend:3000 --origin http://localhost:3000
```

The script uses real HTTP, creates an explicitly synthetic account/document,
requires the documented fact plus authorized citations, and prints verification
only on success. Missing credentials exits nonzero with NOT VERIFIED.
If APP_ORIGIN changed, pass its exact value to --origin.

## APIs and security

| Method | Path | Behavior |
|---|---|---|
| GET | /health | PostgreSQL/Chroma readiness and config presence |
| POST | /api/v1/auth/register | Patient-only registration and session |
| POST | /api/v1/auth/login | Password verification, session rotation |
| GET | /api/v1/auth/me | user and csrf_token |
| POST | /api/v1/auth/logout | Invalidate current session |
| GET | /api/v1/documents | Current patient's documents |
| GET | /api/v1/records | Document list alias |
| POST | /api/v1/documents | Multipart file field; bounded synchronous ingestion |
| GET | /api/v1/documents/{id} | Owner-only status/metadata |
| GET | /api/v1/documents/{id}/source | Owner-only original |
| POST | /api/v1/ai/chat | message → answer, citations, request_id |
| GET | /api/v1/audit | Current account's recorded actions |

All writes need X-Requested-With: CareConnect. Authenticated writes also require
X-CSRF-Token from login/register/me. Origin must match APP_ORIGIN and cross-site
fetches are rejected. Cookies: HttpOnly, SameSite=Strict, host-only, expiring,
Secure when HTTPS is configured. PostgreSQL stores hashed random session tokens;
passwords use Argon2id. Public ADMIN/PRACTITIONER registration is rejected.

Patient document operations are owner-only. Practitioner operations require the
separate assignment and scoped-consent checks described above.
Chroma owner filtering is followed by PostgreSQL checks of document ownership,
READY state and pipeline. Source text/pages come from canonical PostgreSQL chunks.
The prompt treats source content as untrusted data. Generated citation labels must
match retrieved authorized evidence. URLs are constructed by the backend.
FAILED ingestion returns HTTP 502 with persisted diagnostic; no success is invented.
Patient data and in-flight requests are cleared on logout/account switching.

## Persistence and limitations

```powershell
docker compose -f docker-compose.yml -f docker-compose.rag.yml restart postgres chroma backend
```

Wait for health, refresh/re-login, and verify documents/citations remain. PostgreSQL,
original documents and Chroma all use persistent named volumes. Do not remove volumes.
Interrupted PROCESSING rows become FAILED at backend startup; retry the same file.

- Single backend worker and bounded synchronous ingestion; no durable queue or
  multi-worker recovery. Add worker leases before scaling workers/replicas.
- Progress is indeterminate, not a fabricated byte percentage. If a client times
  out, indexing may still run: refresh status before retrying.
- No OCR, antivirus, conversation memory, streaming, FHIR, maps, or blockchain
  implementation. Unsupported APIs return authenticated 501. Doctor provisioning
  and assignments use controlled local seeding; there is no administrator UI.
  Booking is a request workflow, not a full scheduling engine. Requests for an
  unassigned/non-consented doctor remain unavailable to that doctor until a
  controlled assignment and applicable consent exist. Availability is informational.
- Top-five retrieval is not an exhaustive whole-history summary. Similarity cutoff
  needs calibration. No relevant evidence returns insufficient evidence without
  calling generation. Citation validation does not prove every model claim true.
- External providers receive selected document text. This is a local hackathon
  deployment for synthetic data, not a certified medical/production system.
- Basic auth limit: 20 attempts/IP/15 minutes. Provider spending/rate controls,
  stronger accounts, TLS/backups/encryption and a data-handling review are needed
  before public deployment or real patient information.
- Original Compose remains unchanged. Overlay reuses postgres and adds private
  Chroma/backend/tests. Existing MinIO is unused and not started by the command
  above; its original ports and development credentials remain unchanged.
- PostgreSQL credentials are development values. Changing DATABASE_URL must match
  the credentials of the already initialized database.

See backend/VERIFICATION.md for observed checks and live-provider status.
