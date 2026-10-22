# Algos de Leo — port Python des EA MT5

Source : les EA MQL5 de la formation « Algo Rentable » (`01_Range_Breakout`, `02_Bandito`, `03_Happy_Gold`, `04_Double_Croisement`,
`05_Hybride_MM_SuperTrend`, `07_Cloud_EMA_ATR`, `08_Gold_Scalping`, `SuperSelector_MT5_FINAL`). Ils tournent maintenant **dans le moteur
du projet** (même interface, même dashboard, mêmes portes, même période verrouillée) : 14 algos `leo_*`, visibles dans la liste des algos
du dashboard et de la CLI (`--algos leo_bandito,...`).

> **Statut** : le port est vérifié contre une référence littérale (SuperTrend de l'EA 05, pivots, machine d'états Cloud) et testé
> (causalité, horaires, moteur). **Aucun résultat sur données réelles** : cet environnement n'a ni MT5 ni historique. Les chiffres ci-dessous
> sont `[SYNTHÉTIQUE]` ; ils valident la mécanique, pas la rentabilité. Le fichier `06_...` n'a pas été reçu : rien n'est porté à sa place.

## Correspondance

| EA | algo(s) Python | logique d'entrée portée | sorties portées | instrument d'origine |
|---|---|---|---|---|
| 01 Range Breakout | `leo_range_breakout` | plage 00:00→07:30 serveur (≥ 90 % des barres), 1ʳᵉ cassure du jour dans un sens, SL au bord opposé ou en % | pas de TP, clôture 18:00, jamais d'overnight | multi-actifs |
| 02 Bandito | `leo_bandito` | Bollinger(20, 2σ) H1, **première** clôture hors bande (pas de réintégration), spread ≤ 3 pips | SL 180 / TP 130 pips, trailing (départ +10, distance 180), sortie sur bande ou MM50 | AUDCAD |
| 03 Happy Gold | `leo_happy_gold` | cassure du dernier pivot fractal confirmé (12 barres de chaque côté), long seul par défaut, spread ≤ 35 pts | SL 240 / TP 1000 pts, BE à +10 pts, trailing 20 pts, session 03:00→19:00 (vendredi 12:00) | XAUUSD |
| 04 Double Croisement | `leo_double_croisement` | EMA 4/29 hebdo **et** EMA 10/15 quotidienne haussières (états, pas croisements), décision 01:00, long seul | SL 2×ATR D1, clôture 21:30 | indices / or |
| 05 Hybride MM+SuperTrend | `leo_hybride_supertrend` | EMA 4/29 hebdo + SuperTrend D1 (ATR 10, ×3) haussiers, décision 01:00, long seul | SL 2×ATR D1 (Wilder), clôture 21:30 | indices / or |
| 07 Cloud EMA/ATR | `leo_cloud_ema_atr` (grille : 3 presets Cloud H12 / GER40 / DJ30) | écart EMA/ATR hebdo, vitesse de resserrement, portail, croisement D1, override H12, **machine d'états asymétrique** (suspension, épisode, verrou) | SL ATR D1 × mult, clôture 21:45 | GER40, DJ30 |
| 08 Gold Scalping | `leo_gold_scalping` | pivots fractals 3/3, **première clôture** au-delà d'un pivot non consommé (consommation avant filtre), ADX ≥ 25, SuperTrend H1 (10, ×3), spread, fenêtre 03:00→19:00 | SL 240 / TP 1000 pts, BE +100 (verrou 10), trailing 200 (pas 20), clôture hors fenêtre | XAUUSD |
| SuperSelector | `leo_ss_monday`, `leo_ss_lcrb`, `leo_ss_volshock`, `leo_ss_ldr`, `leo_ss_ibi`, `leo_ss_eef` + `leo_superselector` | les 6 modules de l'EA, un à un ; le sélecteur = premier module qui signale dans l'ordre de l'EA, score ≥ 70 | SL/TP en ATR propres à chaque module ; palier de risque coeur (Monday, 0,35 %) / expérimental (0,15 %) | multi-marchés |

Les algos de la liste d'index sans code fourni (DCA intelligent, Moyenne mobile, AUDCAD commun, `06_…`) **ne sont pas portés**.

## Ce qui est exact, ce qui est approximé, ce qui n'est pas porté

**Exact** (testé) : définition des pivots fractals (stricts, confirmés N barres plus tard ; test contre la définition brute), SuperTrend de l'EA 05
(port littéral comparé sur 24 séries × fenêtres), ATR `iATR` (moyenne simple du true range) vs Wilder amorcé (Cloud/Hybride), Bollinger
à écart-type de population (comme `iBands`), machine d'états Cloud (séquences de référence), horaires en **heure serveur** (Europe/Athens, DST
compris), D1/W1/H12 ancrés sur **minuit serveur** (comme le terminal) et alignés sans fuite (barre utilisée = déjà close), une décision par jour sans
rattrapage, risque par signal (paliers coeur/expérimental), SL/TP/BE/trailing en prix.

**Approximé volontairement** (le moteur est pessimiste ; il prime sur la fidélité d'exécution) :
- un **ordre stop MT5** est approximé par « clôture M15 au-delà du niveau puis exécution à l'ouverture suivante » (jamais de fill intrabar au niveau exact) ; un niveau touché sans clôture au-delà est consommé sans trade (Happy Gold) ;
- le **trailing/BE** est évalué à la clôture de la barre M15 et effectif à la barre suivante (l'EA le fait tick par tick) ; sur un trailing de 20 points (Happy Gold) la différence est grande et défavorable à la simulation ;
- le **filtre de spread moyen échantillonné sur 30 ticks** (Gold Scalping) devient un filtre sur le spread de la barre ; la règle « pivot postérieur à la dernière clôture du même sens » n'est pas appliquée (le moteur interdit déjà deux positions simultanées) ;
- l'échauffement exigé de l'EMA hebdo est de 3× la période lente (l'EA demande 5× et 10×) : l'EMA est alors convergée à moins de 0,3 % ;
- MondayMomentum exige un corps non nul (l'EA vend sur un doji) ; l'ATR des modules est l'ATR M15 `iATR` ; IBI est porté **tel quel** : l'EA ne vérifie pas que la barre précédente est une inside bar.

**RR natif conservé** : Bandito (0,72) et les modules du SuperSelector (≈ 1,7) ont un RR inférieur au plancher de 2,5 du moteur. Ces algos portent
`min_rr_net = 0` : sinon tous leurs trades seraient refusés. Les 9 portes (espérance ≥ +0,3 R, PF > 1,3, coûts ×2, test nul, DSR…) restent les mêmes :
un RR bas doit être compensé par un taux de réussite élevé **et** survivre aux coûts.

**Non porté** (sans objet dans une simulation) : verrous fichier exclusifs et variables globales anti-doublon, refus des comptes réels, reprise sur
historique, vérifications `TRADE_ALLOWED` / `FREEZE_LEVEL` / `STOPS_LEVEL`, reprise de SL manquant. Les garde-fous FTMO du SuperSelector (stop quotidien 3 %,
perte max 8 %, plafond de risque portefeuille 1,25 %) sont assurés par le gardien du moteur (70 % des limites officielles, calculé sur l'équité). La réduction de risque
à −2 %/−6 % du SuperSelector n'est pas reproduite.

## Changements du moteur (comportement existant inchangé par défaut)

Tous les champs sont additifs et neutres par défaut ; `test_engine`, `test_replay`, `test_causality` et la référence publiée sont inchangés.

| ajout | où | rôle |
|---|---|---|
| `ExitCfg.flat_srv_min` / `flat_fri_srv_min` | `algos/base.py`, `engine/sim.py` | clôture forcée à HH:MM **heure serveur** (à la clôture de la barre) ; franchir minuit serveur force aussi la sortie |
| `ExitCfg.px_be_*`, `px_trail_*` | idem | break-even et trailing en **unités de prix** (EA en points/pips), jamais de stop qui recule |
| `Signals.xs` | idem | sortie sur signal d'indicateur (bit 1 = fermer les longs, bit 2 = les shorts), exécutée à l'ouverture suivante |
| `Signals.min_rr_net`, `Signals.risk_mult` | idem | plancher de RR et multiplicateur de risque **par signal** |
| `Market.srv_*_c`, `timeutil.server_clock` | `engine/market.py`, `timeutil.py` | horloge serveur à la clôture de chaque barre (fuseau `SERVER_TZ`, à vérifier par courtier) |
| sortie `native` | `algos/library.py`, `research/wf.py` | un algo `leo_*` porte **ses** sorties ; le catalogue (`fixed3`, `be3`, `trail_atr`…) ne les écrase pas et ne multiplie pas les essais du DSR |
| `AUDCAD` | `instruments.py`, `data/synth.py` | instrument de Bandito (conversion CAD→USD figée à 1,37 `[HYPOTHÈSE]`) |
| `calibrate --algos` | `research/calibrate.py`, `cli.py` | calibration d'un sous-ensemble ; le taux « par test d'algo » n'est plus codé pour 8 algos |

Un bogue réel a été trouvé par la recherche de bout en bout (pas par les tests unitaires) et corrigé : `run_variants` remplaçait la sortie du signal par celle du
catalogue, ce qui supprimait la clôture de session et laissait les positions ouvertes des mois. Test de non-régression : `test_research_path_keeps_native_exits`.

## Hypothèses à vérifier sur votre machine

1. **Heure serveur** : `SERVER_TZ = "Europe/Athens"` (GMT+2/+3, bascule NY). Si votre courtier diffère, changez-le dans `timeutil.py` ; tous les horaires en dépendent.
2. **Unités** : « points » = `Spec.tick` de l'instrument, « pip » = 10 ticks (FX 5 chiffres). À remplacer par `symbol_info` MT5 (`data.loaders.specs_from_mt5`) pour les spécifications réelles.
3. **Historique** : les algos à EMA hebdomadaire (04, 05, 07) n'émettent rien avant ~87 semaines de données (3 × 29) : exigez ≥ 3 ans en `data-check`/`research` ; avec moins de 3 ans le verdict est de toute façon plafonné à WATCH.
4. **Instruments d'origine** : Bandito→AUDCAD, Happy Gold / Gold Scalping→XAUUSD, Cloud→GER40 / US30. Les lancer ailleurs est permis mais hors du périmètre de l'EA.

## Lancer

```bash
# données réelles sur VOTRE machine (terminal MT5 ouvert), puis recherche complète des algos de Leo
python -m ftmo_algo research --mt5 --instruments XAUUSD,AUDCAD,US30,GER40 --start 2020-01-01 --workers 4 \
   --algos leo_range_breakout,leo_bandito,leo_happy_gold,leo_double_croisement,leo_hybride_supertrend,leo_cloud_ema_atr,leo_gold_scalping,leo_superselector
python -m ftmo_algo calibrate --instruments XAUUSD,AUDCAD,US30 --n 20 --algos <mêmes algos>      # taux de faux PASS de CETTE chaîne sur CES algos
python -m ftmo_algo dashboard                                                                    # les algos leo_* sont dans la liste des algos
python -m pytest tests/test_leo_engine.py tests/test_leo_algos.py -q
```
