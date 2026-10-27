# stop_hunt_v2 — stop-hunt corrigé + variantes VENTES SEULES et INVERSÉE (or M15, 07-17 UTC)
Spec préenregistrée avant exécution. 3 essais (registre : 112 / 120). Tranche verrouillée non lue.

Défaut corrigé (révision 2) : à taille égale, l'amas de niveaux choisi était toujours le plus BAS, y compris pour les sommets -> niveau plus facile à balayer côté vente. Désormais l'amas le plus extrême des deux côtés ; à score égal aucun sens n'est favorisé. Test de symétrie en miroir (marché miroir = signaux inverses aux mêmes barres, >= 97 % identiques).

| Variante | Trades | Espérance | PF | Achats / Ventes | Verdict |
|---|---|---|---|---|---|
| stop_hunt (achats ET ventes, corrigé) | 810 | +0,027 R | 1,06 | 432 : +0,106 R / 378 : -0,064 R | FAIL |
| stop_hunt__sell (ventes d'origine SEULES) | 630 | -0,058 R | 0,87 | 0 / 630 : -0,058 R | FAIL |
| stop_hunt__flip (achats d'origine INVERSÉS en ventes + ventes d'origine) | 817 | -0,064 R | 0,86 | 0 / 817 : -0,064 R | FAIL |

Sur 2,5 ans de recherche, les ACHATS gagnent (+0,11 R) et les VENTES perdent (-0,06 R) : l'inverse de ce que l'utilisateur a vu sur la simulation récente. Une courte fenêtre récente (peu de trades, régime de marché) ne contredit pas 2,5 ans ; les variantes vente-seule et inversée sont POST-HOC et ne valent rien tant que l'échantillon futur (>= 60 trades par variante, en simulation PAPER) ne les confirme pas. Les trois tournent séparément en PAPER (XAU_STOP_HUNT, XAU_STOP_HUNT_SELL, XAU_STOP_HUNT_FLIP) pour trancher sur des données jamais vues.
