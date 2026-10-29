"""Catalogue des 60 stratégies quantitatives institutionnelles (liste fournie par l'utilisateur) : état RÉEL de chacune dans quantbot.

Statuts :
  CODEE    : un module exécutable existe et tourne en simulation PAPER (le verdict de recherche, s'il existe, est dans le catalogue des stratégies) ;
  COUVERTE : partiellement couverte par un module existant (différence indiquée) ;
  OUTIL    : outil de recherche écrit et testé, pas de stratégie exécutée ;
  DONNEES  : exige des données que quantbot ne possède pas (colonne « données ») : aucune stratégie n'est simulée, rien n'est inventé ;
  HORS_PORTEE : exige une infrastructure ou des droits d'accès incompatibles avec un compte de détail CFD.
Aucune de ces 60 approches n'est VALIDÉE : 118/120 essais consommés, 0 PASS.
"""
from __future__ import annotations

from pathlib import Path

from ..strategies.external_data import missing

C, V, O, D, H = "CODEE", "COUVERTE", "OUTIL", "DONNEES", "HORS_PORTEE"
# (n, nom, famille, statut, module quantbot, données / raison)
S60 = [
    (1, "Value", "Actions", D, None, "constituants d'indices + états financiers datés (publication initiale)"),
    (2, "Quality / rentabilité", "Actions", D, None, "états financiers historiques datés"),
    (3, "Investissement prudent", "Actions", D, None, "actifs et investissements par société, datés"),
    (4, "Faible bêta / BAB", "Actions", D, None, "rendements de TOUS les constituants (anciens inclus) + financement"),
    (5, "Prime de taille", "Actions", D, None, "capitalisations et constituants historiques"),
    (6, "Momentum transversal", "Actions", D, None, "rendements des constituants (anciens inclus)"),
    (7, "Réversion courte", "Actions", D, None, "rendements journaliers des constituants + facteurs marché/secteur"),
    (8, "Révisions bénéficiaires", "Actions", D, None, "consensus d'analystes horodaté"),
    (9, "PEAD (dérive après résultats)", "Actions", D, None, "surprises de bénéfices historiques horodatées"),
    (10, "Alpha fondamental / données alternatives", "Actions", D, None, "données alternatives autorisées (transactions, fréquentation, textes)"),
    (11, "Momentum temporel / CTA", "Tendance", V, "cta_donchian", "tendance D1 + canal H4 sur or ; pas le panier multi-classes de futures"),
    (12, "Cassure de canal", "Tendance", V, "cta_donchian", "canal 20 barres H4 (le canal 55 ne donnait que 90 événements)"),
    (13, "Opening Range Breakout", "Intrajournalier", C, "orb", "barres M15 ; verdict de recherche : voir inst_strategies_v1"),
    (14, "Momentum intrajournalier", "Intrajournalier", C, "intraday_momentum", "barres M15 des indices (10:00 NY -> 15:30 NY)"),
    (15, "Réversion vers le VWAP", "Intrajournalier", C, "vwap", "barres M15 + volume en ticks"),
    (16, "Prime overnight", "Intrajournalier", C, "overnight_premium", "barres M15 des indices ; surtout du bêta haussier"),
    (17, "Paires par cointégration", "Arbitrage statistique", O, "stat/pairs.py", "écrite et préenregistrée (pairs_v1), exécution = 1 essai, données Coinbase BTC/ETH requises"),
    (18, "Arbitrage statistique PCA", "Arbitrage statistique", D, None, "univers d'actions complet"),
    (19, "Valeur relative entre indices", "Arbitrage statistique", O, "stat/pairs.py", "USTEC/US500/US30/DE40 disponibles : un test de spread = 1 essai à dépenser ; exécution sur deux jambes non gérée par le moteur"),
    (20, "Arbitrage ETF-panier", "Arbitrage statistique", H, None, "accès participant autorisé (création/rachat)"),
    (21, "Arbitrage cash-future d'indice", "Arbitrage statistique", D, None, "panier de l'indice, dividendes, financement"),
    (22, "Actions doublement cotées", "Arbitrage statistique", D, None, "cours multi-places synchronisés + droits économiques"),
    (23, "Décote des fonds fermés", "Arbitrage statistique", D, None, "valeurs liquidatives et portefeuilles des fonds"),
    (24, "FX carry", "Devises et taux", D, None, "taux d'intérêt / forwards (les swaps du courtier sont lisibles dans MT5 mais non collectés)"),
    (25, "FX value (PPP)", "Devises et taux", D, None, "taux de change réels et inflation relative"),
    (26, "Base cross-currency", "Devises et taux", D, None, "swaps et financement multi-devises, collatéral"),
    (27, "Carry et rolldown obligataire", "Devises et taux", D, None, "courbes de taux, financement, futures obligataires"),
    (28, "Courbe de taux / butterfly", "Devises et taux", D, None, "futures ou swaps de taux 2-5-10 ans"),
    (29, "Valeur relative entre souverains", "Devises et taux", D, None, "rendements souverains + couvertures"),
    (30, "Base Treasury cash-future", "Devises et taux", D, None, "obligations livrables, repo, futures Treasury"),
    (31, "Swap spread", "Devises et taux", D, None, "swaps SOFR/€STR/SONIA + souverains"),
    (32, "Inflation breakeven", "Devises et taux", V, "macro_tips", "taux réels FRED (DFII10) : la clé FRED gratuite doit être fournie ; pas les swaps d'inflation"),
    (33, "Crédit relatif", "Devises et taux", D, None, "spreads d'obligations et indices CDS"),
    (34, "Base obligation-CDS", "Devises et taux", D, None, "obligations et CDS du même émetteur"),
    (35, "MBS relative value", "Devises et taux", D, None, "titres MBS + modèle de remboursement anticipé"),
    (36, "Commodity carry", "Matières premières", D, None, "courbes de futures multi-échéances"),
    (37, "Calendar spreads", "Matières premières", D, None, "futures à plusieurs échéances"),
    (38, "Crack / crush / spark spreads", "Matières premières", D, None, "prix des intrants et produits transformés"),
    (39, "Arbitrage physique / géographique", "Matières premières", H, None, "accès physique, transport, stockage"),
    (40, "Prévision stocks-météo-production", "Matières premières", D, None, "données météo, stocks et production"),
    (41, "Surprises macroéconomiques", "Matières premières", D, None, "consensus ET première publication horodatés (le calendrier seul ne suffit pas)"),
    (42, "Positionnement COT", "Matières premières", C, "cot_extremes", "data/external/cot_gold.csv (historique 156 semaines)"),
    (43, "Prime de variance", "Options et volatilité", O, "stat/vol_arb.py", "chaîne d'options RÉELLE (bid/ask) : absente"),
    (44, "Long volatilité conditionnelle", "Options et volatilité", D, None, "surface d'options"),
    (45, "Skew relative value", "Options et volatilité", D, None, "surface d'options"),
    (46, "Structure par terme de volatilité", "Options et volatilité", D, None, "options multi-échéances"),
    (47, "Dispersion / corrélation", "Options et volatilité", D, None, "options indice + constituants"),
    (48, "Volatilité d'événement", "Options et volatilité", D, None, "options autour des événements"),
    (49, "Parité put-call / boxes", "Options et volatilité", D, None, "cotations d'options simultanées"),
    (50, "Arbitrage de convertibles", "Options et volatilité", D, None, "obligations convertibles + prêt de titres"),
    (51, "Order Flow Imbalance / micro-prix", "Microstructure", C, "ofi_depth", "carnet réel (data/live/depth) : MetaQuotes-Demo n'en fournit pas (carnet vide)"),
    (52, "Market making avec inventaire", "Microstructure", O, "stat/avellaneda.py", "borne optimiste ; quantbot est preneur de liquidité"),
    (53, "Déséquilibres d'enchères", "Microstructure", D, None, "messages d'imbalance des bourses"),
    (54, "Arbitrage interplaces / triangulaire", "Microstructure", H, None, "latence microseconde, capitaux prépositionnés"),
    (55, "Lead-lag entre marchés liés", "Microstructure", O, "intermarket_telemetry", "testé : aucun décalage exploitable EURUSD->or à 15 min"),
    (56, "Cash-and-carry crypto daté", "Crypto et événements", D, None, "futures datés BTC/ETH"),
    (57, "Funding des perpétuels", "Crypto et événements", D, None, "taux de financement des perpétuels"),
    (58, "Fourniture de liquidité AMM", "Crypto et événements", H, None, "contrats intelligents, accès on-chain"),
    (59, "Arbitrage de fusion", "Crypto et événements", D, None, "opérations de fusion + cours cible/acquéreur"),
    (60, "Rebalancements et changements d'indices", "Crypto et événements", D, None, "annonces officielles des fournisseurs d'indices"),
]


def institutional60(root: Path) -> dict:
    rows = []
    for n, name, fam, status, module, note in S60:
        miss = missing(module, root) if (module and status in (C, V)) else []
        rows.append({"n": n, "name": name, "family": fam, "status": status, "module": module, "note": note, "data_missing": miss})
    cnt: dict = {}
    for r in rows:
        cnt[r["status"]] = cnt.get(r["status"], 0) + 1
    return {"rows": rows, "counts": cnt, "note": "Aucune des 60 n'est validée. « Codée » veut dire : écrite, testée, tournant en simulation PAPER (si ses données existent)."}
