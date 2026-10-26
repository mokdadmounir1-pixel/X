# KalshiMarketMaker (rodlaf, MIT)

Teneur de marché d'Avellaneda-Stoikov sur **Kalshi** (marchés d'événements binaires régulés aux États-Unis) : sélection de marchés ouverts, un worker par marché, quotes asymétriques selon l'inventaire, plafonds globaux, annulation à la désélection.

Ce que ce dépôt N'EST PAS : un bot d'or, de MT5 ou de CFD. Il exige un compte Kalshi et une clé API (RSA) et passe de vrais ordres avec de l'argent réel. Ce projet ne l'exécute pas, ne l'importe pas et ne demande aucune clé : `fetch_references.bat` le clone seulement pour lecture (idées d'architecture : boucle de sélection, nettoyage garanti à la désélection, plafonds de portefeuille, relances avec backoff).
Utiliser Kalshi est une décision distincte, avec ses propres risques et son propre cadre légal ; rien ici n'y incite.
