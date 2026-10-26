# oss_quant_stack — projet SÉPARÉ construit uniquement avec 5 dépôts open source

Aucun import de `quantbot` ni de Nexus. Dossier autonome (à pousser dans un dépôt à part si tu le souhaites). Les 5 dépôts demandés :

| # | Dépôt | Licence | Rôle ici | État |
|---|---|---|---|---|
| 1 | [hftbacktest](https://github.com/nkaz001/hftbacktest) | MIT | backtest haute fréquence (carnet, file d'attente, latences) | installé, actif configuré ; **aucun backtest** : exige des données de carnet réelles (`docs/HFTBACKTEST_DONNEES.md`) |
| 2 | [vectorbt](https://github.com/polakowo/vectorbt) | Apache-2.0 + Commons Clause (pas de revente du logiciel) | backtests vectorisés rapides sur barres | installé ; `examples/vbt_baseline.py` tourne |
| 3 | [KalshiMarketMaker](https://github.com/rodlaf/kalshimarketmaker) | MIT | référence d'architecture d'un teneur de marché | cloné pour lecture (`fetch_references.bat`) ; **non exécuté** : marchés Kalshi, clé API, argent réel (`docs/KALSHI.md`) |
| 4 | [TensorTrade](https://github.com/tensortrade-org/tensortrade) | Apache-2.0 | apprentissage par renforcement | **non installé ni testé** : impose pandas<3 et TensorFlow (`requirements-tensortrade.txt`, environnement séparé) |
| 5 | [NautilusTrader](https://github.com/nautechsystems/nautilus_trader) | LGPL-3.0 | moteur événementiel de backtest/production | installé ; `examples/nautilus_bars_backtest.py` tourne. Pas d'adaptateur MetaTrader 5 |

## Utilisation
```
python -m venv .venv && .venv\Scripts\activate        (Windows)
pip install -r requirements.txt
python examples/vbt_baseline.py   chemin\XAUUSD_M15.csv
python examples/nautilus_bars_backtest.py   chemin\EURUSD_M15.csv
python examples/hftbacktest_smoke.py
python -m pytest -q
```
Les CSV sont des exports MT5 (colonnes `time, open, high, low, close`). Les 12 derniers mois ne sont jamais lus.

## Ce que ce projet ne fait pas (honnêtement)
- **Aucun résultat de ces exemples n'est une preuve d'avantage.** Les paramètres sont figés ; ce sont des tests de plomberie. Mesuré une fois pour vérifier le fonctionnement : sur l'or M15, un croisement EMA 20/50 long seul avec frais gagne moins que l'achat-conservation (bêta de l'or) ; sur EURUSD, le croisement Nautilus perd.
- **Rien ne passe d'ordre**, aucune clé, aucun compte. MetaTrader 5 n'est pas supporté par Nautilus ; relier MT5 reste le travail du projet `quantbot`.
- La vraie recherche rigoureuse (essais comptés, tranche verrouillée, test nul, DSR) vit dans `quantbot/`, pas ici.
