# gold_winrate_v1 — INVALIDE (0 trade pour 8 variantes sur 9)
Cause : `risk.min_reward_risk = 1,3` hérité faisait rejeter tout signal de cible < 1,3 R (`rr_insuffisant`). Rien n'a été testé. 9 essais comptés quand même (registre). Corrigé et rejoué dans `gold_winrate_v1b` (seul changement : min_reward_risk = 0,3).
