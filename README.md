# Care Connect — Milestone 1

Stage 1 keeps the original prototype as a visual reference and adds a real API plus patient and doctor portals. Medical records, uploads, PostGIS search, and RAG are **not** implemented yet.

Unchanged originals:

- `CareConnect_Prototype.html`
- `Backup/CareConnect_Prototype.html`

## Prerequisites

- Docker Desktop
- Node.js 20 or newer
- npm

## Run locally

```bash
cp .env.example .env
docker compose up -d postgres minio
cd backend
npm install
npx prisma generate
npx prisma migrate deploy
npm test
npm run dev
```

Open:

- http://localhost:3000 — portal picker
- http://localhost:3000/patient/ — patient portal
- http://localhost:3000/doctor/ — doctor portal
- http://localhost:3000/health — API health
- http://localhost:9001 — MinIO console (wired for later uploads; unused in M1)

## Verify M1

1. Open the patient portal. There is **no** demo password and **no** “explore without login”.
2. Create a patient account (password at least 12 characters) and sign in.
3. The dashboard layout matches the prototype, but stats, records, vitals, and doctors stay empty or show “not implemented”.
4. Access & consent → Recent access history shows real `AUTH_REGISTER` / `AUTH_LOGIN` audit rows.
5. Open the doctor portal, create a practitioner account, and confirm the same empty clinical placeholders plus the audit log.
6. `GET /api/v1/records` with a session cookie returns `501`.

## Tests

```bash
cd backend
npm test
```

Covers health, register/login/me, httpOnly cookie, audit rows, 501 placeholders, and frontend constraints (no `innerHTML`, no inline handlers, no demo PHI in the new portals).

## Out of scope (later milestones)

- FHIR resource CRUD
- Document uploads to MinIO
- Nearby doctor search (PostGIS)
- Appointment booking
- Consent grants
- RAG assistant
