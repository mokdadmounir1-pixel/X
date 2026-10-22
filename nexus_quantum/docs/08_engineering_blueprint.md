# 08 — Engineering Blueprint

Arborescence : `nexus/{registry,stats,risk,costs,economics}.py`, `tests/`, `scripts/`, `docs/`.
Dépendances : noyau = **aucune** (stdlib, Python ≥3.11). Dev : pytest. Recherche future : numpy/pandas (jamais importés par `risk.py`).
Interfaces stables : `Order`, `Decision`, `HardLimits`, `InstrumentSpec`, `ExperimentRegistry`. Les strategies émettent des *intentions* ; l'allocator produit des `Order` ; le Guardian décide.
Tests : unitaires (31 ✔), propriétés/fuzz sur `check` (☐), injection de panne (☐), intégration adaptateur (☐), charge/latence (☐). CI : pytest + lint à chaque commit (☐ — non ajoutée pour ne pas toucher d'infrastructure partagée du dépôt).
Sécurité : secrets hors dépôt (`.gitignore`), clés live séparées, permissions minimales, journal d'audit, sauvegardes + test de restauration (☐).
Invariants vérifiables : (I1) limites ne croissent jamais ; (I2) aucun ordre d'entrée approuvé en état non réconcilié ; (I3) `CONFIRMED` ⇒ preuve broker ; (I4) chaîne du registre valide ou alerte.
