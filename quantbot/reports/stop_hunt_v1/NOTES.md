# stop_hunt_v1 — balayage de réservoir de liquidité + retour (or M15, 07-17 UTC)
Spec préenregistrée avant exécution. 1 essai (registre : 106 / 120). Tranche verrouillée non lue.
Résultat : FAIL. 800 trades, +0,060 R, PF 1,14 ; achats +0,13 R / ventes -0,03 R (bêta haussier de l'or). Échecs : espérance (0,15 requis), PF, test nul, Monte-Carlo, enveloppe de risque, DSR.

# Lead-lag EURUSD -> or (descriptif, aucun essai compté ; période de recherche, 52 513 barres M15)
corr(or[t], EURUSD[t]) = +0,320 (simultané : facteur dollar) ; corr(or[t], EURUSD[t-1]) = +0,0069 (t ≈ 1,6) ; lags 2-4 ≈ 0. USTEC : lag 0 = 0,060 ; lag 1 = 0,005.
Aucune avance exploitable à une barre M15 : l'information inter-marchés est déjà dans le prix de l'or à la clôture. L'avance de quelques ms décrite pour le HFT n'est pas observable avec ces données.
