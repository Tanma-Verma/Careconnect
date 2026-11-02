CREATE TABLE IF NOT EXISTS cc_users (
    id text PRIMARY KEY,
    email text NOT NULL UNIQUE,
    password_hash text NOT NULL,
    role text NOT NULL DEFAULT 'PATIENT' CHECK (role IN ('PATIENT', 'PRACTITIONER', 'ADMIN')),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS cc_sessions (
    token_hash text PRIMARY KEY,
    user_id text NOT NULL REFERENCES cc_users(id),
    csrf text NOT NULL,
    expires_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS cc_sessions_user ON cc_sessions(user_id);
CREATE TABLE IF NOT EXISTS cc_documents (
    id text PRIMARY KEY,
    owner_id text NOT NULL REFERENCES cc_users(id),
    sha256 text NOT NULL,
    filename text NOT NULL,
    media_type text NOT NULL,
    size_bytes integer NOT NULL,
    pages integer NOT NULL,
    pipeline text NOT NULL,
    state text NOT NULL CHECK (state IN ('PROCESSING', 'READY', 'FAILED')),
    error text,
    chunk_count integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(owner_id, sha256)
);
CREATE TABLE IF NOT EXISTS cc_chunks (
    id text PRIMARY KEY,
    document_id text NOT NULL REFERENCES cc_documents(id) ON DELETE CASCADE,
    page integer,
    source_text text NOT NULL
);
CREATE INDEX IF NOT EXISTS cc_chunks_document ON cc_chunks(document_id);
CREATE TABLE IF NOT EXISTS cc_audit (
    id bigserial PRIMARY KEY,
    user_id text NOT NULL REFERENCES cc_users(id),
    action text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS cc_login_attempts (
    address text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS cc_login_address ON cc_login_attempts(address, created_at);

-- Additive ERP migration: preserve existing users, sessions, documents and vectors.
ALTER TABLE cc_users DROP CONSTRAINT IF EXISTS cc_users_role_check;
ALTER TABLE cc_users ADD CONSTRAINT cc_users_role_check CHECK (role IN ('PATIENT', 'PRACTITIONER', 'ADMIN'));

CREATE TABLE IF NOT EXISTS cc_patient_profiles (
    user_id text PRIMARY KEY REFERENCES cc_users(id),
    name text NOT NULL,
    dob date NOT NULL,
    sex text NOT NULL,
    history jsonb NOT NULL DEFAULT '[]',
    demographics jsonb NOT NULL DEFAULT '{}',
    is_demo boolean NOT NULL DEFAULT false
);
CREATE TABLE IF NOT EXISTS cc_doctor_profiles (
    user_id text PRIMARY KEY REFERENCES cc_users(id),
    name text NOT NULL,
    specialty text NOT NULL,
    department text NOT NULL,
    qualifications text NOT NULL,
    experience integer NOT NULL CHECK (experience >= 0),
    availability jsonb NOT NULL DEFAULT '[]',
    bio text NOT NULL DEFAULT '',
    is_demo boolean NOT NULL DEFAULT false
);
CREATE TABLE IF NOT EXISTS cc_assignments (
    doctor_id text NOT NULL REFERENCES cc_users(id),
    patient_id text NOT NULL REFERENCES cc_users(id),
    active boolean NOT NULL DEFAULT true,
    PRIMARY KEY (doctor_id, patient_id),
    CHECK (doctor_id <> patient_id)
);
CREATE TABLE IF NOT EXISTS cc_consents (
    doctor_id text NOT NULL,
    patient_id text NOT NULL,
    records boolean NOT NULL DEFAULT false,
    clinical boolean NOT NULL DEFAULT false,
    ai boolean NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (doctor_id, patient_id),
    FOREIGN KEY (doctor_id, patient_id) REFERENCES cc_assignments(doctor_id, patient_id)
);
CREATE TABLE IF NOT EXISTS cc_appointments (
    id text PRIMARY KEY,
    doctor_id text NOT NULL REFERENCES cc_users(id),
    patient_id text NOT NULL REFERENCES cc_users(id),
    scheduled_at timestamptz NOT NULL,
    reason text NOT NULL,
    status text NOT NULL CHECK (status IN ('REQUESTED', 'CONFIRMED', 'COMPLETED', 'CANCELLED')),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS cc_appointments_patient_time ON cc_appointments(patient_id, scheduled_at);
CREATE INDEX IF NOT EXISTS cc_appointments_doctor_time ON cc_appointments(doctor_id, scheduled_at);
CREATE TABLE IF NOT EXISTS cc_notes (
    id text PRIMARY KEY,
    doctor_id text NOT NULL REFERENCES cc_users(id),
    patient_id text NOT NULL REFERENCES cc_users(id),
    appointment_id text REFERENCES cc_appointments(id),
    content text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS cc_notes_patient_time ON cc_notes(patient_id, created_at);
CREATE TABLE IF NOT EXISTS cc_observations (
    id text PRIMARY KEY,
    patient_id text NOT NULL REFERENCES cc_users(id),
    document_id text NOT NULL REFERENCES cc_documents(id),
    code text NOT NULL,
    value numeric NOT NULL,
    unit text NOT NULL,
    reference_low numeric,
    reference_high numeric,
    measured_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS cc_observations_patient_time ON cc_observations(patient_id, measured_at);
