# Connecteurs ultérieurs (préparés, désactivés)
Interfaces dans `api/app/connectors/` : `crawl4ai`, `browser-use`, `ccxt`, `mt5`. Chaque méthode lève `ConnectorDisabled` ; l'attribut `enabled` est figé à `False`. Un test le vérifie. Ils apparaissent comme services (MT5 : « disabled »).

**MT5** — processus **distinct** sur le PC Windows qui héberge le terminal. Le paquet Python `MetaTrader5` fonctionne uniquement sous Windows : ne pas supposer qu'il tourne dans un conteneur Linux. Disponibilité **non vérifiée** (aucun terminal MT5 ici). Conception retenue pour plus tard : le processus lit les exports et l'état du terminal, publie un statut vers l'API, et ne reçoit aucun ordre tant qu'une décision explicite n'a pas créé un type de tâche de niveau 2 testé.
Activer un connecteur exige : une décision écrite, un type de tâche dans `kinds.py` (niveau 2 si engageant), des tests de refus, une revue.
