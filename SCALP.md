# SCALP.md — scalp et micro-scalp (barres M1) avec les outils du dépôt

Statuts : `[VÉRIFIÉ]` = calculé sur données réelles · `[SYNTHÉTIQUE]` = données générées ici · `[HYPOTHÈSE]`.
**Aucune donnée réelle n'a été utilisée** (le cloud n'en a pas) : tout chiffre ci-dessous est `[SYNTHÉTIQUE]` et ne dit rien du marché réel.
Ce qui est livré : un pipeline prêt à tourner sur votre machine (Windows, MT5), validé mécaniquement (causalité, test nul, puissance, faux PASS).

## 1. Règles FTMO sur le scalping `[HYPOTHÈSE — sources tierces, ftmo.com inaccessible depuis le cloud]`
Recherche web du 2026-10-21 (aucune source officielle FTMO lue) :
- Le scalping « normal » n'est pas interdit ; plusieurs comparatifs indiquent **pas de durée minimale de détention** chez FTMO.
  Un comparatif évoque « > 50 s de détention, tick scalping interdit » mais sans dire de quelle firme : **à vérifier**.
- Les sources citent surtout : HFT / tick scalping / arbitrage de latence interdits, activité « hyperactive » au-delà de **~2 000 requêtes serveur/jour**
  ou **~200 ordres ouverts simultanés** (chiffres répétés de blog en blog, non confirmés), et la règle de **réplicabilité** (une stratégie d'EA doit être exécutable à la main).
- Challenge 2 étapes : 4 jours de trading minimum. Le « 1-Step » aurait une règle du meilleur jour (≤ 50 % du profit) : non figé ici.
**Choix de conception (prudents, indépendants de la vérité exacte)** : on ne fait ni tick-scalping ni arbitrage de latence ; barres M1 seulement ;
`compliance` publié par algo (trades/jour, durée médiane, part de trades ≤ 1 barre, requêtes estimées/jour). **À faire par vous : lire les règles
FTMO actuelles (page « Trading objectives » + règles EA) ou écrire au support avant d'acheter** — une violation = compte perdu.

## 2. Pourquoi le scalp est « le plus dur » : les coûts
Formule (exacte) : avec c = coût aller-retour / distance de stop (en R) et un RR visé, `E = p·(RR+1) − (1+c)`, donc **taux de réussite d'équilibre p\* = (1+c)/(RR+1)**.
Le coût aller-retour = spread + 2 slippages + commission. Un stop de 1 ATR M1 contient très peu de pips : le spread en pèse une grosse part.
`python -m ftmo_algo scalp-costs --mt5 --instruments ...` imprime, par instrument et par fenêtre horaire, coût/ATR, coût en R et p\*.
Sur les specs par défaut `[HYPOTHÈSE]` et une volatilité synthétique (`reports/scalp/scalp_costs.json`, donc ordre de grandeur seulement) : indices (US500, US100, GER40) et or jouables
de 07:00 à 16:30 UTC avec un stop ≥ 2 ATR (0,13 à 0,26 R de coût) ; EURUSD non jouable (≥ 0,33 R au mieux), GBPUSD/USDJPY à la limite (0,22 à 0,23 R) ; Asie, fin d'après-midi et nuit : jamais (≥ 0,3 R).
**Ces ordres de grandeur dépendent des spreads de VOTRE courtier : seule la mesure sur votre compte tranche.**
Conséquence de conception : filtre de coût **dans chaque algo** (coût A/R ≤ 25 % de la distance de stop, `COST_FRAC` fixé a priori, non optimisé),
fenêtres horaires liquides fixes, RR net minimal 1,3 (au lieu de 2,5 en M15, où le gros RR est la philosophie du dépôt).

## 3. Ce qui est construit (`ftmo_algo/scalp/`)
| fichier | rôle |
|---|---|
| `ctx.py` | contexte M1 causal (ATR, VWAP de séance, coût attendu, fenêtres liquides) |
| `algos.py` | 4 algos : `orb_micro` (cassure de la fourchette d'ouverture), `vwap_fade` (retour au VWAP, cible = VWAP), `burst_momentum` (barre d'expansion), `micro_sweep` (balayage de liquidité 20-40 min) ; 4 sorties courtes (RR 1,5 / 2 / 3 / break-even, time-stop 20-45 min) ; hypothèse et invalidation écrites dans chaque classe |
| `costs.py` | faisabilité des coûts, taux de réussite d'équilibre |
| `pipeline.py` | walk-forward + période verrouillée + portes + test nul + DSR (les mêmes outils que `research`) |
| `calibrate.py` | faux PASS sur marches aléatoires M1 |
Moteur : le **même** moteur pessimiste (`engine/sim.py` : exécution à l'ouverture suivante, bid/ask, stop prioritaire, slippage, commission, annonces ×3 pendant 90 min).
Commandes : `scalp-costs`, `scalp-research`, `scalp-calibrate` (voir §6).

### Portes scalp (propres au scalp, choisies AVANT de voir un résultat, `[HYPOTHÈSE]`)
Les 9 portes + DSR du dépôt, avec : ≥ 300 trades OOS, espérance nette ≥ +0,08 R, PF > 1,12, risque 0,15 %/trade (au lieu de 0,5 %), test nul **par signe aléatoire de chaque barre**
(voir §4), coûts ×**1,5** (au lieu de ×2), et une 10ᵉ porte : **retard d'exécution d'une barre** (espérance encore > 0). Le retard d'une minute est un stress volontairement dur :
M1 ne permet pas de modéliser la latence sub-minute (une latence réelle de quelques centaines de ms est bien inférieure ; elle compte surtout via le slippage, déjà modélisé).
La période verrouillée reste physiquement séparée et évaluée une seule fois.

## 4. Défaut trouvé dans le test nul (important, aussi pour le pipeline M15)
Le test nul historique inverse le signe de **blocs d'un jour**. Pour un algo intrajournalier, l'élan / le retour à la moyenne **intrajournaliers survivent** au retournement
(le bloc est inversé d'un seul tenant). Mesuré `[SYNTHÉTIQUE]` avec un edge planté : espérance observée +1,20 R, **moyenne du « nul » +1,07 R** → la porte nul rejetait un vrai edge (p = 0,28).
Correction (`make_surrogate(..., block_bars=1)`, signe aléatoire par barre : volatilité, amplitude, saisonnalité et spreads conservés, direction détruite) : nul moyen −0,12 R, p = 0,02, PASS.
Le défaut ne crée pas de faux PASS (il rend le test trop sévère) ; le défaut historique reste en place pour le M15 (comportement inchangé, mesures publiées inchangées) —
**à décider par le fil qui possède ce pipeline** (appliquer `block_bars` aux algos intrajournaliers M15 ferait baisser le taux de faux rejets).

## 5. Résultats `[SYNTHÉTIQUE]` (mécanique du pipeline, pas le marché)
Données : US500, EURUSD, XAUUSD, 3,5 ans M1 synthétiques, graine 7, verrou dès 2023-07-04 (12 mois), 7 plis walk-forward.
| scénario | orb_micro | burst_momentum | vwap_fade | micro_sweep | verrou (orb_micro) |
|---|---|---|---|---|---|
| **référence : marche aléatoire** (`reference_s7.json`) | FAIL, E = −0,05 R (n 856) | FAIL, −0,28 R | FAIL, −0,30 R | FAIL, −0,10 R | −0,06 R (n 724) |
| **edge faible planté** (persistance 0,05, `power_p005…json`) | FAIL, E = 0,00 R | FAIL | FAIL | FAIL | −0,01 R |
| **edge fort planté** (persistance 0,3, irréaliste, `power_p03…json`) | **PASS**, E = +1,20 R, PF 6,5, nul moyen −0,12 R | WATCH (n < 300), +0,91 R | FAIL | FAIL | **+1,12 R** (n 333) |

- **Faux PASS : 0/60 marches aléatoires M1 (16 + 44 séries, `calibration_run1/2.json`) = 0,0 %, borne haute à 95 % ≈ 4,9 %** : ne pas en déduire que le taux réel est nul. Espérance OOS moyenne −0,13 R, brute −0,12 R (biais négatif = exécution pessimiste + coûts).
- **Puissance** : le pipeline voit un edge énorme (+1,2 R), pas un edge faible (E ≈ 0 → FAIL, ce qui est correct ici car l'edge planté de 0,05 ne survit pas aux coûts). Un vrai edge réel modeste (< 0,08 R net) sera FAIL/WATCH : choix assumé (spécificité > sensibilité).
- Conformité (orb_micro, référence) : 1,4 trade/jour, durée médiane 21 min, 0 % de trades ≤ 1 barre, ≈ 5 requêtes serveur/jour — très loin des seuils « HFT » évoqués ; les trois autres algos font 0,1 à 0,4 trade/jour.
- **Lecture honnête du scalp** : avec ≤ 1,5 trade/jour par algo et 0,15 % de risque par trade, atteindre +5 %/mois exigerait une espérance nette ≫ 0,3 R sur plusieurs instruments ; rien de tel n'est démontré. Le scalp n'est pas un raccourci vers la cible : c'est le style où les coûts tuent le plus d'edges.

## 6. Lancer sur votre machine (Windows, dépôt dans `Documents\X`)
```bat
cd %USERPROFILE%\Documents\X
git fetch origin && git checkout <branche de la PR>
pip install -r requirements.txt MetaTrader5
:: 1) MESURER les coûts réels de votre courtier (terminal MT5 ouvert, compte démo FTMO) — avant toute recherche
python -m ftmo_algo scalp-costs --mt5 --instruments US500,US100,GER40,XAUUSD,EURUSD,GBPUSD,USDJPY --start 2025-01-01
:: 2) recherche (ne garder que les instruments/fenêtres où cout_R <= 0,25)
python -m ftmo_algo scalp-research --mt5 --instruments US500,XAUUSD --start 2023-01-01 --workers 4 --null 99 --tag scalp_v1 --out results_scalp
```
Données : l'historique M1 des courtiers MT5 est **court** (souvent 1 à 2 ans) : en dessous de 3 ans de données le verdict est plafonné à WATCH. Pour 5 ans et plus, exporter des
barres M1 (idéalement avec bid/ask) depuis Dukascopy ou autre en CSV, puis `--data-dir dossier` (fichiers `US500_M1.csv`, …). Un calendrier d'annonces réel (`--news-csv time,name`)
compte davantage en scalp (blocage 30 min avant / 15 min après).
Règle d'or inchangée : **ne jamais relancer `scalp-research` pour améliorer le verdict de la période verrouillée** (le code refuse une 2ᵉ évaluation).

## 7. Non vérifié / limites
1. Tout edge sur le marché réel : inconnu. 2. Spreads/commissions/slippage = specs `[HYPOTHÈSE]` en synthétique ; avec MT5, la colonne `spread` des barres est utilisée (spread moyen de la minute, pas le pire).
3. Résolution M1 : stop et cible dans la même minute → le stop gagne (pessimiste) ; sans ticks, l'ordre réel est inconnu (la gestion sub-minute n'est pas testable ici).
4. Latence sub-minute et file d'attente d'exécution : non modélisées (voir stress « retard d'une barre »). 5. Règles FTMO sur le scalping : sources tierces (§1).
6. Seuils des portes scalp : choix a priori, à reconsidérer sur réel seulement avec la calibration. 7. Portefeuille multi-algos scalp, intégration live/démo des algos scalp : non faits
(les agents live sont M15). 8. Biais de pessimisme : l'espérance brute des marches aléatoires est négative (≈ −0,05 à −0,3 R) à cause de l'exécution pessimiste ; un vrai edge réel peut être sous-estimé.
