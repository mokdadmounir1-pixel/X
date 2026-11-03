# Programme de recherche v1 — résultats (2026-11-03)

29 essais dépensés sur 50 autorisés (registre : 120 -> 149, chaîne vérifiée ; plafond global 500). Période de recherche, tranche verrouillée jamais lue. **Aucun PASS.** Spécifications figées, un seul amendement (`candidates_v1b`) pour un défaut de conception (0 trade) sans performance vue.

| Stratégie | Instrument | Trades | Espérance | PF | Achats / ventes | Lecture |
|---|---|---|---|---|---|---|
| gap_fade | USTEC | 106 | +0,144 R | 1,64 | +0,20 / +0,10 | le plus proche du seuil 0,15 R ; échoue test nul + DSR |
| noise_area | USTEC | 287 | +0,082 R | 1,33 | +0,085 / +0,080 | équilibré achats/ventes ; échoue espérance, test nul, Monte-Carlo, DSR |
| smc_h4_free | USTEC | 71 | +0,091 R | 1,20 | +0,39 / -0,17 | bêta haussier |
| smc_h4 | USTEC | 37 | +0,084 R | 1,18 | +0,51 / -0,12 | bêta haussier, peu de trades |
| smc_h1_free | XAUUSD | 196 | +0,057 R | 1,10 | +0,14 / -0,05 | bêta haussier |
| smc_m15_free | USTEC | 648 | +0,029 R | 1,19 | +0,05 / +0,01 | quasi nul |
| smc_m15 | USTEC | 300 | +0,013 R | 1,10 | +0,01 / +0,02 | quasi nul |
| ibs_reversion (v1b) | USTEC | 197 | +0,011 R | 1,07 | +0,01 / +0,01 | nul |
| omega | XAUUSD | 1905 | +0,010 R | 1,04 | +0,03 / -0,01 | nul |
| ibs_rsi2_trend | USTEC | 50 | +0,007 R | 1,06 | +0,01 / — | nul (50 trades) |
| overnight_premium | USTEC | 476 | +0,006 R | 1,05 | achats seuls | bêta |
| london_breakout | EURUSD | 434 | +0,001 R | 1,00 | +0,03 / -0,03 | nul |
| omega | USTEC | 1941 | -0,003 R | 0,98 | +0,02 / -0,02 | nul |
| smc_h4_free | XAUUSD | 59 | -0,008 R | 0,99 | +0,09 / -0,13 | nul |
| london_breakout | XAUUSD | 350 | -0,021 R | 0,95 | +0,02 / -0,08 | nul |
| intraday_momentum | USTEC | 74 | -0,030 R | 0,73 | +0,02 / -0,12 | négatif |
| smc_h1_free | EURUSD | 186 | -0,043 R | 0,92 | -0,09 / +0,02 | négatif |
| turn_of_month | USTEC | 16 | -0,062 R | 0,82 | achats seuls | trop peu de trades |
| smc_m15_free | XAUUSD | 608 | -0,065 R | 0,82 | -0,01 / -0,13 | négatif |
| omega | EURUSD | 1901 | -0,069 R | 0,73 | -0,04 / -0,10 | négatif |
| smc_m15 | XAUUSD | 254 | -0,087 R | 0,74 | -0,08 / -0,09 | négatif |
| smc_m15 | EURUSD | 246 | -0,097 R | 0,66 | -0,11 / -0,09 | négatif |
| smc_m15_free | EURUSD | 576 | -0,120 R | 0,64 | -0,11 / -0,13 | négatif |
| smc_h1_free | USTEC | 158 | -0,132 R | 0,63 | -0,20 / -0,08 | négatif |
| smc_h4_free | EURUSD | 59 | -0,324 R | 0,53 | -0,31 / -0,33 | négatif |
| smc_h4 | XAUUSD | 20 | -0,277 R | 0,56 | -0,53 / -0,07 | négatif, 20 trades |
| smc_h4 | EURUSD | 29 | -0,433 R | 0,43 | -0,47 / -0,40 | négatif |
| rsi2_reversion (v1b) | USTEC | 11 | +0,149 R | 2,80 | 10 achats | NON CONCLUANT (11 trades) |
| ibs_reversion (v1) | USTEC | 0 | — | — | — | essai gaspillé : filtre R:R du moteur (corrigé par l'amendement) |

## Lecture honnête
- Aucune stratégie ne passe les portes (espérance >= 0,15 R, test nul, DSR sur 149 essais). Les positifs les plus nets sont soit du bêta haussier (achats positifs, ventes négatives : SMC H4/H1 FREE, overnight), soit de faible espérance.
- Deux pistes équilibrées achats/ventes méritent le seul traitement admis : l'échantillon avant-coup en PAPER (>= 4 semaines, >= 60 trades) : **gap_fade (USTEC)** et **noise_area (USTEC)**. Les coûts utilisés sont ceux de la spec (commission = hypothèse) ; le spread FTMO réel peut tout effacer.
- Le filtre 3 R des SMC n'apporte rien de systématique : FREE fait mieux sur certains, pire sur d'autres.
- Aucun réglage n'a été fait d'après ces résultats.
