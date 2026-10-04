# nexus_agents — agents et orchestrateur au-dessus de nexus_core

Passerelle de modèles, agents spécialisés (Sourcing, Analyste, Rédacteur, Censeur, Setter, Transport) et Hermes,
qui les enchaîne. Tout passe par `nexus_core` : budget, revue indépendante, approbation, opposition, audit.

## Lancer la démonstration
```
python -m nexus_agents.demo --out nexus_agents/demo_out --narrate     # trace dans le terminal + trace.json
python -m nexus_agents.render_html nexus_agents/demo_out/trace.json nexus_agents/demo_out/coulisses.html
python -m pytest nexus_agents/tests nexus_core/tests -q                # 89 tests
```
Elle démarre un PostgreSQL temporaire (socket Unix, aucun port réseau), exécute six leads **fictifs** et écrit la trace réelle.

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
- Hermes n'a pas de file de tâches durable : l'état du pipeline vit en mémoire pendant une exécution. À faire avant tout usage réel.
- L'adaptateur Ollama n'accepte que la boucle locale, sauf liste blanche explicite (ex. adresse du tunnel privé).
- Aucun envoi réel, aucune dépense : rien ici ne prouve qu'un client paiera.
