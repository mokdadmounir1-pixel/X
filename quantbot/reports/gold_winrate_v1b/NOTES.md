# gold_winrate_v1b — variantes à taux de réussite plus élevé sur l'or (XAUUSD M15)
Spec amendée (min_reward_risk 0,3) commitée avant exécution. 9 essais (registre : 104 / 120). Tranche verrouillée non lue.

| Variante | Trades (recherche) | Espérance | PF | Verdict |
|---|---|---|---|---|
| sweep cible 0,5 R | 704 | -0,029 R | 0,82 | FAIL |
| sweep cible 0,75 R | 704 | -0,014 R | 0,93 | FAIL |
| sweep cible 1,0 R | 704 | -0,021 R | 0,91 | FAIL |
| repli EMA cible 0,5 R | 1058 | -0,022 R | 0,90 | FAIL |
| repli EMA cible 0,75 R | 1009 | -0,008 R | 0,97 | FAIL |
| repli EMA cible 1,0 R | 965 | +0,001 R | 1,00 | FAIL |
| retour moyenne stop 2 ATR | 137 | -0,014 R | 0,96 | FAIL |
| retour moyenne stop 3 ATR | 137 | +0,051 R | 1,15 | FAIL |
| retour moyenne stop 4 ATR | 137 | +0,050 R | 1,19 | FAIL |

Illustration du piège (rejeu sur la fenêtre récente de l'interface, 130-215 trades, pas la recherche entière) : sweep cible 0,5 R = 63 % de réussite mais R:R réalisé 0,52 -> seuil d'équilibre 66 % -> perdant ; repli EMA cible 0,5 R = 62 % / R:R 0,50 -> seuil 67 % -> perdant. Un taux de réussite > 60 % existe donc facilement, sans espérance positive.
Meilleur : retour à la moyenne stop 3-4 ATR (+0,05 R, PF 1,15-1,19), loin du seuil d'espérance (0,15 R), achats seuls +0,09 à +0,11 R = profil de bêta haussier de l'or.
(gold_winrate_v1 : invalide, voir son NOTES.md.)
