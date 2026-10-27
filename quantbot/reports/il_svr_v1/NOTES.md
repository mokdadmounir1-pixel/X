# il_svr_v1 — IL-SVR (balayage de la première heure + VWAP ±2σ + divergence de flux proxy), USTEC M15
Spec préenregistrée avant exécution. 1 essai (registre : 113 / 120). Tranche verrouillée non lue.
Résultat : FAIL. 89 trades, +0,002 R, PF 1,02 ; achats 34 trades +0,056 R / ventes 55 trades -0,031 R. Échecs : espérance, PF, test nul, coûts x2, Monte-Carlo, concentration, enveloppe de risque, DSR.
Limites : M15 (la stratégie est pensée pour M1) ; CVD en proxy par barre ; cible unique au VWAP (pas de sortie en deux temps) ; divergence ES/NQ non modélisée ; un seul indice testé (USTEC). Les autres indices (US500, DE40...) se rejouent en EXPLORATION dans l'onglet Backtests après synchronisation.
