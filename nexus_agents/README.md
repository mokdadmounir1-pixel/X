# nexus_agents — agents et orchestrateur au-dessus de nexus_core

Passerelle de modèles, agents spécialisés (Sourcing, Analyste, Rédacteur, Censeur, Setter, Transport) et Hermes,
qui les enchaîne. Tout passe par `nexus_core` : budget, revue indépendante, approbation, opposition, audit.

## Lancer la démonstration
```
python -m nexus_agents.demo --out nexus_agents/demo_out --narrate     # trace dans le terminal + trace.json
python -m nexus_agents.render_html nexus_agents/demo_out/trace.json nexus_agents/demo_out/coulisses.html
python -m pytest nexus_agents/tests nexus_core/tests -q                # 216 tests
```
Elle démarre un PostgreSQL temporaire (socket Unix, aucun port réseau), exécute six leads **fictifs** et écrit la trace réelle.

## Banc de qualification des modèles locaux (à lancer sur le PC d'Ollama)
```
python -m nexus_agents.benchmark --models mistral,qwen2.5:7b --base-url http://127.0.0.1:11434 --out benchmark_out
python -m nexus_agents.benchmark --stub --out /tmp/bench      # vérifie seulement que le banc fonctionne
```
- 44 exemples fictifs de départ (classification des réponses, extraction d'une citation, brouillon), dont des textes qui contiennent des consignes cachées.
- **Seuils fixés avant toute mesure** (`benchmark/thresholds.json`) ; leur empreinte est inscrite dans le manifeste, donc les assouplir après coup l'invalide.
- Le verdict ne repose que sur la partie `holdout`. Sous 30 exemples holdout par tâche, il reste **provisoire** et ne qualifie pas.
- Écrit un manifeste `qualification_<modèle>.json` ; `ModelGateway(qualified_tasks=...)` refuse alors (pause, jamais le cloud) toute tâche locale non qualifiée.
- **À faire par vous :** remplacer/compléter `dataset.json` par de vrais exemples annotés de votre main. Le jeu fourni est un point de départ rédigé par Claude, trop petit pour décider.

## File de tâches durable
Hermes met chaque lead et chaque réponse en file (`task`) : bail avec expiration, 3 tentatives, délai croissant, puis tâche « morte » avec alerte au fondateur. Une clé de dédoublonnage évite de traiter deux fois un même domaine, même après redémarrage.

## Filet d'opposition
Une opposition (« stop », « ne plus m'écrire », « liste de diffusion », « unsubscribe »…) est détectée par règle fixe **en plus** du modèle et force la suppression, même si le modèle l'a classée autrement.

## Réel et simulé
| Réel | Simulé |
|---|---|
| PostgreSQL 16, rôles et droits, budget, revue indépendante, approbation liée au hash, opposition, audit | Les modèles `Stub*` : règles fixes, **pas d'intelligence** |
| Filtre d'injection (heuristique), vérification déterministe de la citation, passerelle et son budget | Le SMTP (puits en mémoire), les décisions du fondateur (scriptées), les leads |
| Adaptateur `OllamaModel` (testé contre un faux serveur HTTP local, jamais contre un vrai Ollama ici) | |

## Limites à connaître
- Le filtre d'injection est une heuristique : la vraie frontière, ce sont les droits de la base (un agent ne peut ni approuver, ni envoyer, ni dépenser seul).
- Le Censeur de la démonstration applique des règles simples ; la qualité réelle d'une revue dépend du modèle qui la fera. Sa **corrélation** avec le rédacteur reste à mesurer quand de vrais modèles seront branchés.
- Les prix du modèle cloud simulé sont illustratifs. Aucun fournisseur n'est connecté.
- La file de tâches est durable, mais les résultats cloud déjà payés sont mis en cache **en mémoire** (une relance dans le même processus ne refacture pas) : à persister avant tout fournisseur réel.
- Une relance après plantage rejoue les étapes ; elles sont idempotentes en base (mêmes clés), mais un appel à un modèle local peut être refait.
- L'adaptateur Ollama n'accepte que la boucle locale, sauf liste blanche explicite (ex. adresse du tunnel privé).
- Aucun envoi réel, aucune dépense : rien ici ne prouve qu'un client paiera.


## Quatre corrections critiques (migration 002)
1. **Observabilité totale** — `rejection.py` : tout écartement (Sourcing, Analyste, Rédacteur, Censeur, Fondateur, Closing, coupe-circuit) produit un `RejectionDetail` avec `motif_exact`, `preuve_source`, `indice_confiance`.
   Écrit en base (table immuable) et affiché dans le journal des appels. `Hermes._end` lève une erreur si un lead est écarté sans détail.
2. **Closing automatique** — `closing.py` : sur « prêt à signer », extraction des variables (avec provenance), devis PDF déterministe, lien d'acompte, message déposé pour revue puis approbation du fondateur. **Rien n'est envoyé seul.**
   Le prix vient du catalogue ; la réponse du prospect ne peut que le confirmer. Lien de paiement : simulé par défaut ; `StripeCheckoutProvider` n'accepte que des clés `sk_test_` (mode test) et n'a été testé que contre un faux serveur local.
   Mentions de l'émetteur laissées « À COMPLÉTER » (la structure juridique n'existe pas) ; le devis est un projet à faire relire par un professionnel.
3. **Évolutions déployées** — `prompts.py` : les prompts sont lus en base à chaque appel. Approbation du fondateur → déploiement par la base → effet à l'appel suivant, sans redémarrage. Retour arrière possible.
   Les modèles simulés *miment* l'effet du prompt ; avec un vrai modèle, l'effet doit être mesuré (A/B) avant de s'y fier.
4. **Réserve prioritaire** — la passerelle réserve avec `task`, `lead_ref` et `api=True` ; la base décide d'après le score enregistré. Preuve : `python -m nexus_agents.scenarios.reserve_prioritaire` (log commité dans `preuves/`).
