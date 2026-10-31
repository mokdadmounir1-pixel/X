# OMEGA — cahier des charges (pour Claude)

Projet : quantbot (dépôt mokdadmounir1-pixel/X, dossier quantbot). Date : 2026-10-28. Statut : **implémenté (v2), PAPER uniquement, NON validé.**

## 1. Objectif
Algorithme de **confluence** de trois stratégies membres FIGÉES : FVG mitigation H1 (`fvg_h1`), AMD / Power of 3 (`amd`), VWAP bandes ±2,5 σ (`vwap`). Un signal est d'autant plus gros que plusieurs membres s'accordent ; il est écarté si les membres se contredisent. Instruments : EURUSD, XAUUSD, USTEC (M15).

## 2. Origine et réserve honnête (à reprendre dans tout rapport)
- Les trois membres ont été choisis après ~2 jours de PAPER (~9 trades clos : 6, 1, 2) : **biais de sélection, aucune valeur statistique**.
- Ces trois stratégies ont ÉCHOUÉ aux portes de recherche sur 2,5 ans (`inst_strategies_v1`, reports/inst_strategies_v1).
- Interdit de présenter OMEGA comme validé, rentable ou « gagnant ». Aucune promesse de rendement (ni 7 %/mois, ni 65 % de réussite).

## 3. Règles de conception (déjà implémentées : `quantbot/strategies/build.py::omega_events`)
1. Membres définis uniquement dans `specs/omega_v2.json` (paramètres identiques à `inst_strategies_v1`). Aucun paramètre appris, aucune pondération optimisée.
2. Causalité : à l'instant t, seules les informations ≤ t. Test de préfixe obligatoire (résultat identique sur données tronquées).
3. Accord = nombre de membres DISTINCTS de même sens dans les `window` = 8 dernières barres (t compris) ; opposition = membres distincts de sens contraire ; net = accord − opposition ; net < 1 → écarté.
4. Confiance = 0,55 + 0,20 × (net − 1) : 0,55 / 0,75 / 0,95 pour 1 / 2 / 3 membres. Elle pilote la taille via le dimensionnement par score existant (`risk.score_sizing_floor`) ; **elle ne peut jamais augmenter le risque par trade au-delà du plafond du moteur**.
5. Anti-doublon : même sens à < `cooldown` = 4 barres du dernier signal retenu → ignoré.
6. Stop et cible = ceux du membre déclencheur. `max_hold_bars` = 48 (le plus long des trois membres).
7. Mode `union` (fusion sans confluence) conservé comme comparateur.

## 4. Exécution et risque
- Un seul moteur (`TradingEngine.on_bar`) : signal à la clôture de barre, exécution à l'ouverture suivante, priorité au stop. Même code en backtest, PAPER et démo.
- PAPER uniquement. **Aucun ordre réel, aucun ordre démo sans l'autorisation écrite de l'utilisateur** (phrase d'autorisation + approbation signée, docs/EXPLOITATION.md).
- Compte FTMO simulé UNIQUE de 100 000 $ (registre `risk/ledger.py`) : perte journalière 5 %, totale 10 %, tampons 4 % / 8 % (règles à vérifier sur ftmo.com). Fichier KILL jamais levé automatiquement. Le « risque ouvert cumulé » est affiché dans les onglets Live trades et Risque.
- Coûts : spread médian mesuré EN SÉANCE, commission du courtier jamais supposée à 0 (valeur « NON CONNUE » tant qu'elle n'est pas relevée).
- Non fait, à décider par l'utilisateur : plafond global de risque ouvert (ex. 2 %).

## 5. Validation (préenregistrée, aucun essai consommé)
- Budget d'essais : plafond relevé à 500 par décision écrite de l'utilisateur le 2026-10-31 (config/trial_budget.json) ; 118 consommés à cette date. Aucun backtest d'OMEGA sans accord explicite de l'utilisateur.
- Jugement sur l'échantillon PAPER avant-coup : **≥ 4 semaines ET ≥ 60 trades**, paramètres inchangés, espérance > 0,15 R.
- OMEGA doit battre (a) la moyenne des trois membres pris séparément et (b) sa propre version `union` rejouée sur les mêmes barres. Sinon, la confluence n'apporte rien et OMEGA est abandonné.
- Comparateur obligatoire : achat-conservation de l'actif (bêta).
- Les résultats négatifs sont publiés tels quels. Jamais de modification des paramètres après avoir vu les résultats : toute variante = nouvelle spec préenregistrée, commitée AVANT l'exécution.

## 6. Livrables et fichiers
`specs/omega_v2.json` (spec), `specs/omega_v1.json` (union, jamais lancée), `quantbot/strategies/build.py` (`omega_events`, code `OMEGA_TRIO`), `tests/test_twelve.py` (niveaux de confiance, causalité, logique d'accord/contradiction), catalogue (`ui/catalog.py`), `supervisor.py` / `start_all.bat` (lanceur PAPER indépendant des trois membres).

## 7. Critères d'acceptation
- `python -m pytest -q` passe en entier.
- Les trois stratégies d'origine continuent de tourner séparément (spec `inst_strategies_v1`) ; les trades d'OMEGA sont comptés à part.
- L'interface affiche OMEGA_TRIO avec son statut « non validé ».
- Aucun message, README ou commentaire ne laisse entendre un avantage prouvé.

## 8. Interdits
Optimiser les poids ou seuils sur les trades observés ; lire la tranche verrouillée de 12 mois ; augmenter la taille parce que les membres ont gagné ; envoyer un ordre ; supprimer ou modifier les stratégies membres ; supposer une commission nulle.
