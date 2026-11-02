# RAG performance investigation — 2 November 2026

## Conclusion and limits

The bottleneck is waiting for the remote Gemini response, not local authorization,
retrieval, JSON validation or connection setup. The approved Flash-Lite model gave
a correct browser result in 2.229 seconds, but an additional final supported request
took **43.414 seconds** (43.389 server-side). Do not describe this as a guaranteed
17x improvement or a reliably two-second service. The fast sample and slow outlier
are both real. Client tracing cannot distinguish Google queueing from inference.

## Method

Actual authenticated browser requests use the already indexed synthetic fixture.
No documents/indexes were rebuilt or deleted. Timings use monotonic clocks and
HTTPX/httpcore trace callbacks. Logs contain only random request IDs, HTTP status,
stage durations, attempt counts, connection phase durations, numeric token usage,
and an allowlisted public model name (unknown names are logged as `other`).
They exclude questions, source text, patient/document identities, URLs, cookies and keys.

`rag_timing` is emitted for `/api/v1/ai/chat`, including failures. The request ID
matches the API response. Durations are milliseconds. Stage timings are exclusive;
HTTP detail within a provider attempt is a breakdown, not additional time to sum.
Generation includes provider HTTP work and any retry wait. Model execution cannot
be separated from Google's queueing/network response delay using client timing alone.

## Baseline: previous Gemini 3.8 Flash

One real request, ID `60f4538c-aab7-4bec-a300-9e7711a3ddc2`, HTTP 200:

| Stage | Milliseconds |
|---|---:|
| Authentication/session/CSRF | 10.554 |
| Question embedding | 809.923 |
| Chroma retrieval | 8.234 |
| PostgreSQL ownership/readiness validation | 20.516 |
| Context + prompt construction | 0.093 |
| Gemini generation HTTP | 38086.876 |
| JSON parsing + citation validation | 0.191 |
| Audit persistence | 14.827 |
| Remaining request processing/serialization | 4.079 |
| Total server request | 38955.293 |
| Browser-observed request | 38976 |

Generation is **97.8%** of total latency. Its TCP setup was 68.599 ms, TLS 60.994 ms,
and waiting for response headers 37954.968 ms. Connection setup is about 0.34% of
generation time; it is not the main bottleneck. Earlier fresh-connection observations
were not controlled pooling benchmarks and do not establish a connection-reuse cause.
The current connection policy is retained rather than changed speculatively.

One embedding request and one generation request both returned 200; no retry.
Generation used 337 prompt tokens and 58 completion tokens. The configured request
uses `reasoning_effort:low` and a 512-token cap. No further cap/prompt reduction is
justified by this measurement; the answer already uses far fewer than 512 tokens.

## Isolated faster-model comparison

Google's authenticated model list included `gemini-3.5-flash-lite`. A single live
service-function comparison used the same fixture, question, embedding model,
grounding prompt, required JSON schema, low reasoning, 512-token cap, ownership
revalidation and citation checks. **The application model was not changed.**

| Stage | Milliseconds |
|---|---:|
| Question embedding | 929.719 |
| Chroma retrieval (cold client) | 64.237 |
| Ownership validation | 19.368 |
| Context construction | 0.068 |
| Candidate generation HTTP | 1639.874 |
| JSON + citation validation | 0.144 |
| Audit persistence | 11.098 |
| Remaining service processing | 0.182 |
| Total service-function call | 2664.690 |

Authentication/HTTP middleware were not part of this isolated comparison. Do not
present 2.665 seconds as an authenticated browser measurement. Generation took
1.640 seconds versus 38.087 seconds for 3.8, approximately 23 times faster in these
individual samples. It returned the documented fact and one validated citation.
Its generation TCP+TLS setup was 161.858 ms and response-header wait 1472.696 ms.
Usage was the same 337 prompt/58 completion tokens as the baseline.

This establishes model availability, schema compatibility and fixture correctness,
not general medical quality or an availability SLA. After reviewing these results,
the user explicitly selected `gemini-3.5-flash-lite` for the demo. The local `.env`
and `.env.example` now select it, with low reasoning/512 output tokens. Embeddings
and the application collection were unchanged.

## After: authenticated browser request on approved Flash-Lite model

Same question, source document, patient, schema and citation checks. Request
`32d35e90-03f0-449f-9d93-86631a4fc701`, HTTP 200:

| Stage | Milliseconds |
|---|---:|
| Authentication/session/CSRF | 8.770 |
| Question embedding | 872.049 |
| Chroma retrieval | 10.852 |
| PostgreSQL ownership/readiness validation | 21.126 |
| Context + prompt construction | 0.067 |
| Gemini generation HTTP | 1266.293 |
| JSON parsing + citation validation | 0.176 |
| Audit persistence | 22.886 |
| Remaining request processing/serialization | 3.327 |
| Total server request | 2205.546 |
| Browser-observed request | 2229 |

Server latency fell from 38.955 to 2.206 seconds, approximately 17.7x faster and
94.3% lower in these individual requests. Browser latency fell from 38.976 to 2.229
seconds. Generation was 1.266 seconds, with TCP+TLS 133.337 ms and response-header
wait 1131.064 ms. Output: 60 tokens, finish reason `stop`; one attempt, no retries.
The answer rendered correctly and its authorized source returned HTTP 200.
This is a before/after sample, not a load test or a percentile/SLA measurement.

### Final supported retest after the insufficient-evidence prompt clarification

Request `79215df5-1ad1-4cf3-994d-9367264a5098`, HTTP 200, correct answer/citation:

| Stage | Milliseconds |
|---|---:|
| Authentication | 9.292 |
| Question embedding | 865.089 |
| Chroma retrieval | 6.795 |
| Ownership validation | 19.237 |
| Context construction | 0.080 |
| Generation | 42475.196 |
| JSON/citation validation | 0.061 |
| Audit | 10.511 |
| Request overhead | 3.070 |
| Total server / browser | 43389.333 / 43414 |

Generation waited 42335.045 ms for headers; TCP+TLS was 137.616 ms. One attempt,
57 completion tokens, 388 prompt tokens, finish `stop`. No retry or token-cap
exhaustion caused this outlier. Prompt clarification added 51 input tokens; these
few samples cannot separate prompt effects, upstream load and run-to-run variance.
No claim of consistently improved latency is supported by this sample size.

## Provider failure observed during investigation

An additional 3.8 Flash request returned upstream HTTP 429. It failed in 1.462
seconds server-side (1.500 seconds in browser). Authentication 11.490 ms; embedding
897.467 ms; Chroma 7.963 ms; ownership 19.727 ms; context 0.111 ms; generation
520.817 ms; overhead 4.243 ms. Parsing/citation/audit stages were skipped because
generation failed. There was one attempt and no quota-error retry.

The UI showed the safe quota/rate-limit error and re-enabled Send. This failed
request is not an accelerated successful RAG result and is excluded from the
before/after comparison. The exact quota window (RPM/TPM/daily) was not established;
inspect the project's active AI Studio limits rather than assuming it is daily.

## Minimal improvements

- Permanent content-free stage/connection timing and numeric token diagnostics.
- Retry shares the remaining configured provider timeout rather than receiving a
  second full timeout. A 503 with <=3 seconds remaining does not start another attempt.
- Still only one retry, same model/key/body; no retry for authentication, model access
  or quota errors. No fabricated fallback. HTTPX timeouts are per network operation,
  not a strict whole-request cancellation timer; the shared budget specifically
  prevents extending retries by another complete timeout allowance.
- Explicit low-reasoning/512-token configuration for the verified Flash-Lite model,
  selected only after the user approved the measured proposal. Existing auth,
  ownership, citations and embedding configuration remain.
- The first Flash-Lite missing-HbA1c result had contradictory insufficient-evidence
  and citation fields. Existing validation rejected it (HTTP 502 in 2.079 seconds).
  The prompt now explicitly forbids citation markers as well as source labels when
  evidence is insufficient, with a matching JSON example. Validation was not relaxed.
  The actual medical negative retest returned HTTP 200, no invented finding and
  empty citations: 2.209 seconds server-side / 2.237 seconds in browser. Generation
  used 1.376 seconds, 48 output tokens, finish `stop`, one attempt.

## Readiness

Docker startup/health, real browser login, previously indexed document listing,
pending chat state and disabled Send control verified. Baseline response rendered
the actual grounded answer and citation. A controlled browser network outage showed
an error and restored Send, then a real request was submitted after recovery.
Provider failure handling is also covered by isolated automated provider tests.

**41 automated tests passed** (one existing TestClient deprecation warning), including
content-free complete stage timing, unchanged ownership/citation behavior, same-body
retry, remaining-budget retry and suppression of late retries. The exact Gemini
generation configuration is covered for both 3.8 Flash and 3.5 Flash-Lite.

Regression assertions also verify that insufficient-evidence responses containing
citation markers or source labels remain rejected. No real provider was replaced
by a mock during live verification. Test mocks stay at the isolated provider boundary.

Changed files: `backend/app/timing.py` (new), `main.py`, `security.py`, `rag.py`,
`provider.py`, `backend/tests/test_app.py`, `backend/tests/test_gemini.py`, ignored
local `.env`, `.env.example`, `README.md`, `backend/VERIFICATION.md`, and this report.
No frontend source, dependency, Compose topology, database schema, embedding model,
application vector collection or blockchain file was changed.
