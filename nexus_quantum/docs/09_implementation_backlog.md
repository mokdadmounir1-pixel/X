# 09 — Implementation Backlog

Priorité P0 (bloquant) → P3. Coût S/M/L. Valeur = réduction du risque de capital ou de faux positifs.
| ID | Tâche | P | Coût | Dépend de | Critère d'acceptation |
|---|---|---|---|---|---|
| A-1 | Fournir `ftmo_algo` et exécuter l'audit Partie II | P0 | M | accès repo | registre de défauts avec test par défaut |
| D-1 | Data Auditor + stockage brut immuable + hash | P0 | M | — | 100 % traçable, test de corruption |
| E-1 | Moteur événementiel de backtest sans look-ahead (test décalage 1 barre) | P0 | L | D-1 | résultat identique en rejouant ; test de fuite |
| E-2 | Persister l'`audit` du Guardian dans le registre | P1 | S | — | chaîne vérifiable |
| V-1 | Nuls (permutation/surrogates), White RC, SPA | P1 | M | E-1 | tests sur bruit : faux positifs ≈ α |
| V-2 | Stabilité param., concentration, inter-instruments | P1 | M | E-1 | carte de validation |
| R-1 | Guardian : horloge, gaps, marge, corrélation, CVaR | P1 | M | — | tests d'injection |
| R-2 | Fuzz/propriétés sur `check` | P1 | S | — | I1–I4 tenus sur 10⁵ cas |
| S-1 | Stratégie 1 : TSMOM daily (hypothèse enregistrée d'abord) | P2 | M | E-1,V-1 | G0–G10 ou rejet consigné |
| S-2 | Stratégies sessions/ORB | P2 | M | E-1 | idem |
| X-1 | Adaptateurs broker (OMS idempotent, réconciliation) + shadow | P2 | L | R-1 | écart position = 0 sur 30 jours shadow |
| X-2 | Adaptateur prop (règles vérifiées à date) | P2 | M | X-1 | rapport de conformité |
| M-1 | Collecte de coûts/latences réels brokers | P2 | M | — | grille 06 remplie avec sources |
| L-1 | Simulateur de file calibré | P3 | L | M-1, données L2 | écart simu/réel mesuré |
| AI-1 | Agents/pipeline champion-challenger | P3 | L | V-1 | promotion jamais automatique |
