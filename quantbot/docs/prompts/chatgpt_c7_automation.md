# C7 — Installation et vérification de l'automatisation 24 h/24 (à coller dans la conversation ChatGPT)

Tu es toujours l'exécutant local défini par `docs/prompts/chatgpt_liaison_protocol.md` : toutes ses règles restent en vigueur
(aucun ordre, aucune approbation, aucune levée du coupe-circuit, aucun secret, rien de faux, « non concluant » si non mesuré).
**Cette tâche C7 est autorisée dès maintenant, sans attendre C3** (elle ne dépend pas d'une séance active). Tu ne fais QUE C7.

## 0. Préparation
1. Récupère le dernier commit de `claude/eager-davinci-8i7zsd` (au moins `6ce4df6`) dans une copie propre ; note le hash.
2. `python -m pytest -q` : rapporte le résultat (attendu : 271 passés).
3. `python scripts\\setup_data.py` puis `python scripts\\check_data.py` : les trois CSV de `data/real` doivent être « OK ». Sinon, STOP et rapporte.
4. Vérifie que le fichier `approved_strategies.json` est ABSENT (le lanceur doit rester en OBSERVATION). S'il existe, ne le modifie pas : rapporte son contenu masqué.

## 1. Extraction MT5 (lecture seule)
Lance, dans une fenêtre dédiée, pendant **au moins 5 minutes** (marché fermé accepté : « aucune nouvelle barre » est un résultat normal) :
`python scripts\\data_daemon.py --symbols XAUUSD EURUSD USTEC --timeframes M15 H1 --interval 30`
Puis arrête-le avec Ctrl+C. Rapporte, avec les fichiers bruts :
- `data/live/DAEMON_STATUS.json` (connexion, séries, `chain_ok`, `orders_sent` doit valoir 0) ;
- les premières lignes et le nombre de barres de chaque `data/live/<SYMBOLE>_<TF>.csv` créé ;
- `data/live/MANIFEST.jsonl` (chaîne intègre ?) et `ANOMALIES.jsonl` s'il existe (ne rien « corriger » : décrire) ;
- relance le démon 1 minute, arrête-le, relance-le : le deuxième passage ne doit PAS dupliquer de barres (compte avant/après).
Vérifie aussi, sans l'écrire en dur : le démon affiche « terminal déconnecté » (et ne plante pas) si MT5 est fermé — teste-le seulement si l'utilisateur ferme MT5 lui-même.

## 2. File de recherche
`python scripts\\research_queue.py --once` : la file est vide (`specs/queue.json`), le résultat attendu est `ran: null`. Rapporte `reports/QUEUE_STATUS.json`.
N'ajoute AUCUN item et ne modifie AUCUNE spec : c'est le travail de Claude et de l'utilisateur.

## 3. Interface
Lance `python -m quantbot ui`, ouvre l'onglet « Données » et fournis une capture : la carte « Automatisation 24 h/24 » doit refléter ce que tu viens de mesurer
(extraction active/arrêtée, chaîne, essais, specs en attente). Toute divergence entre la carte et les fichiers = à rapporter.

## 4. Démarrage automatique : PROPOSITION seulement
Rédige (sans l'exécuter) la commande de tâche planifiée Windows qui lancerait `scripts\\start_all.bat` à l'ouverture de session, et liste ce que
ce script démarre (extraction, file de recherche, lanceur en OBSERVATION, interface). **Ne crée la tâche que si l'utilisateur écrit :
« j'autorise la tâche planifiée »** dans cette conversation. Prévois aussi la commande pour la supprimer.

## 5. Livraison (même format que d'habitude)
Dossier `livraison-C7-<date>/` : `RESULTAT.md` (preuves, écarts, non-concluant, risques, ce qui n'a pas été fait), `manifest-sha256.json`, sorties brutes.
Signale en particulier : tout appel d'API d'ordre rencontré (il ne doit y en avoir aucun dans le démon), toute barre modifiée par le terminal,
tout trou non comblé, la durée réellement observée, et le fait que le marché était ouvert ou fermé pendant la mesure.
Ne dis pas « prêt » ni « validé ». Attends le retour de Claude et un « suivant » avant la tâche suivante.
