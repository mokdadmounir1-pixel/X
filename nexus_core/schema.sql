-- Nexus core : registre de budget, revue, approbation, envoi et audit.
-- A executer par le role proprietaire `nexus_owner` sur une base vide.
-- Toute mutation passe par une fonction SECURITY DEFINER ; les roles applicatifs
-- n'ont aucun droit direct sur les tables.
-- Choix assume : un verrou consultatif global (7001) serialise toutes les mutations.
-- A l'echelle visee (quelques operations par seconde au plus) cela supprime des
-- classes entieres de courses et d'interblocages ; il faudra le revoir au-dela.

CREATE SCHEMA nexus AUTHORIZATION nexus_owner;
SET search_path = nexus, pg_temp;

-- ---------------------------------------------------------------- horloge
-- Vide en production. Les tests y inscrivent une date pour verifier les
-- frontieres de mois et de cycle. Aucun role applicatif n'y a acces.
CREATE TABLE clock_override (ts timestamptz NOT NULL);

CREATE FUNCTION clock() RETURNS timestamptz
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = nexus, pg_temp AS
$$ SELECT COALESCE((SELECT ts FROM clock_override LIMIT 1), now()) $$;

-- ---------------------------------------------------------------- politique
CREATE TABLE policy (
  id                 boolean PRIMARY KEY DEFAULT true CHECK (id),
  total_cents        int  NOT NULL DEFAULT 30000,
  reserve_cents      int  NOT NULL DEFAULT 6000,
  research_cap_cents int  NOT NULL DEFAULT 6000,
  cycle_cap_cents    int  NOT NULL DEFAULT 3000,
  alert_percent      int  NOT NULL DEFAULT 80,
  cycle_anchor       date NOT NULL DEFAULT DATE '2026-10-04',
  cycle_days         int  NOT NULL DEFAULT 15 CHECK (cycle_days > 0),
  daily_email_cap    int  NOT NULL DEFAULT 20,
  CHECK (reserve_cents < total_cents),
  CHECK (research_cap_cents <= total_cents - reserve_cents),
  CHECK (cycle_cap_cents <= research_cap_cents)
);
INSERT INTO policy DEFAULT VALUES;

CREATE FUNCTION paris_day(ts timestamptz) RETURNS date
LANGUAGE sql IMMUTABLE AS $$ SELECT (ts AT TIME ZONE 'Europe/Paris')::date $$;

CREATE FUNCTION paris_month(ts timestamptz) RETURNS date
LANGUAGE sql IMMUTABLE AS
$$ SELECT date_trunc('month', ts AT TIME ZONE 'Europe/Paris')::date $$;

-- Le cycle est derive de l'ancrage, jamais choisi par l'appelant.
CREATE FUNCTION cycle_of(ts timestamptz) RETURNS int
LANGUAGE sql STABLE SET search_path = nexus, pg_temp AS
$$ SELECT floor((paris_day(ts) - p.cycle_anchor)::numeric / p.cycle_days)::int FROM policy p $$;

CREATE TYPE result AS (ok boolean, code text, id bigint);

-- ---------------------------------------------------------------- principaux
CREATE TABLE principal (
  id      serial PRIMARY KEY,
  db_role name NOT NULL UNIQUE,
  kind    text NOT NULL CHECK (kind IN ('worker','censor','founder','transport'))
);

-- ---------------------------------------------------------------- audit
CREATE TABLE audit_log (
  seq       bigserial PRIMARY KEY,
  ts        timestamptz NOT NULL,
  actor     text NOT NULL,
  event     text NOT NULL,
  payload   jsonb NOT NULL,
  prev_hash text NOT NULL,
  hash      text NOT NULL
);

CREATE FUNCTION no_mutation() RETURNS trigger LANGUAGE plpgsql AS
$$ BEGIN RAISE EXCEPTION 'immutable_table' USING ERRCODE = 'P0001'; END $$;

CREATE TRIGGER audit_no_mod BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION no_mutation();
CREATE TRIGGER audit_no_trunc BEFORE TRUNCATE ON audit_log
  FOR EACH STATEMENT EXECUTE FUNCTION no_mutation();

CREATE FUNCTION audit_hash(p_prev text, p_actor text, p_event text, p_payload jsonb, p_ts timestamptz)
RETURNS text LANGUAGE sql IMMUTABLE AS
$$ SELECT encode(sha256(convert_to(
     p_prev || '|' || p_actor || '|' || p_event || '|' || p_payload::text || '|' ||
     to_char(p_ts AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US'), 'UTF8')), 'hex') $$;

CREATE FUNCTION audit(p_event text, p_payload jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = nexus, pg_temp AS
$$
DECLARE v_prev text; v_ts timestamptz := clock();
BEGIN
  PERFORM pg_advisory_xact_lock(7001);
  SELECT hash INTO v_prev FROM audit_log ORDER BY seq DESC LIMIT 1;
  v_prev := COALESCE(v_prev, repeat('0', 64));
  INSERT INTO audit_log (ts, actor, event, payload, prev_hash, hash)
  VALUES (v_ts, session_user, p_event, p_payload, v_prev,
          audit_hash(v_prev, session_user::text, p_event, p_payload, v_ts));
END $$;

CREATE FUNCTION verify_audit_chain() RETURNS bigint
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = nexus, pg_temp AS
$$
DECLARE r audit_log; v_prev text := repeat('0', 64);
BEGIN
  FOR r IN SELECT * FROM audit_log ORDER BY seq LOOP
    IF r.prev_hash <> v_prev
       OR r.hash <> audit_hash(r.prev_hash, r.actor, r.event, r.payload, r.ts) THEN
      RETURN r.seq;
    END IF;
    v_prev := r.hash;
  END LOOP;
  RETURN NULL;
END $$;

-- ---------------------------------------------------------------- budget
CREATE TABLE budget_reservation (
  id             bigserial PRIMARY KEY,
  idem_key       text NOT NULL UNIQUE,
  category       text NOT NULL CHECK (category IN ('research','operations')),
  period_month   date NOT NULL,
  cycle_id       int,
  reserved_cents int  NOT NULL CHECK (reserved_cents > 0),
  actual_cents   int  CHECK (actual_cents >= 0),
  status         text NOT NULL DEFAULT 'reserved' CHECK (status IN ('reserved','settled','released')),
  overrun        boolean NOT NULL DEFAULT false,
  description    text NOT NULL,
  requested_by   text NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT nexus.clock(),
  settled_at     timestamptz,
  CHECK ((category = 'research') = (cycle_id IS NOT NULL))
);

CREATE TABLE budget_alert (
  id           bigserial PRIMARY KEY,
  period_month date NOT NULL,
  scope        text NOT NULL,
  level        text NOT NULL CHECK (level IN ('80','100')),
  created_at   timestamptz NOT NULL DEFAULT nexus.clock(),
  UNIQUE (period_month, scope, level)
);

CREATE TABLE budget_stop (
  period_month date PRIMARY KEY,
  reason       text NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT nexus.clock()
);

-- Cout engage : reserve = montant reserve ; regle = montant reel (jamais ecrete) ; libere = 0.
CREATE FUNCTION committed(p_month date, p_category text DEFAULT NULL) RETURNS int
LANGUAGE sql STABLE SET search_path = nexus, pg_temp AS
$$ SELECT COALESCE(SUM(CASE status WHEN 'reserved' THEN reserved_cents
                                    WHEN 'settled'  THEN actual_cents ELSE 0 END), 0)::int
   FROM budget_reservation
   WHERE period_month = p_month AND (p_category IS NULL OR category = p_category) $$;

-- Un cycle de recherche peut chevaucher deux mois : on somme sur le cycle seul.
CREATE FUNCTION committed_cycle(p_cycle int) RETURNS int
LANGUAGE sql STABLE SET search_path = nexus, pg_temp AS
$$ SELECT COALESCE(SUM(CASE status WHEN 'reserved' THEN reserved_cents
                                    WHEN 'settled'  THEN actual_cents ELSE 0 END), 0)::int
   FROM budget_reservation WHERE category = 'research' AND cycle_id = p_cycle $$;

CREATE FUNCTION touch_alerts(p_month date) RETURNS void
LANGUAGE plpgsql SET search_path = nexus, pg_temp AS
$$
DECLARE pol policy; v_op int; v_ops int; v_res int; n int;
BEGIN
  SELECT * INTO pol FROM policy;
  v_op  := pol.total_cents - pol.reserve_cents;
  v_ops := committed(p_month);
  v_res := committed(p_month, 'research');
  IF v_ops * 100 >= pol.alert_percent * v_op THEN
    INSERT INTO budget_alert (period_month, scope, level) VALUES (p_month, 'operating', '80')
      ON CONFLICT DO NOTHING;
    GET DIAGNOSTICS n = ROW_COUNT;
    IF n > 0 THEN PERFORM audit('budget_alert', jsonb_build_object('month', p_month, 'scope', 'operating', 'level', '80')); END IF;
  END IF;
  IF v_ops >= v_op THEN
    INSERT INTO budget_alert (period_month, scope, level) VALUES (p_month, 'operating', '100')
      ON CONFLICT DO NOTHING;
    GET DIAGNOSTICS n = ROW_COUNT;
    IF n > 0 THEN PERFORM audit('budget_alert', jsonb_build_object('month', p_month, 'scope', 'operating', 'level', '100')); END IF;
  END IF;
  IF v_res * 100 >= pol.alert_percent * pol.research_cap_cents THEN
    INSERT INTO budget_alert (period_month, scope, level) VALUES (p_month, 'research', '80')
      ON CONFLICT DO NOTHING;
    GET DIAGNOSTICS n = ROW_COUNT;
    IF n > 0 THEN PERFORM audit('budget_alert', jsonb_build_object('month', p_month, 'scope', 'research', 'level', '80')); END IF;
  END IF;
  IF v_res >= pol.research_cap_cents THEN
    INSERT INTO budget_alert (period_month, scope, level) VALUES (p_month, 'research', '100')
      ON CONFLICT DO NOTHING;
    GET DIAGNOSTICS n = ROW_COUNT;
    IF n > 0 THEN PERFORM audit('budget_alert', jsonb_build_object('month', p_month, 'scope', 'research', 'level', '100')); END IF;
  END IF;
END $$;

CREATE FUNCTION reserve_budget(p_idem text, p_category text, p_cents int, p_desc text)
RETURNS result LANGUAGE plpgsql SECURITY DEFINER SET search_path = nexus, pg_temp AS
$$
DECLARE
  pol policy; v_me principal; v_now timestamptz; v_month date; v_cycle int;
  v_id bigint; v_op int; v_exist budget_reservation;
BEGIN
  PERFORM pg_advisory_xact_lock(7001);
  SELECT * INTO v_me FROM principal WHERE db_role = session_user;
  IF NOT FOUND OR v_me.kind NOT IN ('worker','transport','founder') THEN
    RAISE EXCEPTION 'forbidden' USING ERRCODE = 'P0001';
  END IF;
  IF p_idem IS NULL OR p_idem = '' THEN RETURN ROW(false, 'idem_required', NULL)::result; END IF;
  IF p_cents IS NULL OR p_cents <= 0 THEN RETURN ROW(false, 'unknown_cost', NULL)::result; END IF;
  IF p_category IS NULL OR p_category NOT IN ('research','operations') THEN
    RETURN ROW(false, 'bad_category', NULL)::result;
  END IF;
  SELECT * INTO v_exist FROM budget_reservation WHERE idem_key = p_idem;
  IF FOUND THEN
    IF v_exist.category = p_category AND v_exist.reserved_cents = p_cents THEN
      RETURN ROW(true, 'ok', v_exist.id)::result;
    END IF;
    RETURN ROW(false, 'idem_conflict', NULL)::result;
  END IF;

  SELECT * INTO pol FROM policy;
  v_now := clock(); v_month := paris_month(v_now); v_op := pol.total_cents - pol.reserve_cents;

  IF EXISTS (SELECT 1 FROM budget_stop WHERE period_month = v_month) THEN
    PERFORM audit('budget_refused', jsonb_build_object('idem', p_idem, 'code', 'budget_stopped'));
    RETURN ROW(false, 'budget_stopped', NULL)::result;
  END IF;
  IF committed(v_month) + p_cents > v_op THEN
    PERFORM touch_alerts(v_month);
    PERFORM audit('budget_refused', jsonb_build_object('idem', p_idem, 'code', 'budget_exceeded:operating', 'cents', p_cents));
    RETURN ROW(false, 'budget_exceeded:operating', NULL)::result;
  END IF;
  IF p_category = 'research' THEN
    v_cycle := cycle_of(v_now);
    IF committed(v_month, 'research') + p_cents > pol.research_cap_cents THEN
      PERFORM audit('budget_refused', jsonb_build_object('idem', p_idem, 'code', 'budget_exceeded:research_month', 'cents', p_cents));
      RETURN ROW(false, 'budget_exceeded:research_month', NULL)::result;
    END IF;
    IF committed_cycle(v_cycle) + p_cents > pol.cycle_cap_cents THEN
      PERFORM audit('budget_refused', jsonb_build_object('idem', p_idem, 'code', 'budget_exceeded:research_cycle', 'cents', p_cents));
      RETURN ROW(false, 'budget_exceeded:research_cycle', NULL)::result;
    END IF;
  END IF;

  INSERT INTO budget_reservation (idem_key, category, period_month, cycle_id, reserved_cents, description, requested_by)
  VALUES (p_idem, p_category, v_month, v_cycle, p_cents, COALESCE(p_desc, ''), session_user)
  RETURNING id INTO v_id;
  PERFORM audit('budget_reserved', jsonb_build_object('id', v_id, 'category', p_category, 'cents', p_cents, 'cycle', v_cycle));
  PERFORM touch_alerts(v_month);
  RETURN ROW(true, 'ok', v_id)::result;
END $$;

-- Regle un cout reel. Un depassement tardif est conserve tel quel et peut
-- declencher l'arret du mois d'origine de la reservation.
CREATE FUNCTION settle_budget(p_id bigint, p_actual int)
RETURNS result LANGUAGE plpgsql SECURITY DEFINER SET search_path = nexus, pg_temp AS
$$
DECLARE pol policy; v_me principal; r budget_reservation; v_op int;
BEGIN
  PERFORM pg_advisory_xact_lock(7001);
  SELECT * INTO v_me FROM principal WHERE db_role = session_user;
  IF NOT FOUND OR v_me.kind NOT IN ('worker','transport') THEN
    RAISE EXCEPTION 'forbidden' USING ERRCODE = 'P0001';
  END IF;
  IF p_actual IS NULL OR p_actual < 0 THEN RETURN ROW(false, 'unknown_cost', NULL)::result; END IF;
  SELECT * INTO r FROM budget_reservation WHERE id = p_id FOR UPDATE;
  IF NOT FOUND THEN RETURN ROW(false, 'not_found', NULL)::result; END IF;
  IF r.status = 'settled' THEN
    IF r.actual_cents = p_actual THEN RETURN ROW(true, 'ok', r.id)::result; END IF;
    RETURN ROW(false, 'already_settled', NULL)::result;
  END IF;
  IF r.status = 'released' THEN RETURN ROW(false, 'released', NULL)::result; END IF;

  UPDATE budget_reservation
     SET actual_cents = p_actual, status = 'settled', settled_at = clock(),
         overrun = p_actual > reserved_cents
   WHERE id = p_id;
  PERFORM audit('budget_settled', jsonb_build_object('id', p_id, 'reserved', r.reserved_cents, 'actual', p_actual, 'overrun', p_actual > r.reserved_cents));

  SELECT * INTO pol FROM policy;
  v_op := pol.total_cents - pol.reserve_cents;
  IF committed(r.period_month) > v_op
     OR committed(r.period_month, 'research') > pol.research_cap_cents
     OR (r.cycle_id IS NOT NULL AND committed_cycle(r.cycle_id) > pol.cycle_cap_cents) THEN
    INSERT INTO budget_stop (period_month, reason) VALUES (r.period_month, 'late_cost_over_cap')
      ON CONFLICT DO NOTHING;
    PERFORM audit('budget_stop', jsonb_build_object('month', r.period_month, 'reservation', p_id));
  END IF;
  PERFORM touch_alerts(r.period_month);
  RETURN ROW(true, 'ok', r.id)::result;
END $$;

CREATE FUNCTION release_budget(p_id bigint)
RETURNS result LANGUAGE plpgsql SECURITY DEFINER SET search_path = nexus, pg_temp AS
$$
DECLARE v_me principal; r budget_reservation;
BEGIN
  PERFORM pg_advisory_xact_lock(7001);
  SELECT * INTO v_me FROM principal WHERE db_role = session_user;
  IF NOT FOUND OR v_me.kind NOT IN ('worker','transport','founder') THEN
    RAISE EXCEPTION 'forbidden' USING ERRCODE = 'P0001';
  END IF;
  SELECT * INTO r FROM budget_reservation WHERE id = p_id FOR UPDATE;
  IF NOT FOUND THEN RETURN ROW(false, 'not_found', NULL)::result; END IF;
  IF r.status = 'released' THEN RETURN ROW(true, 'ok', r.id)::result; END IF;
  IF r.status <> 'reserved' THEN RETURN ROW(false, 'not_releasable', NULL)::result; END IF;
  UPDATE budget_reservation SET status = 'released', settled_at = clock() WHERE id = p_id;
  PERFORM audit('budget_released', jsonb_build_object('id', p_id));
  RETURN ROW(true, 'ok', p_id)::result;
END $$;

CREATE FUNCTION budget_status() RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = nexus, pg_temp AS
$$
DECLARE pol policy; v_now timestamptz := clock(); v_month date; v_cycle int;
BEGIN
  SELECT * INTO pol FROM policy;
  v_month := paris_month(v_now); v_cycle := cycle_of(v_now);
  RETURN jsonb_build_object(
    'month', v_month,
    'operating', jsonb_build_object('committed', committed(v_month), 'cap', pol.total_cents - pol.reserve_cents),
    'research',  jsonb_build_object('committed', committed(v_month, 'research'), 'cap', pol.research_cap_cents),
    'cycle',     jsonb_build_object('id', v_cycle, 'committed', committed_cycle(v_cycle), 'cap', pol.cycle_cap_cents),
    'stopped',   EXISTS (SELECT 1 FROM budget_stop WHERE period_month = v_month),
    'reserve_untouchable', pol.reserve_cents);
END $$;

-- ---------------------------------------------------------------- suppression
CREATE TABLE suppression (
  recipient_norm text PRIMARY KEY,
  reason         text NOT NULL,
  added_by       text NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT nexus.clock()
);

-- ---------------------------------------------------------------- messages
CREATE TABLE outbox_message (
  id             bigserial PRIMARY KEY,
  idem_key       text NOT NULL UNIQUE,
  version        int  NOT NULL DEFAULT 1 CHECK (version BETWEEN 1 AND 3),
  lineage_id     bigint,
  supersedes     bigint REFERENCES outbox_message (id),
  author_id      int  NOT NULL REFERENCES principal (id),
  channel        text NOT NULL CHECK (channel IN ('email','internal')),
  recipient_norm text NOT NULL,
  subject        text NOT NULL,
  body           text NOT NULL,
  max_cost_cents int  NOT NULL CHECK (max_cost_cents >= 0),
  purpose        text NOT NULL,
  content_hash   text NOT NULL,
  state          text NOT NULL DEFAULT 'draft'
                 CHECK (state IN ('draft','reviewed','rejected','approved','sending','sent','blocked')),
  blocked_reason text,
  lease_until    timestamptz,
  claimed_at     timestamptz,
  sent_at        timestamptz,
  provider_ref   text,
  attempts       int NOT NULL DEFAULT 0,
  created_at     timestamptz NOT NULL DEFAULT nexus.clock()
);
CREATE INDEX ON outbox_message (state, id);
CREATE INDEX ON outbox_message (recipient_norm);

CREATE FUNCTION message_hash(p_channel text, p_recipient text, p_subject text, p_body text,
                             p_max_cost int, p_purpose text, p_author int, p_version int)
RETURNS text LANGUAGE sql IMMUTABLE AS
$$ SELECT encode(sha256(convert_to(jsonb_build_object(
     'channel', p_channel, 'recipient', p_recipient, 'subject', p_subject, 'body', p_body,
     'max_cost_cents', p_max_cost, 'purpose', p_purpose, 'author', p_author,
     'version', p_version)::text, 'UTF8')), 'hex') $$;

-- Le contenu d'un message ne change jamais : une correction cree une nouvelle version.
CREATE FUNCTION outbox_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
  IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'immutable_table' USING ERRCODE = 'P0001'; END IF;
  IF (NEW.idem_key, NEW.version, NEW.lineage_id, NEW.supersedes, NEW.author_id, NEW.channel, NEW.recipient_norm,
      NEW.subject, NEW.body, NEW.max_cost_cents, NEW.purpose, NEW.content_hash)
     IS DISTINCT FROM
     (OLD.idem_key, OLD.version, OLD.lineage_id, OLD.supersedes, OLD.author_id, OLD.channel, OLD.recipient_norm,
      OLD.subject, OLD.body, OLD.max_cost_cents, OLD.purpose, OLD.content_hash) THEN
    RAISE EXCEPTION 'content_immutable' USING ERRCODE = 'P0001';
  END IF;
  IF NEW.state <> OLD.state AND NOT (
       (OLD.state = 'draft'    AND NEW.state IN ('reviewed','rejected','blocked')) OR
       (OLD.state = 'reviewed' AND NEW.state IN ('approved','rejected','blocked')) OR
       (OLD.state = 'approved' AND NEW.state IN ('sending','blocked')) OR
       (OLD.state = 'sending'  AND NEW.state IN ('sent','approved','blocked'))) THEN
    RAISE EXCEPTION 'bad_transition:%->%', OLD.state, NEW.state USING ERRCODE = 'P0001';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER outbox_content_immutable BEFORE UPDATE OR DELETE ON outbox_message
  FOR EACH ROW EXECUTE FUNCTION outbox_guard();

CREATE TABLE review (
  id           bigserial PRIMARY KEY,
  message_id   bigint NOT NULL REFERENCES outbox_message (id),
  reviewer_id  int    NOT NULL REFERENCES principal (id),
  content_hash text   NOT NULL,
  verdict      text   NOT NULL CHECK (verdict IN ('pass','reject')),
  dimensions   jsonb  NOT NULL,
  reasons      text,
  created_at   timestamptz NOT NULL DEFAULT nexus.clock(),
  UNIQUE (message_id, reviewer_id)
);
CREATE TRIGGER review_no_mod BEFORE UPDATE OR DELETE ON review
  FOR EACH ROW EXECUTE FUNCTION no_mutation();

CREATE TABLE approval (
  id             bigserial PRIMARY KEY,
  message_id     bigint NOT NULL UNIQUE REFERENCES outbox_message (id),
  content_hash   text   NOT NULL,
  approver_id    int    NOT NULL REFERENCES principal (id),
  max_cost_cents int    NOT NULL,
  reservation_id bigint REFERENCES budget_reservation (id),
  valid_until    timestamptz NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT nexus.clock()
);
CREATE TRIGGER approval_no_mod BEFORE UPDATE OR DELETE ON approval
  FOR EACH ROW EXECUTE FUNCTION no_mutation();

CREATE TABLE ops_alert (
  id         bigserial PRIMARY KEY,
  kind       text NOT NULL,
  ref        text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT nexus.clock(),
  UNIQUE (kind, ref)
);

-- Interne : bloque un message et libere sa reservation de transport.
CREATE FUNCTION block_message(p_id bigint, p_reason text) RETURNS void
LANGUAGE plpgsql SET search_path = nexus, pg_temp AS
$$
DECLARE v_res bigint;
BEGIN
  UPDATE outbox_message SET state = 'blocked', blocked_reason = p_reason, lease_until = NULL
   WHERE id = p_id AND state IN ('draft','reviewed','approved','sending');
  SELECT reservation_id INTO v_res FROM approval WHERE message_id = p_id;
  IF v_res IS NOT NULL THEN
    UPDATE budget_reservation SET status = 'released', settled_at = clock()
     WHERE id = v_res AND status = 'reserved';
  END IF;
  PERFORM audit('message_blocked', jsonb_build_object('message', p_id, 'reason', p_reason));
END $$;

CREATE FUNCTION create_message(p_idem text, p_channel text, p_recipient text, p_subject text,
                               p_body text, p_max_cost int, p_purpose text)
RETURNS result LANGUAGE plpgsql SECURITY DEFINER SET search_path = nexus, pg_temp AS
$$
DECLARE v_me principal; v_norm text; v_hash text; v_id bigint; v_exist outbox_message;
BEGIN
  PERFORM pg_advisory_xact_lock(7001);
  SELECT * INTO v_me FROM principal WHERE db_role = session_user;
  IF NOT FOUND OR v_me.kind <> 'worker' THEN RAISE EXCEPTION 'forbidden' USING ERRCODE = 'P0001'; END IF;
  IF p_idem IS NULL OR p_idem = '' THEN RETURN ROW(false, 'idem_required', NULL)::result; END IF;
  IF p_channel NOT IN ('email','internal') OR p_subject IS NULL OR p_body IS NULL
     OR p_purpose IS NULL OR p_purpose = '' OR p_max_cost IS NULL OR p_max_cost < 0 THEN
    RETURN ROW(false, 'bad_input', NULL)::result;
  END IF;
  v_norm := lower(btrim(COALESCE(p_recipient, '')));
  IF p_channel = 'email' AND (length(v_norm) > 254 OR v_norm !~ '^[^@\s]+@[^@\s]+\.[^@\s]+$') THEN
    RETURN ROW(false, 'bad_recipient', NULL)::result;
  END IF;
  v_hash := message_hash(p_channel, v_norm, p_subject, p_body, p_max_cost, p_purpose, v_me.id, 1);
  SELECT * INTO v_exist FROM outbox_message WHERE idem_key = p_idem;
  IF FOUND THEN
    IF v_exist.content_hash = v_hash THEN RETURN ROW(true, 'ok', v_exist.id)::result; END IF;
    RETURN ROW(false, 'idem_conflict', NULL)::result;
  END IF;
  IF EXISTS (SELECT 1 FROM suppression WHERE recipient_norm = v_norm) THEN
    PERFORM audit('message_refused', jsonb_build_object('idem', p_idem, 'code', 'suppressed'));
    RETURN ROW(false, 'suppressed', NULL)::result;
  END IF;
  v_id := nextval(pg_get_serial_sequence('nexus.outbox_message', 'id'));
  INSERT INTO outbox_message (id, idem_key, lineage_id, author_id, channel, recipient_norm, subject, body,
                              max_cost_cents, purpose, content_hash)
  VALUES (v_id, p_idem, v_id, v_me.id, p_channel, v_norm, p_subject, p_body, p_max_cost, p_purpose, v_hash);
  PERFORM audit('message_created', jsonb_build_object('id', v_id, 'hash', v_hash));
  RETURN ROW(true, 'ok', v_id)::result;
END $$;

-- Correction apres rejet : nouvelle version, jamais de modification. Deux corrections au plus.
CREATE FUNCTION create_revision(p_prev bigint, p_idem text, p_subject text, p_body text,
                                p_max_cost int, p_purpose text)
RETURNS result LANGUAGE plpgsql SECURITY DEFINER SET search_path = nexus, pg_temp AS
$$
DECLARE v_me principal; prev outbox_message; v_hash text; v_id bigint; v_exist outbox_message;
BEGIN
  PERFORM pg_advisory_xact_lock(7001);
  SELECT * INTO v_me FROM principal WHERE db_role = session_user;
  IF NOT FOUND OR v_me.kind <> 'worker' THEN RAISE EXCEPTION 'forbidden' USING ERRCODE = 'P0001'; END IF;
  SELECT * INTO prev FROM outbox_message WHERE id = p_prev;
  IF NOT FOUND THEN RETURN ROW(false, 'not_found', NULL)::result; END IF;
  IF prev.author_id <> v_me.id THEN RAISE EXCEPTION 'forbidden' USING ERRCODE = 'P0001'; END IF;
  IF p_idem IS NULL OR p_idem = '' THEN RETURN ROW(false, 'idem_required', NULL)::result; END IF;
  IF p_subject IS NULL OR p_body IS NULL OR p_purpose IS NULL OR p_max_cost IS NULL OR p_max_cost < 0 THEN
    RETURN ROW(false, 'bad_input', NULL)::result;
  END IF;
  v_hash := message_hash(prev.channel, prev.recipient_norm, p_subject, p_body, p_max_cost, p_purpose, v_me.id, prev.version + 1);
  SELECT * INTO v_exist FROM outbox_message WHERE idem_key = p_idem;
  IF FOUND THEN
    IF v_exist.content_hash = v_hash THEN RETURN ROW(true, 'ok', v_exist.id)::result; END IF;
    RETURN ROW(false, 'idem_conflict', NULL)::result;
  END IF;
  IF prev.state <> 'rejected' THEN RETURN ROW(false, 'not_rejected', NULL)::result; END IF;
  IF prev.version >= 3 THEN
    PERFORM audit('lineage_paused', jsonb_build_object('lineage', prev.lineage_id));
    RETURN ROW(false, 'paused_after_two_corrections', NULL)::result;
  END IF;
  IF p_subject = prev.subject AND p_body = prev.body AND p_max_cost = prev.max_cost_cents AND p_purpose = prev.purpose THEN
    RETURN ROW(false, 'no_change', NULL)::result;
  END IF;
  IF EXISTS (SELECT 1 FROM suppression WHERE recipient_norm = prev.recipient_norm) THEN
    RETURN ROW(false, 'suppressed', NULL)::result;
  END IF;
  INSERT INTO outbox_message (idem_key, version, lineage_id, supersedes, author_id, channel, recipient_norm,
                              subject, body, max_cost_cents, purpose, content_hash)
  VALUES (p_idem, prev.version + 1, prev.lineage_id, prev.id, v_me.id, prev.channel, prev.recipient_norm,
          p_subject, p_body, p_max_cost, p_purpose, v_hash)
  RETURNING id INTO v_id;
  PERFORM audit('message_revised', jsonb_build_object('id', v_id, 'supersedes', prev.id, 'hash', v_hash));
  RETURN ROW(true, 'ok', v_id)::result;
END $$;

-- L'identite du relecteur vient de la session authentifiee, jamais d'un parametre.
CREATE FUNCTION submit_review(p_message bigint, p_verdict text, p_dims jsonb, p_reasons text)
RETURNS result LANGUAGE plpgsql SECURITY DEFINER SET search_path = nexus, pg_temp AS
$$
DECLARE v_me principal; m outbox_message; rv review; k text;
BEGIN
  PERFORM pg_advisory_xact_lock(7001);
  SELECT * INTO v_me FROM principal WHERE db_role = session_user;
  IF NOT FOUND OR v_me.kind <> 'censor' THEN RAISE EXCEPTION 'forbidden' USING ERRCODE = 'P0001'; END IF;
  SELECT * INTO m FROM outbox_message WHERE id = p_message FOR UPDATE;
  IF NOT FOUND THEN RETURN ROW(false, 'not_found', NULL)::result; END IF;
  IF m.author_id = v_me.id THEN RETURN ROW(false, 'self_review', NULL)::result; END IF;
  IF p_verdict IS NULL OR p_verdict NOT IN ('pass','reject') THEN RETURN ROW(false, 'bad_verdict', NULL)::result; END IF;
  SELECT * INTO rv FROM review WHERE message_id = p_message AND reviewer_id = v_me.id;
  IF FOUND THEN
    IF rv.verdict = p_verdict THEN RETURN ROW(true, 'ok', rv.id)::result; END IF;
    RETURN ROW(false, 'already_reviewed', NULL)::result;
  END IF;
  IF m.state <> 'draft' THEN RETURN ROW(false, 'not_reviewable', NULL)::result; END IF;
  IF p_dims IS NULL OR jsonb_typeof(p_dims) <> 'object' THEN RETURN ROW(false, 'bad_dimensions', NULL)::result; END IF;
  FOREACH k IN ARRAY ARRAY['orthographe','ton','promesses_preuves','repetitions'] LOOP
    IF jsonb_typeof(p_dims -> k) IS DISTINCT FROM 'boolean' THEN
      RETURN ROW(false, 'bad_dimensions', NULL)::result;
    END IF;
  END LOOP;
  IF (SELECT count(*) FROM jsonb_object_keys(p_dims)) <> 4 THEN RETURN ROW(false, 'bad_dimensions', NULL)::result; END IF;
  IF p_verdict = 'pass' AND NOT (p_dims @> '{"orthographe":true,"ton":true,"promesses_preuves":true,"repetitions":true}') THEN
    RETURN ROW(false, 'pass_requires_all_dimensions', NULL)::result;
  END IF;
  IF p_verdict = 'reject' AND (p_reasons IS NULL OR btrim(p_reasons) = '') THEN
    RETURN ROW(false, 'reasons_required', NULL)::result;
  END IF;
  INSERT INTO review (message_id, reviewer_id, content_hash, verdict, dimensions, reasons)
  VALUES (p_message, v_me.id, m.content_hash, p_verdict, p_dims, p_reasons)
  RETURNING * INTO rv;
  UPDATE outbox_message SET state = CASE p_verdict WHEN 'pass' THEN 'reviewed' ELSE 'rejected' END
   WHERE id = p_message;
  PERFORM audit('message_reviewed', jsonb_build_object('message', p_message, 'verdict', p_verdict, 'hash', m.content_hash));
  RETURN ROW(true, 'ok', rv.id)::result;
END $$;

-- Approbation : liee au hash exact, a une duree, et au budget de transport.
CREATE FUNCTION approve(p_message bigint, p_hash text, p_valid_hours int)
RETURNS result LANGUAGE plpgsql SECURITY DEFINER SET search_path = nexus, pg_temp AS
$$
DECLARE
  v_me principal; m outbox_message; a approval; v_res result; v_resid bigint;
  v_now timestamptz := clock();
BEGIN
  PERFORM pg_advisory_xact_lock(7001);
  SELECT * INTO v_me FROM principal WHERE db_role = session_user;
  IF NOT FOUND OR v_me.kind <> 'founder' THEN RAISE EXCEPTION 'forbidden' USING ERRCODE = 'P0001'; END IF;
  SELECT * INTO m FROM outbox_message WHERE id = p_message FOR UPDATE;
  IF NOT FOUND THEN RETURN ROW(false, 'not_found', NULL)::result; END IF;
  SELECT * INTO a FROM approval WHERE message_id = p_message;
  IF FOUND THEN
    IF a.content_hash = p_hash THEN RETURN ROW(true, 'ok', a.id)::result; END IF;
    RETURN ROW(false, 'stale_hash', NULL)::result;
  END IF;
  IF m.state <> 'reviewed' THEN RETURN ROW(false, 'not_reviewed', NULL)::result; END IF;
  IF p_hash IS DISTINCT FROM m.content_hash THEN RETURN ROW(false, 'stale_hash', NULL)::result; END IF;
  IF message_hash(m.channel, m.recipient_norm, m.subject, m.body, m.max_cost_cents, m.purpose, m.author_id, m.version)
     <> m.content_hash THEN
    RETURN ROW(false, 'hash_mismatch', NULL)::result;
  END IF;
  IF p_valid_hours IS NULL OR p_valid_hours < 1 OR p_valid_hours > 168 THEN RETURN ROW(false, 'bad_validity', NULL)::result; END IF;
  IF NOT EXISTS (SELECT 1 FROM review r JOIN principal p ON p.id = r.reviewer_id
                  WHERE r.message_id = m.id AND r.verdict = 'pass' AND r.content_hash = m.content_hash
                    AND p.kind = 'censor' AND r.reviewer_id <> m.author_id) THEN
    RETURN ROW(false, 'no_independent_review', NULL)::result;
  END IF;
  IF EXISTS (SELECT 1 FROM suppression WHERE recipient_norm = m.recipient_norm) THEN
    PERFORM block_message(m.id, 'suppressed');
    RETURN ROW(false, 'suppressed', NULL)::result;
  END IF;
  IF m.max_cost_cents > 0 THEN
    v_res := reserve_budget('approval:' || m.id, 'operations', m.max_cost_cents, 'transport message ' || m.id);
    IF NOT v_res.ok THEN RETURN v_res; END IF;
    v_resid := v_res.id;
  END IF;
  INSERT INTO approval (message_id, content_hash, approver_id, max_cost_cents, reservation_id, valid_until)
  VALUES (m.id, m.content_hash, v_me.id, m.max_cost_cents, v_resid, v_now + make_interval(hours => p_valid_hours))
  RETURNING * INTO a;
  UPDATE outbox_message SET state = 'approved' WHERE id = m.id;
  PERFORM audit('message_approved', jsonb_build_object('message', m.id, 'hash', m.content_hash, 'until', a.valid_until));
  RETURN ROW(true, 'ok', a.id)::result;
END $$;

CREATE FUNCTION founder_reject(p_message bigint, p_reason text)
RETURNS result LANGUAGE plpgsql SECURITY DEFINER SET search_path = nexus, pg_temp AS
$$
DECLARE v_me principal; m outbox_message;
BEGIN
  PERFORM pg_advisory_xact_lock(7001);
  SELECT * INTO v_me FROM principal WHERE db_role = session_user;
  IF NOT FOUND OR v_me.kind <> 'founder' THEN RAISE EXCEPTION 'forbidden' USING ERRCODE = 'P0001'; END IF;
  SELECT * INTO m FROM outbox_message WHERE id = p_message FOR UPDATE;
  IF NOT FOUND THEN RETURN ROW(false, 'not_found', NULL)::result; END IF;
  IF m.state <> 'reviewed' THEN RETURN ROW(false, 'not_reviewed', NULL)::result; END IF;
  UPDATE outbox_message SET state = 'rejected' WHERE id = m.id;
  PERFORM audit('message_rejected_by_founder', jsonb_build_object('message', m.id, 'reason', p_reason));
  RETURN ROW(true, 'ok', m.id)::result;
END $$;

-- Opposition : bloque ce qui n'est pas encore parti. Un message deja 'sending' est
-- controle par precheck_before_send juste avant l'envoi reel.
CREATE FUNCTION add_suppression(p_recipient text, p_reason text)
RETURNS result LANGUAGE plpgsql SECURITY DEFINER SET search_path = nexus, pg_temp AS
$$
DECLARE v_me principal; v_norm text; r outbox_message; n int;
BEGIN
  PERFORM pg_advisory_xact_lock(7001);
  SELECT * INTO v_me FROM principal WHERE db_role = session_user;
  IF NOT FOUND THEN RAISE EXCEPTION 'forbidden' USING ERRCODE = 'P0001'; END IF;
  v_norm := lower(btrim(COALESCE(p_recipient, '')));
  IF v_norm = '' THEN RETURN ROW(false, 'bad_recipient', NULL)::result; END IF;
  INSERT INTO suppression (recipient_norm, reason, added_by) VALUES (v_norm, COALESCE(p_reason, ''), session_user)
    ON CONFLICT DO NOTHING;
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n > 0 THEN PERFORM audit('suppression_added', jsonb_build_object('recipient_hash', encode(sha256(convert_to(v_norm, 'UTF8')), 'hex'))); END IF;
  FOR r IN SELECT * FROM outbox_message
            WHERE recipient_norm = v_norm AND state IN ('draft','reviewed','approved') LOOP
    PERFORM block_message(r.id, 'suppressed');
  END LOOP;
  RETURN ROW(true, 'ok', NULL)::result;
END $$;

-- Reservation d'envoi : une seule personne la prend, apres tous les controles.
CREATE FUNCTION claim_outbox(p_lease_seconds int DEFAULT 300)
RETURNS TABLE (message_id bigint, recipient text, subject text, body text, content_hash text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = nexus, pg_temp AS
$$
DECLARE
  v_me principal; pol policy; v_now timestamptz := clock(); r outbox_message; a approval;
  v_used int; v_email_blocked boolean;
BEGIN
  PERFORM pg_advisory_xact_lock(7001);
  SELECT * INTO v_me FROM principal WHERE db_role = session_user;
  IF NOT FOUND OR v_me.kind <> 'transport' THEN RAISE EXCEPTION 'forbidden' USING ERRCODE = 'P0001'; END IF;
  IF p_lease_seconds IS NULL OR p_lease_seconds < 10 OR p_lease_seconds > 3600 THEN
    RAISE EXCEPTION 'bad_lease' USING ERRCODE = 'P0001';
  END IF;
  SELECT * INTO pol FROM policy;
  SELECT count(*) INTO v_used FROM outbox_message o
   WHERE o.channel = 'email' AND o.claimed_at IS NOT NULL AND paris_day(o.claimed_at) = paris_day(v_now);
  v_email_blocked := v_used >= pol.daily_email_cap;
  LOOP
    SELECT * INTO r FROM outbox_message o
     WHERE (o.state = 'approved' AND NOT (o.channel = 'email' AND v_email_blocked))
        OR (o.state = 'sending' AND o.lease_until < v_now)
     ORDER BY o.id LIMIT 1 FOR UPDATE SKIP LOCKED;
    IF NOT FOUND THEN RETURN; END IF;
    SELECT * INTO a FROM approval ap WHERE ap.message_id = r.id;
    IF NOT FOUND OR a.valid_until <= v_now THEN
      PERFORM block_message(r.id, 'approval_expired'); CONTINUE;
    END IF;
    IF message_hash(r.channel, r.recipient_norm, r.subject, r.body, r.max_cost_cents, r.purpose, r.author_id, r.version)
         <> r.content_hash OR a.content_hash <> r.content_hash THEN
      PERFORM block_message(r.id, 'hash_mismatch'); CONTINUE;
    END IF;
    IF EXISTS (SELECT 1 FROM suppression s WHERE s.recipient_norm = r.recipient_norm) THEN
      PERFORM block_message(r.id, 'suppressed'); CONTINUE;
    END IF;
    UPDATE outbox_message o
       SET state = 'sending', lease_until = v_now + make_interval(secs => p_lease_seconds),
           claimed_at = COALESCE(o.claimed_at, v_now), attempts = o.attempts + 1
     WHERE o.id = r.id;
    PERFORM audit('message_claimed', jsonb_build_object('message', r.id));
    RETURN QUERY SELECT r.id, r.recipient_norm, r.subject, r.body, r.content_hash;
    RETURN;
  END LOOP;
END $$;

-- A appeler juste avant l'envoi reel : repasse les controles qui peuvent avoir change.
CREATE FUNCTION precheck_before_send(p_message bigint)
RETURNS result LANGUAGE plpgsql SECURITY DEFINER SET search_path = nexus, pg_temp AS
$$
DECLARE v_me principal; r outbox_message; a approval; v_now timestamptz := clock();
BEGIN
  PERFORM pg_advisory_xact_lock(7001);
  SELECT * INTO v_me FROM principal WHERE db_role = session_user;
  IF NOT FOUND OR v_me.kind <> 'transport' THEN RAISE EXCEPTION 'forbidden' USING ERRCODE = 'P0001'; END IF;
  SELECT * INTO r FROM outbox_message WHERE id = p_message FOR UPDATE;
  IF NOT FOUND THEN RETURN ROW(false, 'not_found', NULL)::result; END IF;
  IF r.state <> 'sending' OR r.lease_until < v_now THEN RETURN ROW(false, 'not_sending', NULL)::result; END IF;
  SELECT * INTO a FROM approval WHERE message_id = r.id;
  IF NOT FOUND OR a.valid_until <= v_now THEN
    PERFORM block_message(r.id, 'approval_expired'); RETURN ROW(false, 'approval_expired', NULL)::result;
  END IF;
  IF EXISTS (SELECT 1 FROM suppression WHERE recipient_norm = r.recipient_norm) THEN
    PERFORM block_message(r.id, 'suppressed'); RETURN ROW(false, 'suppressed', NULL)::result;
  END IF;
  RETURN ROW(true, 'ok', r.id)::result;
END $$;

CREATE FUNCTION mark_sent(p_message bigint, p_provider_ref text, p_actual_cost int)
RETURNS result LANGUAGE plpgsql SECURITY DEFINER SET search_path = nexus, pg_temp AS
$$
DECLARE v_me principal; r outbox_message; a approval; v_set result;
BEGIN
  PERFORM pg_advisory_xact_lock(7001);
  SELECT * INTO v_me FROM principal WHERE db_role = session_user;
  IF NOT FOUND OR v_me.kind <> 'transport' THEN RAISE EXCEPTION 'forbidden' USING ERRCODE = 'P0001'; END IF;
  SELECT * INTO r FROM outbox_message WHERE id = p_message FOR UPDATE;
  IF NOT FOUND THEN RETURN ROW(false, 'not_found', NULL)::result; END IF;
  IF r.state = 'sent' THEN RETURN ROW(true, 'ok', r.id)::result; END IF;
  IF r.state <> 'sending' THEN RETURN ROW(false, 'not_sending', NULL)::result; END IF;
  IF p_actual_cost IS NULL OR p_actual_cost < 0 THEN RETURN ROW(false, 'unknown_cost', NULL)::result; END IF;
  SELECT * INTO a FROM approval WHERE message_id = r.id;
  IF a.reservation_id IS NULL AND p_actual_cost > 0 THEN
    RETURN ROW(false, 'cost_without_reservation', NULL)::result;
  END IF;
  UPDATE outbox_message SET state = 'sent', sent_at = clock(), provider_ref = p_provider_ref, lease_until = NULL
   WHERE id = r.id;
  IF a.reservation_id IS NOT NULL THEN
    v_set := settle_budget(a.reservation_id, p_actual_cost);
  END IF;
  PERFORM audit('message_sent', jsonb_build_object('message', r.id, 'cost', p_actual_cost));
  RETURN ROW(true, 'ok', r.id)::result;
END $$;

CREATE FUNCTION mark_failed(p_message bigint, p_error text, p_actual_cost int, p_retryable boolean)
RETURNS result LANGUAGE plpgsql SECURITY DEFINER SET search_path = nexus, pg_temp AS
$$
DECLARE v_me principal; r outbox_message; a approval; v_set result;
BEGIN
  PERFORM pg_advisory_xact_lock(7001);
  SELECT * INTO v_me FROM principal WHERE db_role = session_user;
  IF NOT FOUND OR v_me.kind <> 'transport' THEN RAISE EXCEPTION 'forbidden' USING ERRCODE = 'P0001'; END IF;
  SELECT * INTO r FROM outbox_message WHERE id = p_message FOR UPDATE;
  IF NOT FOUND THEN RETURN ROW(false, 'not_found', NULL)::result; END IF;
  IF r.state <> 'sending' THEN RETURN ROW(false, 'not_sending', NULL)::result; END IF;
  IF COALESCE(p_actual_cost, 0) > 0 THEN
    SELECT * INTO a FROM approval WHERE message_id = r.id;
    IF a.reservation_id IS NULL THEN RETURN ROW(false, 'cost_without_reservation', NULL)::result; END IF;
    v_set := settle_budget(a.reservation_id, p_actual_cost);
  END IF;
  IF COALESCE(p_retryable, false) THEN
    UPDATE outbox_message SET state = 'approved', lease_until = NULL WHERE id = r.id;
  ELSE
    UPDATE outbox_message SET state = 'blocked', blocked_reason = 'send_failed', lease_until = NULL WHERE id = r.id;
  END IF;
  PERFORM audit('message_failed', jsonb_build_object('message', r.id, 'retryable', COALESCE(p_retryable, false)));
  RETURN ROW(true, 'ok', r.id)::result;
END $$;

-- Si aucun transport ne prend un message approuve, on le signale une fois.
CREATE FUNCTION raise_stuck_alerts(p_age_minutes int) RETURNS int
LANGUAGE plpgsql SECURITY DEFINER SET search_path = nexus, pg_temp AS
$$
DECLARE v_me principal; r record; n int := 0; c int;
BEGIN
  PERFORM pg_advisory_xact_lock(7001);
  SELECT * INTO v_me FROM principal WHERE db_role = session_user;
  IF NOT FOUND THEN RAISE EXCEPTION 'forbidden' USING ERRCODE = 'P0001'; END IF;
  FOR r IN SELECT o.id FROM outbox_message o JOIN approval a ON a.message_id = o.id
            WHERE o.state = 'approved' AND a.created_at < clock() - make_interval(mins => p_age_minutes) LOOP
    INSERT INTO ops_alert (kind, ref) VALUES ('stuck_approved', r.id::text) ON CONFLICT DO NOTHING;
    GET DIAGNOSTICS c = ROW_COUNT;
    IF c > 0 THEN n := n + 1; PERFORM audit('stuck_alert', jsonb_build_object('message', r.id)); END IF;
  END LOOP;
  RETURN n;
END $$;

-- Lecture du texte exact et de son hash : c'est ce que le fondateur voit avant d'approuver.
CREATE FUNCTION get_message(p_id bigint) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = nexus, pg_temp AS
$$
DECLARE v_me principal; m outbox_message;
BEGIN
  SELECT * INTO v_me FROM principal WHERE db_role = session_user;
  IF NOT FOUND THEN RAISE EXCEPTION 'forbidden' USING ERRCODE = 'P0001'; END IF;
  SELECT * INTO m FROM outbox_message WHERE id = p_id;
  IF NOT FOUND THEN RETURN NULL; END IF;
  RETURN jsonb_build_object('id', m.id, 'version', m.version, 'state', m.state, 'channel', m.channel,
    'recipient', m.recipient_norm, 'subject', m.subject, 'body', m.body, 'max_cost_cents', m.max_cost_cents,
    'purpose', m.purpose, 'content_hash', m.content_hash, 'blocked_reason', m.blocked_reason);
END $$;

-- ---------------------------------------------------------------- notifications au fondateur
CREATE TABLE notification (
  id         bigserial PRIMARY KEY,
  kind       text NOT NULL CHECK (kind IN ('ready_to_sign','hostile_reply','injection_attempt',
                                           'budget_alert','circuit_open','needs_human')),
  ref        text NOT NULL,
  text       text NOT NULL CHECK (length(text) <= 2000),
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT nexus.clock(),
  UNIQUE (kind, ref)
);
CREATE TRIGGER notification_no_mod BEFORE UPDATE OR DELETE ON notification
  FOR EACH ROW EXECUTE FUNCTION no_mutation();

CREATE FUNCTION notify_founder(p_kind text, p_ref text, p_text text)
RETURNS result LANGUAGE plpgsql SECURITY DEFINER SET search_path = nexus, pg_temp AS
$$
DECLARE v_me principal; n notification;
BEGIN
  PERFORM pg_advisory_xact_lock(7001);
  SELECT * INTO v_me FROM principal WHERE db_role = session_user;
  IF NOT FOUND OR v_me.kind NOT IN ('worker','transport','censor') THEN
    RAISE EXCEPTION 'forbidden' USING ERRCODE = 'P0001';
  END IF;
  IF p_kind IS NULL OR p_ref IS NULL OR p_ref = '' OR p_text IS NULL OR btrim(p_text) = ''
     OR length(p_text) > 2000
     OR p_kind NOT IN ('ready_to_sign','hostile_reply','injection_attempt','budget_alert','circuit_open','needs_human') THEN
    RETURN ROW(false, 'bad_input', NULL)::result;
  END IF;
  SELECT * INTO n FROM notification WHERE kind = p_kind AND ref = p_ref;
  IF FOUND THEN RETURN ROW(true, 'ok', n.id)::result; END IF;
  INSERT INTO notification (kind, ref, text, created_by) VALUES (p_kind, p_ref, p_text, session_user)
  RETURNING * INTO n;
  PERFORM audit('founder_notified', jsonb_build_object('id', n.id, 'kind', p_kind, 'ref', p_ref));
  RETURN ROW(true, 'ok', n.id)::result;
END $$;

CREATE FUNCTION get_notifications() RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = nexus, pg_temp AS
$$
DECLARE v_me principal;
BEGIN
  SELECT * INTO v_me FROM principal WHERE db_role = session_user;
  IF NOT FOUND OR v_me.kind <> 'founder' THEN RAISE EXCEPTION 'forbidden' USING ERRCODE = 'P0001'; END IF;
  RETURN COALESCE((SELECT jsonb_agg(jsonb_build_object('id', id, 'kind', kind, 'ref', ref, 'text', text,
                                                       'by', created_by) ORDER BY id) FROM notification), '[]'::jsonb);
END $$;

-- ---------------------------------------------------------------- droits
REVOKE ALL ON ALL TABLES IN SCHEMA nexus FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA nexus FROM PUBLIC;
REVOKE ALL ON SCHEMA nexus FROM PUBLIC;
GRANT USAGE ON SCHEMA nexus TO nexus_worker, nexus_censor, nexus_founder, nexus_transport;
GRANT USAGE ON TYPE nexus.result TO nexus_worker, nexus_censor, nexus_founder, nexus_transport;

GRANT EXECUTE ON FUNCTION reserve_budget(text, text, int, text)   TO nexus_worker, nexus_transport, nexus_founder;
GRANT EXECUTE ON FUNCTION settle_budget(bigint, int)              TO nexus_worker, nexus_transport;
GRANT EXECUTE ON FUNCTION release_budget(bigint)                  TO nexus_worker, nexus_transport, nexus_founder;
GRANT EXECUTE ON FUNCTION budget_status()                         TO nexus_worker, nexus_censor, nexus_founder, nexus_transport;
GRANT EXECUTE ON FUNCTION verify_audit_chain()                    TO nexus_worker, nexus_censor, nexus_founder, nexus_transport;
GRANT EXECUTE ON FUNCTION create_message(text, text, text, text, text, int, text) TO nexus_worker;
GRANT EXECUTE ON FUNCTION create_revision(bigint, text, text, text, int, text)    TO nexus_worker;
GRANT EXECUTE ON FUNCTION submit_review(bigint, text, jsonb, text) TO nexus_censor;
GRANT EXECUTE ON FUNCTION approve(bigint, text, int)               TO nexus_founder;
GRANT EXECUTE ON FUNCTION founder_reject(bigint, text)             TO nexus_founder;
GRANT EXECUTE ON FUNCTION add_suppression(text, text)              TO nexus_worker, nexus_censor, nexus_founder, nexus_transport;
GRANT EXECUTE ON FUNCTION claim_outbox(int)                        TO nexus_transport;
GRANT EXECUTE ON FUNCTION precheck_before_send(bigint)             TO nexus_transport;
GRANT EXECUTE ON FUNCTION mark_sent(bigint, text, int)             TO nexus_transport;
GRANT EXECUTE ON FUNCTION mark_failed(bigint, text, int, boolean)  TO nexus_transport;
GRANT EXECUTE ON FUNCTION raise_stuck_alerts(int)                  TO nexus_worker, nexus_founder, nexus_transport;
GRANT EXECUTE ON FUNCTION get_message(bigint) TO nexus_worker, nexus_censor, nexus_founder, nexus_transport;
GRANT EXECUTE ON FUNCTION notify_founder(text, text, text) TO nexus_worker, nexus_transport, nexus_censor;
GRANT EXECUTE ON FUNCTION get_notifications() TO nexus_founder;
