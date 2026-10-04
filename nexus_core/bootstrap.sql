-- A executer par un superutilisateur, une seule fois par cluster.
-- Les mots de passe / certificats se configurent hors de ce fichier (pg_hba, secrets).
DO $$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['nexus_owner','nexus_worker','nexus_censor','nexus_founder','nexus_transport'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE', r);
    END IF;
  END LOOP;
END $$;
