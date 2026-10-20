-- NEXUS 001 : socle. Migrations additives uniquement (voir docs/MIGRATIONS.md).
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE users (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  username      text UNIQUE NOT NULL,
  password_hash text NOT NULL,
  role          text NOT NULL CHECK (role IN ('fondateur','operateur','lecture')),
  active        boolean NOT NULL DEFAULT true,
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE sessions (
  token_hash text PRIMARY KEY,
  user_id    uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  revoked    boolean NOT NULL DEFAULT false
);

CREATE TABLE system_state (
  id             int PRIMARY KEY CHECK (id = 1),
  emergency_stop boolean NOT NULL DEFAULT false,
  stopped_at     timestamptz, stopped_by text, reason text,
  report         jsonb,
  rearmed_at     timestamptz, rearmed_by text
);
INSERT INTO system_state(id) VALUES (1);

CREATE TABLE services (
  id text PRIMARY KEY, name text NOT NULL, kind text NOT NULL, url text,
  status text NOT NULL DEFAULT 'unknown' CHECK (status IN ('unknown','up','down','degraded','disabled')),
  checked_at timestamptz, detail text
);
CREATE TABLE agents (
  id text PRIMARY KEY, name text NOT NULL, role text NOT NULL,
  service_id text REFERENCES services(id), enabled boolean NOT NULL DEFAULT true, description text
);

CREATE TABLE tasks (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  kind           text NOT NULL,
  title          text NOT NULL,
  owner          text NOT NULL,
  status         text NOT NULL DEFAULT 'draft'
                 CHECK (status IN ('draft','queued','awaiting_approval','running','succeeded','failed','cancelled')),
  auth_level     int NOT NULL DEFAULT 1 CHECK (auth_level IN (0,1,2)),
  params         jsonb NOT NULL DEFAULT '{}',
  params_hash    text NOT NULL,
  version        int NOT NULL DEFAULT 1,
  input_refs     jsonb NOT NULL DEFAULT '[]',
  output_refs    jsonb NOT NULL DEFAULT '[]',
  outputs        jsonb,
  error_code     text, error_message text,
  correlation_id uuid NOT NULL,
  created_by     text NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now(),
  queued_at timestamptz, started_at timestamptz, finished_at timestamptz,
  timeout_s      int NOT NULL DEFAULT 60,
  max_attempts   int NOT NULL DEFAULT 2,
  attempts       int NOT NULL DEFAULT 0,
  not_before     timestamptz,
  cancel_requested boolean NOT NULL DEFAULT false
);
CREATE INDEX tasks_status_idx ON tasks(status);
CREATE INDEX tasks_corr_idx ON tasks(correlation_id);
CREATE TABLE task_dependencies (
  task_id uuid NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  depends_on_id uuid NOT NULL REFERENCES tasks(id),
  PRIMARY KEY (task_id, depends_on_id), CHECK (task_id <> depends_on_id)
);
CREATE TABLE workflow_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id uuid REFERENCES tasks(id), source text NOT NULL DEFAULT 'internal',
  attempt int NOT NULL DEFAULT 1, status text NOT NULL,
  started_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz,
  error_code text, correlation_id uuid
);
CREATE TABLE approvals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id uuid NOT NULL REFERENCES tasks(id),
  action text NOT NULL, params jsonb NOT NULL, params_hash text NOT NULL,
  status text NOT NULL DEFAULT 'pending'
         CHECK (status IN ('pending','approved','rejected','expired','invalidated','consumed')),
  requested_by text NOT NULL, requested_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  decided_by text, decided_at timestamptz, decision_note text, consumed_at timestamptz
);

-- Journal append-only, chaîné par empreintes (calculées par le serveur de base).
CREATE SEQUENCE audit_events_seq;
CREATE TABLE audit_events (
  seq bigint PRIMARY KEY, ts timestamptz NOT NULL DEFAULT clock_timestamp(),
  actor text NOT NULL, action text NOT NULL, entity_type text, entity_id text,
  correlation_id text, outcome text NOT NULL DEFAULT 'ok', details jsonb NOT NULL DEFAULT '{}',
  prev_hash text NOT NULL DEFAULT '', hash text NOT NULL DEFAULT ''
);
CREATE FUNCTION audit_row_hash(prev text, a audit_events) RETURNS text LANGUAGE sql IMMUTABLE AS $$
  SELECT encode(sha256(convert_to(concat_ws('|', prev, a.seq::text,
    to_char(a.ts AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US'),
    a.actor, a.action, a.entity_type, a.entity_id, a.correlation_id, a.outcome, a.details::text),'UTF8')),'hex') $$;
CREATE FUNCTION audit_before_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE prev text;
BEGIN
  PERFORM pg_advisory_xact_lock(9187001);
  SELECT hash INTO prev FROM audit_events ORDER BY seq DESC LIMIT 1;
  NEW.seq := nextval('audit_events_seq');
  NEW.ts := clock_timestamp();
  NEW.prev_hash := coalesce(prev, 'GENESIS');
  NEW.hash := audit_row_hash(NEW.prev_hash, NEW);
  RETURN NEW;
END $$;
CREATE TRIGGER audit_chain BEFORE INSERT ON audit_events FOR EACH ROW EXECUTE FUNCTION audit_before_insert();
CREATE FUNCTION audit_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'audit_events est append-only'; END $$;
CREATE TRIGGER audit_no_update BEFORE UPDATE OR DELETE ON audit_events FOR EACH ROW EXECUTE FUNCTION audit_immutable();
CREATE TRIGGER audit_no_truncate BEFORE TRUNCATE ON audit_events FOR EACH STATEMENT EXECUTE FUNCTION audit_immutable();
-- Retourne le premier seq dont l'empreinte ou le chaînage est faux, ou NULL si la chaîne est saine.
CREATE FUNCTION verify_audit_chain() RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE r audit_events; prev text := 'GENESIS';
BEGIN
  FOR r IN SELECT * FROM audit_events ORDER BY seq LOOP
    IF r.prev_hash <> prev OR r.hash <> audit_row_hash(prev, r) THEN RETURN r.seq; END IF;
    prev := r.hash;
  END LOOP;
  RETURN NULL;
END $$;

CREATE TABLE repositories (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text UNIQUE NOT NULL, url text,
  source text NOT NULL, status text NOT NULL DEFAULT 'downloaded_unaudited'
    CHECK (status IN ('downloaded_unaudited','audited','rejected')),
  metadata jsonb NOT NULL DEFAULT '{}', imported_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE dataset_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text NOT NULL, version text NOT NULL,
  sha256 text NOT NULL, rows int NOT NULL, provenance jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (name, version)
);
CREATE TABLE strategy_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text NOT NULL, version text NOT NULL,
  definition jsonb NOT NULL, status text NOT NULL DEFAULT 'simulation' CHECK (status IN ('simulation','retired')),
  created_at timestamptz NOT NULL DEFAULT now(), UNIQUE (name, version)
);
CREATE TABLE experiments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  strategy_version_id uuid REFERENCES strategy_versions(id), dataset_version_id uuid REFERENCES dataset_versions(id),
  task_id uuid REFERENCES tasks(id), status text NOT NULL DEFAULT 'running',
  mode text NOT NULL DEFAULT 'SIMULATION' CHECK (mode = 'SIMULATION'),
  assumptions jsonb NOT NULL DEFAULT '{}', metrics jsonb, report_md text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE prospects (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text NOT NULL, sector text,
  contact_info jsonb NOT NULL DEFAULT '{}', documented_issues jsonb NOT NULL DEFAULT '[]',
  is_fictional boolean NOT NULL DEFAULT true, source text NOT NULL DEFAULT 'manual',
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE proposals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), prospect_id uuid NOT NULL REFERENCES prospects(id),
  status text NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft','reviewed','awaiting_approval','approved_not_sent','rejected')),
  body_md text, review jsonb, task_id uuid REFERENCES tasks(id), version int NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE contracts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), proposal_id uuid REFERENCES proposals(id),
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft')), terms jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE incidents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  severity text NOT NULL CHECK (severity IN ('low','medium','high','critical')),
  title text NOT NULL, status text NOT NULL DEFAULT 'open'
    CHECK (status IN ('open','root_cause','fixed','tested','reviewed','deployed','closed')),
  root_cause text, corrective_action text, tests_ref text, reviewed_by text, task_id uuid REFERENCES tasks(id),
  created_at timestamptz NOT NULL DEFAULT now(), closed_at timestamptz
);
CREATE TABLE ledger_entries (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), kind text NOT NULL CHECK (kind IN ('expense','payment')),
  amount_cents bigint NOT NULL CHECK (amount_cents > 0), currency text NOT NULL DEFAULT 'EUR',
  label text NOT NULL, documented boolean NOT NULL DEFAULT false, document_ref text,
  occurred_on date NOT NULL DEFAULT current_date, created_by text NOT NULL
);
CREATE TABLE external_actions (   -- toute action déjà effectuée hors du système (vide en v0.1)
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), task_id uuid REFERENCES tasks(id),
  kind text NOT NULL, target text, performed_at timestamptz NOT NULL DEFAULT now(), details jsonb NOT NULL DEFAULT '{}'
);
CREATE TABLE idempotency_keys (
  actor text NOT NULL, key text NOT NULL, request_hash text NOT NULL,
  status_code int, response jsonb, created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (actor, key)
);
CREATE TABLE ceo_commitments (
  day date NOT NULL, kind text NOT NULL CHECK (kind IN ('decision_prioritaire','action_livree','revue_fin_journee')),
  text text, done boolean NOT NULL DEFAULT false, updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (day, kind)
);
CREATE TABLE council_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), question text NOT NULL,
  proposal text, counter text, synthesis jsonb, task_id uuid REFERENCES tasks(id),
  grants_rights boolean NOT NULL DEFAULT false CHECK (grants_rights = false),
  created_at timestamptz NOT NULL DEFAULT now()
);
