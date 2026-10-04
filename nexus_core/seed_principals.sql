-- A executer par nexus_owner apres schema.sql.
INSERT INTO nexus.principal (db_role, kind) VALUES
  ('nexus_worker',    'worker'),
  ('nexus_censor',    'censor'),
  ('nexus_founder',   'founder'),
  ('nexus_transport', 'transport');
