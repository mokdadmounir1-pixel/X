-- Données de référence (services et agents). Rejouable sans doublon.
INSERT INTO services(id,name,kind,url) VALUES
 ('api','API NEXUS','app','http://127.0.0.1:8000/api/health'),
 ('postgres','PostgreSQL (applicatif)','db',NULL),
 ('ollama','Ollama (inférence locale)','llm','http://127.0.0.1:11434/api/tags'),
 ('n8n','n8n (workflows)','workflow','http://127.0.0.1:5678/healthz'),
 ('baserow','Baserow (interface métier)','ui','http://127.0.0.1:8080/api/_health/'),
 ('mt5','Connecteur MT5 (non activé)','connector',NULL)
ON CONFLICT (id) DO NOTHING;
UPDATE services SET status='disabled', detail='Processus distinct sur le PC Windows, non activé en v0.1' WHERE id='mt5' AND status='unknown';
INSERT INTO agents(id,name,role,service_id,description) VALUES
 ('operateur','Opérateur de démonstration','executant','api','Exécute les tâches internes'),
 ('analyste-quant','Analyste quant','recherche','api','Backtests de démonstration en SIMULATION'),
 ('redacteur-agence','Rédacteur agence','agence','api','Brouillons de propositions, aucun envoi'),
 ('relecteur','Relecteur','controle','api','Contrôle des brouillons'),
 ('conseil','Conseil','analyse','ollama','Proposition, contre-analyse, synthèse')
ON CONFLICT (id) DO NOTHING;
