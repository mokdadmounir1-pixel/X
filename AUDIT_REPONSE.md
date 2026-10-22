# Réponse à l'audit externe du 22 octobre 2026 (confrontation au code)

Statuts : **JUSTE** (corrigé ou à corriger) · **COUVERT** (déjà dans le code) · **PARTIEL** · **INEXACT** · **NON FAIT** (assumé).
L'audit a été fait « sur une description, sans audit du code » (il le dit) et le texte reçu s'arrête au début de la section 3 (« les neuf portes que j'imposerais » n'a pas été lu).
Aucun chiffre ci-dessous n'est une performance de marché : tout est `[SYNTHÉTIQUE]` ou mécanique.

## Verdict exécutif
| Point de l'audit | Statut | Où / quoi |
|---|---|---|
| Aucune preuve d'edge sur marché réel | **JUSTE, déjà affirmé** | `ETAT_PROJET.md` §3 et §5 : aucun PASS, aucune donnée réelle |
| +5 %/mois = +10 R à 0,5 % | **COUVERT** | `README.md` « Lecture honnête », `target.py` |
| Risque principal : écart simulation M1/M15 ↔ exécution MT5 | **JUSTE** | bornes d'ambiguïté + slippage de volatilité ajoutés ; la vraie mesure viendra de la **démo** (écart prix demandé/exécuté déjà journalisé par le pont) |
| Trop de stratégies + auto-amélioration avant la 1re validation réelle | **JUSTE en partie** | la boucle est calibrée (0/40 faux « utile » sous le nul) mais la surface d'essais grandit : registre des essais + DSR cumulatif ajoutés. **Gel de la création de nouveaux algos accepté** jusqu'aux premiers résultats réels |
| 0 faux positif sur 60 ≠ taux nul (borne ≈ 4,87 %) | **COUVERT** | déjà écrit : « borne haute ≈ 4,9 % » (`1 − 0,05^(1/60)`) |
| Priorités : qualité des données, simulation d'exécution, preuve hors échantillon | **D'ACCORD** | `data-check`, bornes d'exécution, période verrouillée + démo |

## Failles méthodologiques
**A. OHLC / ordre stop-cible.** *Principe JUSTE, formulation INEXACTE.* Le moteur ne « choisit pas −1 R » systématiquement : quand des barres plus fines existent (M5 sous du M15), il résout l'ordre dessus (`_fine_first`). Seule l'ambiguïté **résiduelle** retombait sur le stop. Gap au-delà du stop : exécution à l'ouverture, perte > 1 R possible (`stop_gap`, testé) ; annonces : spread ×3, slippage ×1,5.
*Ajouté :* `SimConfig.ambiguity` (`stop` | `target` | `random`), drapeau `amb` par trade, et dans chaque rapport de recherche `intrabar` = part de trades ambigus et **fourchette d'espérance** stop-d'abord / cible-d'abord. *NON FAIT :* résolution par **ticks bid/ask** (il faut exporter des ticks MT5/Dukascopy et écrire le chargeur ; indispensable pour le scalp M1 avant tout verdict).

**B. Coûts conditionnels.** *PARTIEL.* Déjà : spread par barre (colonne MT5) ou profil horaire, ×3 annonces, slippage ×1,5 annonces, commission par lot, swaps (triple mercredi), porte « coûts ×2 > 0 ». *Ajouté :* `SimConfig.vol_slip` (slippage croissant avec l'amplitude de la barre relative à l'ATR, plafonné ×4, **désactivé par défaut**, testé). *NON FAIT :* dépendance au type d'ordre et à la liquidité réelle (seule la démo les mesure). Le rejet d'une stratégie M1 dont l'edge disparaît sous coûts plausibles existe déjà (porte 5 + filtre de coût du scalp).

**C. Nombre réel d'essais.** *JUSTE, corrigé.* `registry.py` : registre **append-only, chaîné par hachage** (`trials_registry.jsonl` dans le dossier de sortie) ; chaque `research` y consigne ses essais ; le DSR ajoute les essais **antérieurs de la même famille** (même ensemble d'instruments, réel/synthétique), une ré-exécution identique ne compte qu'une fois. Limite : comptage brut, non corrigé des corrélations (donc conservateur).

**D. Test nul.** *PARTIEL, point juste.* Le signe aléatoire par blocs d'un jour conserve volatilité et saisonnalité, mais il **conserve aussi les motifs intrajournaliers symétriques** (une cassure haussière devient une cassure baissière identique) : il teste mal les stratégies intraday symétriques. *Ajouté :* batterie — (1) signe aléatoire par jour, (2) **bootstrap stationnaire** par blocs de ~4 h (détruit la persistance à l'échelle du jour, testé), (3) **décalage des signaux de ±7 à ±56 jours** à distances relatives conservées (le timing exact compte-t-il ?) ; la porte 4 exige les trois. Rapport : **White Reality Check** sur les rendements quotidiens OOS de tous les algos (biais de sélection). *NON FAIT :* SPA de Hansen, permutation par régimes comparables. Déjà couvert : simulation de processus sans alpha (calibration sur marches aléatoires).

**E. Verrou final fragile.** *JUSTE sur le principe.* Déjà : purge/embargo 5 jours, marqueur disque (évaluation unique), divulgation de toute lecture antérieure. À faire sur réel : valider sur instruments non utilisés à la conception ; la **période prospective** est la démo ≥ 4 semaines exigée par `gate` avant tout réel.

## Les neuf portes (`research/gates.py`)
*Ajouté :* classes **éliminatoires** (n, test nul, coûts ×2, Monte Carlo p5 > capital, séries de pertes/DD) et **statistiques** (espérance, PF, concentration top-3, plateau) ; un algo qui échoue une porte éliminatoire ne peut plus être WATCH. La règle PASS reste « toutes les portes + DSR », donc **plus stricte** que le principe de l'audit (qui tolère des échecs statistiques). Risque de ruine : porte 6 + porte 9 + module `target` (P(violation) < 5 %, daily/max loss simulés par jour sur les trades chronologiques — déjà couvert) ; *ajouté :* tableau de **stress** (`target` affiche P(violation) si l'espérance baisse de 0,05 / 0,10 / 0,20 R par trade).
Exclusions automatiques (risque de mémoriser le passé) : déjà en ombre + Šidák ; *ajouté :* une zone n'est exclue que si elle perd dans **les deux moitiés** de la fenêtre d'entraînement.

## Effets sur les résultats publiés
Les rapports de référence synthétiques (tous FAIL) ne changent pas de conclusion. Les nouvelles portes ne peuvent qu'**abaisser** la proportion de PASS (donc pas augmenter le taux de faux PASS) ; la puissance (edge planté fort) est remesurée : voir `ETAT_PROJET.md` §3quater.
