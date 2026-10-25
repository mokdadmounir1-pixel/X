# C8 — Historique profond complet + backtests EN ARRIÈRE (à coller dans ChatGPT, après relecture de C6 par Claude)

Tu restes l'exécutant défini par `docs/prompts/chatgpt_liaison_protocol.md` (aucun ordre, aucune approbation, aucun secret, rien de faux, « non concluant » si non mesuré).
Tu ne fais QUE C8. **Récupère d'abord le dernier commit** de `claude/eager-davinci-8i7zsd`, lance `python -m pytest -q` et rapporte le résultat (attendu : 279 passés ou plus).

## Pourquoi
C6 a montré que `export_mt5.py` plafonne à ~100 000 barres par timeframe (M15 depuis 2022, H1 depuis 2009-2010). Le NOUVEL export par tranches de dates
`scripts\export_mt5_deep.py` (lecture seule, déjà dans le dépôt, ne le modifie pas) remonte aussi loin que le serveur a des données. Et les scripts acceptent désormais
`--terminal "C:\Program Files\MetaTrader 5\terminal64.exe"` : plus besoin de ton adaptateur pour `initialize`.

## Étapes
1. Export profond, pour XAUUSD, EURUSD et USTEC, dans `data\deep` (sans écraser `data\real`) :
   `python scripts\export_mt5_deep.py --symbol XAUUSD --timeframes M15 H1 --out data\deep --terminal "C:\Program Files\MetaTrader 5\terminal64.exe"`
   Rapporte pour chaque fichier : barres, première et dernière barre (époques brutes), plus grand intervalle, SHA-256, et les `notes` / `failures` du JSON de provenance profond.
   Vérifie de nouveau que les barres de `data\deep\<S>_M15.csv` communes avec `data\real\<S>_M15.csv` sont IDENTIQUES (attendu : 0 différence). Si l'écart est non nul : STOP.
   Remarque : H4 et D1 ne sont plus nécessaires pour ces tests (ne les ré-exporte pas).
2. Si M15 remonte plus loin qu'avant (plus de 100 000 barres), dis-le clairement ; sinon écris « plafond inchangé » avec la preuve (nombre de requêtes, tranches vides).
3. Backtests en arrière (écrivent des essais dans le registre, comptés ; lance-les UNE fois chacun, dans cet ordre, et conserve les sorties brutes) :
   `python scripts\run_backward.py specs\backward_v1.json > backward_v1.log`
   `python scripts\run_battery_backward.py specs\battery_backward_v1.json > battery_backward_v1.log`
   Ne modifie aucune spec, aucun paramètre. Ne relance pas après avoir vu les résultats. Si un script plante, rapporte l'erreur exacte et ne contourne pas.
4. Livre : `reports\backward_v1\*.json`, `reports\battery_backward_v1\*.json`, les deux `.log`, **`reports\registry.jsonl`** (indispensable : Claude le fusionne avec
   `scripts\registry_merge.py` ; ne le modifie pas à la main) et le nombre d'essais avant/après.

## Livraison
Dossier `livraison-C8-<date>/` : `RESULTAT.md` (preuves, écarts, non concluant, risques, ce qui n'a pas été fait), `manifest-sha256.json`, sorties brutes.
Pas de « prêt » ni « validé » : tu rapportes. Aucune lecture de la période verrouillée n'est demandée ni permise.
