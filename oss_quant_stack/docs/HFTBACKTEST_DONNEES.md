# hftbacktest : données requises

hftbacktest (MIT) rejoue des ÉVÉNEMENTS de carnet (profondeur L2/L3 + transactions) avec horodatages exchange/local, file d'attente et latences. Un backtest valide exige :
- des mises à jour de profondeur avec prix ET tailles, par niveau ;
- les transactions (prix, taille, sens) ;
- deux horodatages par événement (bourse, réception locale) pour modéliser la latence.

Ce que quantbot enregistre aujourd'hui (`data/live/ticks/`) : bid, ask, last, volume, flags en millisecondes. **Pas de tailles bid/ask, pas de niveaux** : convertir ces ticks en « profondeur » inventerait les tailles et rendrait le positionnement dans la file (le cœur de l'outil) faux. Aucune conversion n'est fournie.
Pour l'or : un flux de profondeur réel (courtier qui expose `market_book`, ou fournisseur de données L2) est nécessaire ; la collecte de `market_book_get` est déjà active dans le terminal quantbot (`data/live/depth/`) si le courtier l'expose.
