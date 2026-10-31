# FUCKDARTY

Version améliorée de quantbot, **séparée** : ce dossier n'importe rien de quantbot et ne le modifie pas.
Contenu actuel : formules de référence testées des deux candidats « actions » (Attention Factors, ORB sur actions à volume inhabituel) et la décision de budget.

- `fuckdarty/equity_formulas.py` : coût de portefeuille, exposition brute, résidu de facteurs, RVOL, filtres « actions en jeu », stop 10 % ATR, quantité, coût en R, espérance.
- `tests/` : `cd fuckdarty && python -m pytest -q` (numpy et pytest seulement).
- `docs/DECISION_BUDGET.json` : plafond d'essais de quantbot décidé à 500 (non écrit dans quantbot).
- `docs/CANDIDATS_ACTIONS.md` : état honnête des deux candidats.

Aucun ordre, aucune donnée inventée. Les deux stratégies exigent des données absentes (voir le document).
