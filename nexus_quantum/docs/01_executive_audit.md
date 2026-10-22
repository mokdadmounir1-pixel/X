# 01 — Executive Audit

## Ce qui a été réellement examiné
| Élément | Statut |
|---|---|
| Projet `ftmo_algo` (moteur, 9 portes, gardien FTMO, pont MT5, agents live, dashboard, auto-amélioration) | **NON ACCESSIBLE** dans cette session : absent du dépôt `mokdadmounir1-pixel/X`, absent de `list_repos` (résultat vide). **Aucun audit n'est prétendu.** |
| Dépôt `X` (présent) | Contient `micro_scalping/`, `fx_liquidity_bot/`, scripts de stress synthétique. Ce sont d'**autres projets** : conformément à la consigne, **aucun fichier existant n'a été modifié ni audité en détail**. NEXUS QUANTUM vit isolé dans `nexus_quantum/`. |

Conséquence : la Partie II (audit défaut par défaut) ne peut pas être produite honnêtement. Ci-dessous, le **plan d'inspection** et la liste des fichiers à fournir. Les défauts listés en `02`/`05` sont des **[HYPOTHESE] a priori typiques**, pas des constats.

## Fichiers nécessaires pour l'audit de `ftmo_algo`
Arborescence complète (`tree -L 3`), `requirements*.txt`/lockfile, moteur de backtest et simulateur d'ordres, modèle de coûts, stratégies M15/M1, gardien FTMO, code des 9 portes, tests nuls/surrogates, DSR, walk-forward, module d'auto-amélioration, pont MT5, agents live, dashboard, config/secrets (valeurs masquées), logs d'un run, suite de tests + sortie `pytest`, exemple de données (hash + provenance).

## Plan d'inspection (par composant → question qui tue)
| Composant | Test d'inspection | Défaut classique recherché |
|---|---|---|
| Backtest | exécution décalée d'une barre : le résultat survit-il ? | look-ahead (signal sur close, fill au même close), SL/TP dans la même barre sans règle d'ordre |
| Simulation d'ordres | fill limite sur simple « touch » ? | surestimation des fills passifs |
| Coûts | spread fixe ? swap ? commission aller-retour ? | spread constant en sessions illiquides/news |
| Gardien FTMO | perte jour calculée sur **equity flottante** ? reset à l'heure serveur ? | franchissement intra-barre non vu, fuseau horaire |
| 9 portes | quels seuils réglés **après** observation ? N d'essais compté ? | portes réglées sur la période finale (surapprentissage de méta-niveau) |
| DSR | N = nombre réel d'essais (négatifs inclus) ? | N sous-estimé ⇒ DSR gonflé |
| Walk-forward | purge/embargo ? paramètres figés ? | chevauchement de labels |
| Auto-amélioration | peut-elle écrire dans la config de risque ? se promouvoir ? | boucle fermée de sélection sur le test |
| Pont MT5 | idempotence, ack, réconciliation au restart, ordres fantômes | doublons, état inconnu après crash |
| Agents live / dashboard | le dashboard est-il dans le chemin de trading ? | point unique de défaillance |
| Sécurité | secrets en clair ? dépendances épinglées ? | clés dans le repo, `pip` non épinglé |
| Tests | couverture des chemins d'échec ? | tests uniquement « happy path » |

Format de registre de défaut (à instancier à l'audit) : ID, gravité, cause racine, déclenchement, conséquence, fréquence±incertitude, détection, prévention, correction, test, risque résiduel, validateur. Gabarit : `05_failure_mode_register.md`.

## Forces/risques du **projet NEXUS** (ce qui existe réellement)
Forces : noyau stdlib-only, 31 tests verts, registre infalsifiable, Risk Guardian isolé. Risques : aucune donnée de marché, aucune stratégie, aucun adaptateur broker — **aucun edge n'est établi**. Statut courant : « pas de preuve d'edge ⇒ pas de déploiement ».
