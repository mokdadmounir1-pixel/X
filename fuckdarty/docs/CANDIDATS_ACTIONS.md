# Deux candidats « actions » : état réel

| Candidat | Résultat publié (simulation d'auteurs) | Ce qu'il faut | État |
|---|---|---|---|
| Attention Factors (arbitrage statistique, 30 facteurs, LongConv) | 9,52 % net, Sharpe 2,28 net, 1998-2021, bêta 0,05 | 500 plus grosses actions US (anciennes incluses), facteurs, apprentissage profond (8 ans glissants, réentraînement annuel) | **NON faite** : données absentes ; code et poids originaux non vérifiés ; impact de marché absent de la formule de coût |
| ORB 5 minutes + volume relatif | 41,6 % composé, Sharpe 2,81, 2016-2023, drawdown 12 % | barres de 5 minutes d'actions US avec volume réel d'ouverture sur 14 séances, tout l'univers | **NON faite** : données absentes ; aucun protocole hors échantillon ni glissement publié ; stop à 10 % de l'ATR = frais très lourds en R |

Les formules de ces deux méthodes sont dans `fuckdarty/equity_formulas.py` et testées. Les chiffres publiés ne sont pas reproduits ici et ne prouvent rien en réel.
