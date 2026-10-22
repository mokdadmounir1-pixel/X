# 03 — Research Roadmap (hypothèses d'alpha priorisées)

Tout ci-dessous est **[HYPOTHESE]** : un phénomène documenté n'est pas la preuve qu'une implémentation est rentable après coûts. Les sources sont des références académiques à re-vérifier au moment de l'étude.

## Priorisation (valeur scientifique / coût / compatibilité capital)
| Prio | Famille | Pourquoi d'abord | Horizon | Rejet si |
|---|---|---|---|---|
| 1 | Time-series momentum / trend multi-actifs (Moskowitz-Ooi-Pedersen 2012) | beaucoup de recherche, faibles coûts/rotation, données daily accessibles, peu de latence | jours-mois | DSR<0,95 avec N réel; edge disparaît à coûts ×2 |
| 2 | Sessions/ORB, breakout après compression, continuation | intraday, données minute disponibles, compatible prop | minutes-heures | breakeven > edge brut à coûts centraux |
| 3 | Mean reversion/stat-arb sur paires/ETF corrélés | diversifiant vs momentum | heures-jours | non-stationnarité du spread (tests de coïntégration instables) |
| 4 | Méta-labeling sur 1–3 (López de Prado 2018) | améliore le sizing sans nouvelle source d'alpha | — | n'améliore pas hors-échantillon vs baseline |
| 5 | Microstructure (OFI, microprice, queue imbalance : Cont-Kukanov-Stoikov 2014) | seulement si données L2/L3 + simulateur de file calibrés | ms-min | edge < coût réel au pessimiste |
| 6 | Market making sous inventaire (Avellaneda-Stoikov 2008) | spéculatif : course à la latence, adverse selection | ms-s | fills passifs non calibrés; inventaire mal borné |

## Fiche normalisée (modèle, à instancier par famille)
Hypothèse économique · source · marchés · horizon · données requises · mécanisme de l'edge · formulation · coûts/latence admissibles (`breakeven_ticks`) · crowding · conditions de dégradation · capacité · validation (`04`) · critères de rejet.

## Exemple instancié — Time-series momentum (famille 1)
- Hypothèse : persistance des rendements de 1–12 mois (sous-réaction, flux de couverture/allocation) [HYPOTHESE].
- Signal : `sign(r_{t-L,t})`, volatilité cible ex-ante σ*/σ̂_t (σ̂ EWMA disponible à t).
- Marchés : futures liquides (indices, taux, devises, matières) ; ici micro-futures pour petits capitaux.
- Coûts : rotation faible ⇒ breakeven peu contraignant.
- Dégradation : retournements de régime, crowding CTA ; rejet si SR hors-échantillon < 0 sur 2 sous-périodes disjointes.
- Validation : walk-forward, purge = L, DSR avec N de toutes variantes de L/σ*, test inter-instruments.

## Machine d'IA (Partie V) — ordre imposé
1) données + moteur + validation fiables ; 2) baselines simples (règles, régression logistique régularisée) ; 3) gradient boosting/méta-labeling seulement si baseline battue hors-échantillon avec N compté ; 4) détection de régime ; 5) bandits en simulation ; 6) RL uniquement avec environnement crédible. Deep learning : exception justifiée, jamais défaut. Les 10 agents sont des **rôles** (checklists + sorties au registre) ; le Skeptic et le Validator ont droit de veto, aucun agent n'écrit dans `HardLimits` ni ne se promeut.
