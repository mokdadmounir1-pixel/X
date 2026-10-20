# Rapport prop_sim : simulation prospective interne et scénarios FTMO

**Périmètre.** Le code NEXUS (Windows, MT5, Léo, Jesse…) n'était pas dans cette session. Ce rapport couvre uniquement le paquet portable `prop_sim/`, testé sur **données synthétiques**. Aucun résultat ici n'est une preuve d'avantage de marché, et aucun ordre courtier n'est possible dans ce code.

## Problèmes identifiés
- Le dépôt n'a pas de simulation prospective : le bot FX existant ne fait que du backtest groupé, sans positions persistantes, sans reprise ni traçabilité des rejets.
- Il n'y a pas de moteur de risque indépendant de la stratégie (risque cumulé, corrélation de devises, flottant).
- Il n'y a pas d'évaluation FTMO sur equity flottante avec le jour Europe/Prague.

## Changements
- `prop_sim/risk_engine.py` : limites figées (plafond 0,60 % non dépassable), risque cumulé, exposition nette par devise, tampons internes de perte (3 % jour, 6 % total, flottant inclus).
- `prop_sim/book.py` : livre SQLite. Dédup des signaux et des barres, reprise idempotente, journal de chaque signal, rejet, remplissage et clôture. Stop avant objectif en cas de collision dans une barre, exécution au prix d'ouverture en cas de gap. Une modification des paramètres d'une stratégie annule son approbation. Les limites sont verrouillées par empreinte.
- `prop_sim/ftmo.py` et `prop_sim/ftmo_mc.py` : évaluateur de trajectoires et Monte-Carlo de sensibilité.
- `tests/test_prop_sim.py` : 16 tests, tous passent.

## Résultats
**Relecture synthétique** (7 paires, M15, 20 000 barres, du 2024-01-01 au 2024-07-27, preset *selective*) :
- 4 trades, +1,09 %, drawdown d'equity 0,25 %, coûts 33 $, statut FTMO « incomplete ».
- Contrôle de reprise : arrêt au milieu puis rejeu complet donne un résultat identique (4 trades, même solde).
- **Cet échantillon est trop petit pour conclure quoi que ce soit.**

**Sensibilité FTMO, conditionnelle à une espérance supposée** (2 trades/jour en moyenne, 60 jours maximum, 2 000 simulations par cas, coût 0,05 R par trade). Les intervalles de confiance ne mesurent que l'erreur Monte-Carlo, pas l'incertitude sur l'espérance réelle.

| Hypothèse (espérance nette) | Risque/trade | Réussite | Échec perte max | Échec perte jour | Non terminé |
|---|---|---|---|---|---|
| 40 % × 1,5R (−0,05R) | 0,60 % | 6 % | 20 % | 0 % | 74 % |
| 45 % × 1,5R (+0,075R) | 0,60 % | 28 % | 5 % | 0 % | 67 % |
| 50 % × 1,5R (+0,20R) | 0,25 % | 5 % | 0 % | 0 % | 95 % |
| 50 % × 1,5R (+0,20R) | 0,60 % | 65 % | 1 % | 0 % | 34 % |
| 50 % × 1,5R (+0,20R) | 1,00 % | 82 % | 4 % | 4 % | 10 % |
| 40 % × 2R (+0,15R) | 0,60 % | 52 % | 4 % | 0 % | 45 % |

Le tableau complet est dans `outputs/prospective_demo.json`.

**Lecture :**
- Avec un avantage nul ou négatif, un risque plus élevé donne quand même des « réussites » (6 % à 0,60 % avec −0,05R, 21 % à 1 %). Ce n'est pas un avantage : c'est de la variance, et la même hausse de risque multiplie les ruines.
- L'objectif de 3 % par jour demande environ 5R nets en une journée au plafond de 0,60 %, et celui de 10 % environ 17R. Les simulations donnent une probabilité non nulle seulement parce que le risque est grand et que le maximum est pris sur 60 jours. Ces objectifs restent des aspirations, pas des cibles de dimensionnement.
- La métrique « p_day_ge_3pct » du JSON est le maximum sur toute la trajectoire, donc elle dépend de sa longueur. Il ne faut pas la lire comme une probabilité par jour.

## Limites
- Prix synthétiques et spreads « typiques » de la configuration, pas du bid/ask mesuré. Aucune donnée FTMO, MT5 ou UTC vérifiée.
- Les **règles FTMO 2-Step sont mes valeurs par défaut, non revérifiées** : `FtmoRules.verified_on` est vide. À confronter aux règles officielles avant toute interprétation. La référence de perte journalière est un choix prudent, configurable.
- Le Monte-Carlo suppose des trades indépendants, sans flottant intra-trade ni régimes, et ne mesure pas l'avantage réel.
- Les swaps ne sont pas modélisés.
- **Performance :** la démo a mis 15 min parce que le livre valide la base à chaque barre. À optimiser (validation par lots) avant un flux long.
- Le chemin MQL5 natif, les moteurs tiers (Jesse, Freqtrade…), la matrice des 36 composants et le correctif `spawn_hidden` n'ont pas été traités : ils exigent le code et la machine Windows.

## Prochaine expérience
Fournir des historiques MT5 réels avec bid/ask, puis geler les paramètres d'une famille interprétable sur une période de recherche. Faire une évaluation finale unique sur une période disjointe, passer le résultat dans `VirtualBook`, et mesurer l'espérance en R avec son intervalle avant de lancer le Monte-Carlo FTMO. **Conclusion actuelle : aucun candidat qualifié.**
