# Prompt ChatGPT — finalisation sur le PC (à coller dans la conversation du protocole de liaison)

Tu es l'exécutant local de quantbot (voir `docs/prompts/chatgpt_liaison_protocol.md` : ses règles priment, notamment JAMAIS d'`order_send`, aucun secret, aucune modification de `quantbot/`, des specs ou du risque).
Récupère la dernière version de la branche par défaut (`git pull`), lance `python -m pytest -q` et rapporte le résultat. Puis, SANS poser de questions, dans l'ordre :

1. **Démarrage** : MT5 ouvert et connecté au compte démo ; double-clic sur `quantbot\lancer_terminal.bat` (fenêtre noire ouverte en permanence). Ouvre http://127.0.0.1:3214/ (ou le port affiché).
2. **Collecte** (≥ 1 journée de marché) : onglet Système, panneau « Synchronisation automatique ». Relève toutes les 6 h : état Coinbase/MT5, barres ajoutées, `data\live\*_M1.csv`/`*_M5.csv` (symboles, nombre de lignes), présence et taille de `data\live\depth\XAUUSD_*.jsonl`. Si « carnet indisponible » : écris-le, ne contourne pas.
3. **C3** (séance ouverte Londres/New York) : `python scripts/c3_quote_gate.py <sortie.json>` puis les mesures de la tâche C3 du protocole. Ajoute : spread réel de l'or toutes les 5 s pendant 30 min par session (médiane, quantiles 10/50/90, part des instants ≤ 0,03 $), et latence aller-retour de `order_check` (PAS d'`order_send`) sur 200 appels : médiane, p95, p99 en ms.
4. **Coûts du compte** : commission par lot, swap long/short de l'or, taille de contrat, point, pas de volume (`symbol_info`), en lecture seule.
5. **Export** : `scripts/export_mt5_deep.py` pour XAUUSD en M1 et M5 (le plus d'historique que le courtier fournit), avec empreintes SHA-256.
6. **Si une erreur apparaît** (fenêtre noire ou navigateur) : copie le texte EXACT.

Livre `livraison-finalisation-<AAAAMMJJ-HHMM>/` : `RESULTAT.md` (preuves datées UTC, écarts, « non concluant » + ce qui manque, risques, ce que tu n'as PAS fait), les sorties brutes, `data\live\` en zip (hors secrets), `manifest-sha256.json`. Ne dis jamais « validé » ni « prêt à trader ». Réponds d'abord en 5 lignes avec ce que tu feras et ne feras pas, puis exécute.
