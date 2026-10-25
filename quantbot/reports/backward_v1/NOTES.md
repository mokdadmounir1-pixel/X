# backward_v1 — exécution INCOMPLÈTE (1 combinaison sur 13)

Lancée une fois sur le PC de l'utilisateur le 2026-10-25 (livraison C8). Le programme a planté à l'affichage (`UnicodeEncodeError` sous cp1252 sur le caractère « → »)
APRÈS le premier essai : seul **EURUSD amd** a été calculé (123 trades, espérance -0,0525 R, PF 0,81, FAIL). Les 12 autres combinaisons n'ont PAS été exécutées :
ce ne sont pas douze verdicts négatifs. Le défaut d'affichage est corrigé (voir `quantbot/console.py` et les scripts) ; la relance ne repasse que ce que le registre ne connaît pas.
Segment utilisé : 19 999 barres M15 avant le début de la période de recherche (environ 10 mois) : peu de trades, puissance limitée.
