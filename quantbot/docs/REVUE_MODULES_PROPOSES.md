# Revue des modules proposés (prompts « 7 piliers », Kalman, HMM, CVaR, Hawkes, A-S, EVT, RMT, BOCPD…) — 2026-10-26

Principe : un module n'entre dans le dépôt que s'il est (1) mathématiquement correct, (2) utile à un système qui prend des positions (et non qui cote des prix), (3) testé sur un cas dont la réponse est connue. Aucun n'ajoute d'espérance par lui-même ; les stratégies restent jugées par le registre d'essais.

| Module proposé | Verdict | Pourquoi / où c'est dans le dépôt |
|---|---|---|
| Proxy OFI (règle des ticks) | Déjà fait, version corrigée | `order_flow_ofi.tick_flow_imbalance` / `aggression_ratio`. Le code proposé comparait `price` à `ask`/`bid` : sur les CFD MT5 le dernier prix (`last`) vaut 0, tout serait « neutre ». On classe par révision de cotation. Il renvoyait aussi 0,95/0,3 codés en dur (binaire, contraire à la règle « zéro binaire »). |
| Iceberg / absorption | Proxy continu seulement | `absorption_score` (rampes continues). Un iceberg est invisible sans L2/L3. |
| Proxy GEX (chiffres ronds) | Fait, évalué, **FAIL** | `level_proximity.py`, `apex_levels_v1` : +0,016 R. Ce n'est pas un GEX et ne le remplace pas. Le vrai GEX : `dealer_gex.py` sur chaîne d'options réelle. |
| Slicing « Almgren-Chriss » | Non fait | La version proposée n'est pas Almgren-Chriss (simple découpage + bruit). À 0,01-1 lot sur l'or, le découpage n'a aucun effet de marché mesurable et ajoute de la latence et du risque d'exécution partielle. |
| Filtre de Kalman 1D sur le prix | Non fait | Un Kalman à bruit constant converge vers un gain fixe = une moyenne exponentielle : même retard qu'une EMA. L'affirmation « sans lag » est fausse. (Le Kalman à bêta dynamique pour paires, lui, est dans `stat/pairs.py`.) |
| Mutateur IA qui réécrit `apex_config.json` | Refusé | Il durcit/relâche les seuils d'après le taux de pertes récent (procyclique, sur-ajustement du bruit), écrit en place sans validation ni essai compté. Notre boucle PROPOSE, ne promeut jamais (`improvement/apex_loop.py`). |
| HMM de régime (`hmmlearn`) | Non fait en l'état | Le code proposé ajuste le modèle sur toute l'histoire puis prédit (fuite du futur) et suppose que l'état 1 = « tendance saine » (les états d'un HMM n'ont pas de sens fixe). Multiplicateur 1,2 > 1 : augmente le risque. Faisable proprement en walk-forward, mais coûte un essai et reste un filtre. |
| Disjoncteur CVaR | Déjà couvert + EVT ajouté | `risk/var.py` (VaR/ES historiques et paramétriques) et coupure sur perte journalière / drawdown (`risk/active.py`). Ajouté : `evt_var_es` (POT/GPD, formules de McNeil-Frey) testé sur une GPD connue. |
| EVT (POT) | Fait, corrigé | Le code proposé estimait ξ par `mean(log(excès/seuil))` (faux). Remplacé par un ajustement GPD par moments pondérés ; test : retrouve ξ=0,25 à ±0,05. |
| Ornstein-Uhlenbeck / demi-vie | Fait | `stat/pairs.ou_half_life` (numpy seul, `statsmodels` non requis), avec t-stat : sans significativité la « réversion » est déclarée fausse. Test sur un processus simulé de demi-vie connue. |
| Différenciation fractionnaire | Déjà fait, version correcte | `ml/features.frac_diff_ffd` (poids tronqués). Le code proposé utilisait une fenêtre de la taille de la série entière : une seule valeur de sortie. |
| Ledoit-Wolf, RMT (Marchenko-Pastur) | Non fait | Utiles pour des dizaines d'actifs. Avec 3 à 5 séries, il n'y a rien à nettoyer. `scikit-learn` n'est pas une dépendance. |
| Hawkes | Non fait | Récursion proposée sans ajustement des paramètres (α, β fixés à la main) ni définition de « l'événement ». À faire sur de vrais ticks, une fois collectés (`data/live/ticks/`). |
| « BOCPD » | Mal nommé, non fait | Le code est un seuil fixe de 2,5 % sur un rendement : binaire, pas bayésien (aucune vraisemblance prédictive). Un vrai BOCPD (Adams & MacKay) est faisable plus tard. |
| Signatures de chemins | Non fait | Le niveau 1 est un simple incrément (aucune information nouvelle). |
| Avellaneda-Stoikov | Non applicable | Modèle de TENEUR de marché (cotation bid/ask avec inventaire). Nous sommes preneur de liquidité. |
| Prime SGE/LBMA (pilier 6) | Non faisable | Exige les cours de Shanghai et de Londres ; un pic de volume à 01:00 UTC n'est pas une prime. |
| Seuil Ω ≥ 0,82, TIPS/DXY en direct | Non démontré | Le seuil est arbitraire ; on mesure (`composite` + essais) au lieu de l'imposer. TIPS : non disponible sur MT5. |
