# Current ERP verification

See [ERP_VERIFICATION.md](ERP_VERIFICATION.md) for the latest two-portal implementation,
100 real indexed synthetic reports, 53-test suite, browser checks and restart results.
Earlier RAG-only verification below is retained as historical evidence.

# CareConnect implementation verification

The implementation uses real PostgreSQL and Chroma, with an external HTTP provider
adapter. There is no production fake-provider mode.

## Latest: performance investigation and approved demo model

The active demo generation model is now **gemini-3.5-flash-lite**, explicitly chosen
by the user after seeing an isolated real-provider comparison. Embeddings remain
`gemini-embedding-001`. See [PERFORMANCE.md](PERFORMANCE.md) for separate pipeline
and TCP/TLS/provider-wait timings, sample IDs, limitations and safe improvements.

- Authenticated browser comparison: 38.976 seconds on 3.8 Flash versus 2.229 seconds
  on Flash-Lite; both actual answers and authorized citations matched the same fixture.
- A 3.8 request hit a real 429. The UI showed the error and re-enabled Send; quota
  errors were not retried. The exact quota window was not established.
- The Flash-Lite missing-HbA1c check initially failed strict citation consistency.
  After clarifying the prompt (without relaxing validation), it returned HTTP 200,
  insufficient evidence and empty citations in 2.237 seconds.
- 41 automated tests pass, including complete content-free timing and safety tests.
- A final supported Flash-Lite request passed but took 43.414 seconds. Its remote
  response-header wait dominated; no retries or token-cap exhaustion occurred.
  The two-second result is a fast sample, not a consistency guarantee.
- Logs never include questions, source text, patient/document identities, cookies
  or API keys. Current application documents and collection ID remain unchanged.

The sections below preserve prior migration verification as history; they do not
override the current approved model selection or claim current 3.8 quota availability.

## Current migration: Gemini 3.8 Flash

**Live upload → real embeddings → Chroma retrieval → Gemini 3.8 structured
generation → validated citations → frontend rendering verified.**

The approved configuration is now `LLM_MODEL=gemini-3.8-flash` with the unchanged
`EMBEDDING_MODEL=gemini-embedding-001`. Keys remain only in the ignored local `.env`.

Actual structured generation and the complete RAG service function have succeeded
against Google. The latter returned an answer containing the documented 122/80 mmHg,
date 1 November 2026, and a validated source [1]. The live HTTP demonstration using
the exact `demo/synthetic-report.txt` also passed:

- `live_embeddings_verified: true`, `live_llm_verified: true`.
- Document `459499b5-2ab8-4633-b08b-af971f4156b5`, READY, chunk `:0`.
- Request `6e72ce74-854f-4d57-a7bb-0726ea4b75cb`.
- Actual answer: “According to the documented outpatient visit summary from
  1 November 2026, your recorded blood pressure was 122/80 mmHg [1]. Please note
  that this is demonstration data from a synthetic report and not real medical
  advice; always consult a healthcare professional for clinical guidance and
  treatment decisions.”
- Citation [1] identifies `synthetic-report.txt`, the same uploaded document and
  canonical chunk; TXT page is null. Authenticated source bytes matched the fixture.

Browser verification also passed with the existing uploaded document
`91d03dcb-2f2e-4d1f-9286-ac431b31c381`:

- Chat returned HTTP 200 and the portal rendered the actual model answer:
  “On 1 November 2026, your report records a blood pressure measurement of
  122/80 mmHg [1]. Please remember to consult with a qualified healthcare
  professional regarding the interpretation of your medical results.”
- The rendered citation expands to the canonical source excerpt. Its source link
  returned HTTP 200, matches that document ID, and contains the documented date
  and value. TXT page remains null, not an invented page reference.

Unsupported-question verification:

- Browser question: “Which spacecraft first photographed Pluto?”
- Real retrieval returned the synthetic report at cosine distance 0.537139, under
  the existing 0.65 cutoff, so the generation path was exercised.
- HTTP 200 returned: “I could not find enough relevant evidence in your ready
  documents to answer this question. Upload a relevant report or ask about a
  documented finding. A healthcare professional can help interpret your results.”
- Citations were empty; no out-of-document spacecraft fact or medical finding
  was invented. Request ID: `236fcd69-9f23-4f28-952d-8788878325eb`.
- An additional medical unsupported question, “What is my HbA1c result?”, exceeded
  the provider deadline and returned HTTP 502, `Llm provider timed out. Please
  retry.` No fabricated result appeared. Successful generation for this extra
  medical negative case remains unverified; do not describe all provider calls as
  reliable. No retrieval cutoff was adjusted to force these tests to pass.

Final actual backend restart:

- Session remained valid in the browser; the existing uploaded document remained
  READY and its original source returned HTTP 200 with matching content.
- Real query embedding still used `gemini-embedding-001`, 3072 dimensions.
- Owner-scoped search retrieved `91d03dcb-2f2e-4d1f-9286-ac431b31c381:0` at cosine
  distance 0.284516. The original pre-migration document remained READY.
- Application collection ID stayed `29eb11fe-2ddb-4714-8294-b659a7d0e48c` throughout;
  vector count increased from 1 to 7 solely from real demo uploads. Existing
  application collections/documents/volumes were not deleted or recreated.
- Read-only Python syntax, Compose config and Git whitespace checks passed.

Modified in this migration: ignored local `.env`, `.env.example`, `README.md`,
`backend/app/provider.py`, `backend/tests/test_gemini.py`, and this verification file.
No frontend, database schema, Compose infrastructure or blockchain file was changed
in this migration. Earlier uncommitted implementation work remains intact.

Observed integration issues and minimal adjustments:

- Original 45-second requests timed out. A structured diagnostic succeeded after
  78.36 seconds; local/example provider timeout is now 120 seconds.
- The full prompt succeeded with a 512-token cap (83.33 seconds). Gemini 3.8 now
  uses that cap and documented low reasoning; the schema and grounding prompt remain.
- Full real retrieval → generation → citation validation succeeded on fresh provider
  connections (104.16 seconds). Gemini connections now avoid keep-alive reuse.
- Upstream HTTP 503 was observed. One bounded retry uses the exact same model,
  key and body after two seconds. Persistent errors remain explicit; no fake output.
- **37 automated tests passed in 7.24 seconds**, including both generation models'
  schema handling and bounded 503 retry tests. One existing TestClient warning remains.

Application collection `careconnect-a552f6f12870b165113c`, ID
`29eb11fe-2ddb-4714-8294-b659a7d0e48c`, existed before migration and is retained.
Its old documents and 3072-dimensional embedding configuration were preserved.

## Previous Gemini 2.5 verification (historical access restriction)

**Gemini embeddings and real semantic retrieval verified. Generation is blocked by
Google model access, not missing credentials.** Both keys are now present in local
`.env` and remain server-side. No key was printed, logged or written into source.

Configured base: `https://generativelanguage.googleapis.com/v1beta/openai/`.
Models: `gemini-embedding-001` and `gemini-2.5-flash`.
The pre-existing `.env` typo `gemini-2.5-flashx` was corrected, preserving credentials.

Real Google HTTP results:

- Embeddings: HTTP 200, finite nonzero vectors of **3072 dimensions**. Google's
  response omitted `data[].index`; the adapter now safely handles singleton
  responses and sends singleton requests to avoid ambiguous batch ordering.
- Generation: HTTP **404 NOT_FOUND**. The safely inspected provider message was:
  “This model models/gemini-2.5-flash is no longer available to new users.” Google
  recommended gemini-3.8-flash. No alternative model was selected automatically.
- Google `/models` returned HTTP 200 and included models/gemini-2.5-flash, but that
  listing did not grant generation access. No 401, 403 or 429 was observed.
- Google's compatibility docs document structured schema output. Gemini requests
  now use a required JSON Schema; local output/citation checks remain unchanged.
  Successful schema generation on the requested model remains unverified due to 404.

Real RAG demonstration using the exact `demo/synthetic-report.txt` fixture:

- Authenticated upload reached **READY**, document ID
  `49688952-c3ef-46b1-8d65-3211d8222885`.
- The query “Which cardiovascular measurements were captured at the appointment?”
  generated a real Gemini query embedding and retrieved the fixture's chunk with
  cosine distance **0.292692**, under the configured **0.65** cutoff.
- Stored and query vectors both have 3072 dimensions. Canonical PostgreSQL chunk
  text contains 122/80, owner metadata matches, and a foreign-owner vector query
  returned no results. Existing volumes were preserved.
- The full chat request reached generation and returned the real provider failure.
  No generated answer or generated citation was fabricated. Source provenance was
  verified; actual generated-citation correctness remains blocked.

**34 automated tests passed in 7.77 seconds** on the final rerun, with one existing TestClient
deprecation warning. The original PostgreSQL/Chroma integration tests and new
Gemini URL/authentication, unindexed responses, dimensions, schema and safe-error
tests all passed. Provider mocks are isolated to automated tests, never live checks.

The automated suite mocks only external provider HTTP responses. Passing those
tests does not establish that a real embedding or LLM request has succeeded.

## Initial implementation checks (before Gemini credentials were configured)

Observed on 2 November 2026 (local timezone):

- Python compile checks, both edited JavaScript syntax checks, Compose validation,
  and `git diff --check` passed.
- Backend and test Docker images built successfully. The backend runs as UID 10001.
- PostgreSQL, Chroma and backend containers reported healthy. `/health` returned
  `status: ok`, `database: ok`, `chroma: ok`, with both provider configuration flags false.
- **23 automated tests passed in 7.23 seconds** against actual PostgreSQL and Chroma.
  One dependency deprecation warning: Starlette's TestClient currently deprecates
  httpx in favor of httpx2. The pinned stack remains functional.
- Browser: patient registration, upload submission, explicit missing-embedding-key
  error, persisted FAILED state, successful rendering of an honest no-evidence
  response, and logout clearing chat/email/document DOM all passed.
- Browser testing found and fixed the existing registration dialog stacking bug.
- Browser after real container restart: account login and original document persisted;
  owner source access returned 200 with the original bytes, logged-out access returned
  401, and a second patient's access returned 404 with an empty document list.
- After restarting PostgreSQL, Chroma and backend, the isolated infrastructure probe
  verified a PostgreSQL row, private-volume file, Chroma vector and similarity query
  all survived. Probe vectors are explicitly test data, never application AI output.
- The real live-demo script was run and exited nonzero with `NOT VERIFIED` because
  provider configuration is absent. No real embedding or LLM call was claimed.

Expected browser HTTP errors were 401 before login, 501 for out-of-scope clinical
features, and 502 for intentionally unconfigured ingestion. No JavaScript runtime
exceptions were observed in the completed browser flows.

## Reproduce

From the repository root:

```powershell
docker compose -f docker-compose.yml -f docker-compose.rag.yml --profile tools run --build --rm tests
docker compose -f docker-compose.yml -f docker-compose.rag.yml --profile tools run --rm --no-deps -v careconnect_careconnect_documents:/data/documents tests python scripts/persistence_probe.py seed
docker compose -f docker-compose.yml -f docker-compose.rag.yml restart postgres chroma backend
# Wait for all three containers to become healthy.
docker compose -f docker-compose.yml -f docker-compose.rag.yml --profile tools run --rm --no-deps -v careconnect_careconnect_documents:/data/documents tests python scripts/persistence_probe.py verify
```

The probe uses uniquely named `cc_persistence_probe_*` tables/collections and a
private `.persistence-probe.json` marker. It does not modify patient records.

All source changes remain local and uncommitted. Original docker-compose.yml,
the standalone prototype and doctor portal source were not modified. No blockchain
files or Git identity/credentials were changed.
