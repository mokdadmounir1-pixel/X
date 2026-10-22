# 06 — HFT Feasibility Study (milliers de trades/jour)

**Verdict préliminaire [HYPOTHESE, à confirmer par données réelles]** : pour un capital de détail et un broker de détail, des milliers de trades quotidiens par *traversée du spread* sont économiquement irréalistes ; la voie possible, si elle existe, est la fourniture passive de liquidité avec calibrage de file — qui est une course à la latence où un acteur de détail est structurellement désavantagé. Le volume n'est jamais un objectif.

## 1. Arithmétique du point mort [HYPOTHESE tarifs / calcul vérifié] (`sprint1_demo_output.txt`)
Instrument de référence : MES, tick 0,25 = 1,25 USD (spécification CME à re-vérifier). Tarifs **supposés**, non issus d'un broker :
| Scénario | Coût A/R | Point mort | ×2 stress |
|---|---|---|---|
| optimiste | 2,35 USD | 1,88 ticks | 4,70 |
| central | 3,58 USD | 2,86 ticks | 7,15 |
| pessimiste | 6,55 USD | 5,24 ticks | 13,10 |

Lecture : avec un spread typique de **1 tick** (à vérifier), toute stratégie qui traverse le spread doit gagner >2,9 ticks bruts par aller-retour *avant* de gagner un centime. Multiplier le nombre de trades multiplie le coût linéairement : 50 000 trades/mois → edge brut requis 2,86 ticks/trade ; les frais fixes se diluent mais le coût variable domine. **Le nombre de trades ne crée pas d'edge.**

## 2. Capital (risque 1 %/trade, 1 MES, coûts centraux) [HYPOTHESE, calcul]
| Capital | Risque 1 % | Stop max à 1 MES | Coût/risque | Verdict provisoire |
|---|---|---|---|---|
| 1 000 | 10 | 2 pts (8 ticks) | 35,8 % | **non viable** : coûts dévorent le risque ; ne pas gonfler le levier |
| 5 000 | 50 | 10 pts | 7,2 % | swing/intraday lent seulement |
| 10 000 | 100 | 20 pts | 3,6 % | intraday multi-horizons plausible à tester |
| 25 000 | 250 | 50 pts | 1,4 % | idem, plusieurs stratégies |
| 100 000 | 1 000 | 200 pts | 0,4 % | capacité de diversification ; HFT toujours non démontré |
Marges requises, frais fixes de données, fiscalité : **à renseigner** après vérification broker (non inventés ici). Pour 1 000 € l'option raisonnable est paper/prop (sous règles du programme) ou ne pas trader.
Ruine [SYNTHETIQUE, edge nul, 1000 trades, ruine=−50 %] : risque 0,5 %→0,000 ; 1 %→0,037 ; 2 %→0,373 ; 5 %→0,856 (hypothèse iid, sous-estime le réel).

## 3. Marchés/infrastructures à comparer (grille de collecte)
Futures CME / micro-futures / FX spot / actions-ETF / autres : taille min, valeur du tick, spread observé, commission, frais d'échange, rebates, profondeur, latence, connectivité, qualité des données, API, limites de messages, capital, marge, contraintes réglementaires. **Aucune de ces valeurs n'est encore collectée** ; Phase 5 = les mesurer, pas les supposer. Un broker de détail avec API par REST/WebSocket impose typiquement des latences >10 ms et des limites de messages : incompatible a priori avec la plupart des stratégies de latence [HYPOTHESE].

## 4. Données & simulateur (Phase 5)
Reconstruction du carnet événement par événement (add/modify/cancel/trade), contrôles de séquence/gap/snapshot, distinction carnet affiché / liquidité cachée / position de file estimée. Simulateur : latences (données, calcul, envoi, réponse), file, fills partiels, annulations, rejets, adverse selection, coûts complets, saturation ; scénarios optimiste/central/pessimiste ; **calibration sur journaux d'exécution réels** (impossible sans trading réel minimal ⇒ le HFT ne peut être validé qu'après Phase 6/7). Un ordre limite n'est jamais supposé exécuté au simple « touch ».

## 5. Faisabilité technique
Python pour recherche ; profilage P50/P95/P99/P99.9 de bout en bout ; Rust/C++ **seulement** si le profil montre que la latence détermine l'edge. Pas de recherche de latence minimale sans edge dépendant de la latence.

## 6. Critères Go/No-Go
GO microstructure seulement si : données L2/L3 traçables, simulateur calibré, rentabilité nette positive au scénario **pessimiste**, capacité mesurée, règles broker/exchange autorisantes. Sinon : **NO-GO**, résultat scientifique valide.
## 7. Statut réalisable / recherche / dépend du capital / spéculatif
Réalisable aujourd'hui : TSMOM/intraday lent, validation, risque. Recherche : stat-arb, méta-labeling. Dépend du capital : taille des contrats, diversification. Spéculatif : HFT/market making de détail.
