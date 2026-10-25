# C6 — Export de l'historique PROFOND MT5 (à coller dans la conversation ChatGPT)

Tu restes l'exécutant défini par `docs/prompts/chatgpt_liaison_protocol.md` : toutes ses règles s'appliquent (aucun ordre, aucune approbation,
aucun secret, rien de faux, « non concluant » si non mesuré). Tu ne fais QUE C6. **Récupère d'abord le dernier commit** de `claude/eager-davinci-8i7zsd`.

## But
Les backtests actuels ne couvrent que ~2,5 à 3,5 ans de M15 (export plafonné à 80 000 barres). Il faut les ANNÉES PRÉCÉDENTES pour tester les stratégies
figées hors échantillon (`specs/backward_v1.json`) et, plus tard, des phases de marché différentes (baisses). Tu ne modifies aucun script de quantbot.

## Étapes
1. Dans MT5 : Outils > Options > Graphiques > « Barres max. dans l'historique » = **Illimité** (et « Barres max. dans le graphique » = Illimité). Redémarre MT5 si demandé.
   Pour chaque symbole (XAUUSD, EURUSD, USTEC) et chaque timeframe (M15 en priorité, puis H1, H4, D1), ouvre un graphique et fais défiler TRÈS loin vers la gauche
   (touche Début) jusqu'à ce que le terminal arrête de télécharger. Note la date de la plus ancienne barre visible pour chaque couple.
2. **Premier essai (EURUSD) = enseignement** : `export_mt5.py --bars 1000000` plafonne (M15 : 99 999 barres depuis 2022-10-14 ; H1 : 100 040 barres depuis 2010-09-12) et
   échoue sur H4 (« Call failed »). Utilise donc le NOUVEL export par tranches de dates, lecture seule, déjà dans le dépôt (ne le modifie pas) :
   `python scripts\export_mt5_deep.py --symbol XAUUSD --timeframes M15 H1 H4 D1 --out data\deep`
   puis idem pour EURUSD et USTEC. Il remonte tranche par tranche jusqu'à épuisement des données du serveur ; un échec sur un timeframe est consigné dans
   `EXPORT-PROVENANCE-DEEP-<SYMBOLE>.json` sans arrêter les autres. Les fichiers `<SYMBOLE>_<TF>.csv` vont dans `data\deep` et ne doivent PAS écraser `data\real`.
   Si une tranche échoue (« Call failed »), relance une fois ; si l'échec persiste, rapporte-le tel quel avec le message d'erreur exact.
3. Pour les coûts réels : `python scripts\export_symbol_specs.py --symbols XAUUSD EURUSD USTEC --out data\deep\SYMBOL-SPECS.json` (swaps, contrat, pas de prix : lecture seule).
4. Contrôle de qualité (rapporte les chiffres, ne corrige rien) pour chaque fichier : nombre de barres, première et dernière barre, doublons d'époque, OHLC invalides,
   plus grand trou en jours, SHA-256. Vérifie que `data\deep\<SYMBOLE>_M15.csv` RECOUVRE `data\real\<SYMBOLE>_M15.csv` et que les barres communes sont IDENTIQUES
   (compte les différences ; attendu : 0). Si elles diffèrent, STOP et rapporte.
5. Ne lance AUCUN backtest toi-même. Le lancement de `scripts\run_backward.py` (13 essais comptés au registre) attend ma revue et ton « suivant ».
6. Rapporte aussi, pour chaque symbole, la plus ancienne barre M15, H1, H4, D1 : la profondeur diffère selon le timeframe (H1 EURUSD remonte à 2010).

## Livraison
Dossier `livraison-C6-<date>/` : `RESULTAT.md` (par symbole et timeframe : couverture réelle, début, fin, barres, trous, recouvrement avec data\real, limites du courtier),
`manifest-sha256.json`, `SYMBOL-SPECS.json`, `EXPORT-PROVENANCE.json`. Les gros CSV ne sont pas à coller : donne leurs empreintes ; l'utilisateur les place dans `data\deep`
(ils sont ignorés par Git). Signale clairement si l'historique du serveur démo est plus court que prévu : c'est une information, pas un échec.
Ne dis pas « prêt » ni « validé ».
