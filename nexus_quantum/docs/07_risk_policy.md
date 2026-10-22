# 07 — Risk Policy (contrôles non contournables)

Implémentée dans `nexus/risk.py` ; chaque règle ci-dessous est testée (`tests/test_risk.py`).

1. **Chemin unique** : tout ordre passe par `RiskGuardian.check`. Aucun ordre direct.
2. **Limites dures** (`HardLimits`, immuables) : notionnel ordre/position/brut, risque par trade (stop obligatoire, du bon côté), perte jour, drawdown, ordres ouverts, cadence, âge des données. `tighten()` refuse tout assouplissement ; aucun module IA n'y a accès en écriture.
3. **Fail-safe** : au démarrage `reconciled=False` ⇒ entrées bloquées ; écart de position ⇒ `REDUCE_ONLY` ; perte jour/drawdown ⇒ `HALTED` verrouillé.
4. **Réductions** toujours possibles (sauf `HALTED` : seuls ordres de liquidation émis par la procédure) ; une inversion n'est pas une réduction.
5. **Annulation/liquidation** = `ActionRequest` ; statut `CONFIRMED` uniquement sur preuve broker (ordres ouverts = 0 / positions nulles). Une liquidation au marché ne garantit ni prix ni exécution ⇒ gap/slippage résiduels assumés.
6. **Redémarrage** : `authorize_restart(operateur)` exige opérateur nommé, état réconcilié, limite non violée.
7. **Audit** : chaque halt/restart/tighten/confirm est journalisé (`audit`) ; à persister dans le registre immuable.
8. **Montants de départ** : le capital maximal exposé et les valeurs numériques des limites sont **à fixer par le responsable humain** ; les valeurs des tests sont illustratives.
9. **Hors périmètre actuel** : corrélations dynamiques, VaR/CVaR agrégées, marge broker, exposition par secteur/facteur, contrôle d'horloge, gaps — à ajouter (backlog R-*).
