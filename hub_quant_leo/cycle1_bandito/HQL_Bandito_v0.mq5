//+------------------------------------------------------------------+
//| HQL_Bandito_v0.mq5 - Hub Quant Leo, cycle 1 (reference)          |
//| Reconstruction depuis BILAN_DE_CLAUDE.md (regles du code         |
//| original). Non compile ici : a compiler avec F5 dans MetaEditor. |
//| Ecarts voulus vs l'original : risque % (au lieu du lot fixe) et  |
//| journal CSV des deals. Aucune optimisation dans cette version.   |
//+------------------------------------------------------------------+
#property strict
#property version "0.10"
#include <Trade/Trade.mqh>

input group "Signal (Bollinger entree / sortie)"
input int             InpBBPeriod       = 20;
input double          InpBBDevEntry     = 2.0;
input double          InpBBDevExit      = 2.0;
input int             InpExitMAPeriod   = 50;
input ENUM_MA_METHOD  InpExitMAMethod   = MODE_SMA;
input group "Gestion de la position (pips)"
input double          InpRiskPct        = 0.60;   // % du solde risque par trade (distance = SL)
input double          InpSLPips         = 180;
input double          InpTPPips         = 130;
input double          InpTrailStartPips = 10;
input double          InpTrailDistPips  = 180;
input double          InpForceClosePips = 1000;   // fermeture forcee a +/- N pips
input double          InpMaxSpreadPips  = 3;
input int             InpMaxPosPerDir   = 1;
input group "Technique"
input ulong           InpMagic          = 20260201;
input bool            InpLogTrades      = true;   // ecrit HQL_Bandito_deals.csv (dossier Common\Files)

CTrade trade;
int hBBEntry = INVALID_HANDLE, hBBExit = INVALID_HANDLE, hMAExit = INVALID_HANDLE;
datetime lastBar = 0;
double pip = 0;

//+------------------------------------------------------------------+
int OnInit()
  {
   pip = (_Digits == 3 || _Digits == 5) ? _Point * 10.0 : _Point;
   hBBEntry = iBands(_Symbol, PERIOD_CURRENT, InpBBPeriod, 0, InpBBDevEntry, PRICE_CLOSE);
   hBBExit  = iBands(_Symbol, PERIOD_CURRENT, InpBBPeriod, 0, InpBBDevExit,  PRICE_CLOSE);
   hMAExit  = iMA(_Symbol, PERIOD_CURRENT, InpExitMAPeriod, 0, InpExitMAMethod, PRICE_CLOSE);
   if(hBBEntry == INVALID_HANDLE || hBBExit == INVALID_HANDLE || hMAExit == INVALID_HANDLE)
     { Print("Erreur creation indicateurs"); return INIT_FAILED; }
   if(AccountInfoInteger(ACCOUNT_MARGIN_MODE) != ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
      Print("ATTENTION : compte non hedging, une seule position par symbole.");
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(20);
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   IndicatorRelease(hBBEntry); IndicatorRelease(hBBExit); IndicatorRelease(hMAExit);
  }

//+------------------------------------------------------------------+
bool Get(int handle, int buffer, int shift, double &v)
  {
   double b[1];
   if(CopyBuffer(handle, buffer, shift, 1, b) != 1) return false;
   v = b[0];
   return true;
  }

int CountPos(ENUM_POSITION_TYPE type)
  {
   int n = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t == 0 || !PositionSelectByTicket(t)) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol || PositionGetInteger(POSITION_MAGIC) != (long)InpMagic) continue;
      if(PositionGetInteger(POSITION_TYPE) == type) n++;
     }
   return n;
  }

double LotForRisk(ENUM_ORDER_TYPE type, double price, double sl)
  {
   double loss = 0;
   if(!OrderCalcProfit(type, _Symbol, 1.0, price, sl, loss) || loss >= 0) return 0;
   double riskMoney = AccountInfoDouble(ACCOUNT_BALANCE) * InpRiskPct / 100.0;
   double lots = riskMoney / MathAbs(loss);
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   lots = MathFloor(lots / step) * step;
   if(lots < vmin) return 0;          // risque minimal > risque voulu : pas de trade
   return MathMin(lots, vmax);
  }

//+------------------------------------------------------------------+
void ManagePositions(double c1, double exitUp, double exitLo, double maExit)
  {
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t == 0 || !PositionSelectByTicket(t)) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol || PositionGetInteger(POSITION_MAGIC) != (long)InpMagic) continue;
      bool   isBuy = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY);
      double open  = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl    = PositionGetDouble(POSITION_SL);
      double tp    = PositionGetDouble(POSITION_TP);
      double pnlPips = (isBuy ? bid - open : open - ask) / pip;

      // 1) fermeture forcee +/- N pips
      if(MathAbs(pnlPips) >= InpForceClosePips) { trade.PositionClose(t); continue; }
      // 2) sortie sur cloture au-dela de la bande de sortie OU de la MM de sortie
      bool exitSig = isBuy ? (c1 > exitUp || c1 > maExit) : (c1 < exitLo || c1 < maExit);
      if(exitSig) { trade.PositionClose(t); continue; }
      // 3) trailing (evalue a la nouvelle barre, comme la source)
      if(pnlPips >= InpTrailStartPips)
        {
         double newSL = isBuy ? bid - InpTrailDistPips * pip : ask + InpTrailDistPips * pip;
         newSL = NormalizeDouble(newSL, _Digits);
         bool better = isBuy ? (newSL > sl + _Point) : (sl == 0 || newSL < sl - _Point);
         if(better) trade.PositionModify(t, newSL, tp);
        }
     }
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   datetime bar = iTime(_Symbol, PERIOD_CURRENT, 0);
   if(bar == lastBar) return;          // une decision par barre, sur bougies cloturees
   lastBar = bar;

   double c1 = iClose(_Symbol, PERIOD_CURRENT, 1), c2 = iClose(_Symbol, PERIOD_CURRENT, 2);
   double up1, lo1, up2, lo2, xUp1, xLo1, ma1;
   if(!Get(hBBEntry, 1, 1, up1) || !Get(hBBEntry, 2, 1, lo1) ||
      !Get(hBBEntry, 1, 2, up2) || !Get(hBBEntry, 2, 2, lo2) ||
      !Get(hBBExit, 1, 1, xUp1) || !Get(hBBExit, 2, 1, xLo1) || !Get(hMAExit, 0, 1, ma1)) return;

   ManagePositions(c1, xUp1, xLo1, ma1);

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK), bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   if((ask - bid) / pip > InpMaxSpreadPips) return;

   bool buySig  = (c1 < lo1 && c2 >= lo2);   // cloture sous la bande basse, precedente au-dessus
   bool sellSig = (c1 > up1 && c2 <= up2);

   if(buySig && CountPos(POSITION_TYPE_BUY) < InpMaxPosPerDir)
     {
      double sl = NormalizeDouble(ask - InpSLPips * pip, _Digits);
      double tp = NormalizeDouble(ask + InpTPPips * pip, _Digits);
      double lots = LotForRisk(ORDER_TYPE_BUY, ask, sl);
      if(lots > 0) trade.Buy(lots, _Symbol, ask, sl, tp, "HQL_Bandito");
     }
   if(sellSig && CountPos(POSITION_TYPE_SELL) < InpMaxPosPerDir)
     {
      double sl = NormalizeDouble(bid + InpSLPips * pip, _Digits);
      double tp = NormalizeDouble(bid - InpTPPips * pip, _Digits);
      double lots = LotForRisk(ORDER_TYPE_SELL, bid, sl);
      if(lots > 0) trade.Sell(lots, _Symbol, bid, sl, tp, "HQL_Bandito");
     }
  }

//+------------------------------------------------------------------+
//| Journal CSV : une ligne par deal (entree et sortie)              |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &tr, const MqlTradeRequest &rq, const MqlTradeResult &rs)
  {
   if(!InpLogTrades || tr.type != TRADE_TRANSACTION_DEAL_ADD) return;
   if(!HistoryDealSelect(tr.deal)) return;
   if(HistoryDealGetInteger(tr.deal, DEAL_MAGIC) != (long)InpMagic) return;
   int h = FileOpen("HQL_Bandito_deals.csv", FILE_READ|FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON, ';');
   if(h == INVALID_HANDLE) return;
   if(FileSize(h) == 0)
      FileWrite(h, "time", "deal", "position", "symbol", "type", "entry", "volume", "price", "sl", "tp",
                "profit", "commission", "swap", "reason", "balance");
   FileSeek(h, 0, SEEK_END);
   FileWrite(h,
      TimeToString((datetime)HistoryDealGetInteger(tr.deal, DEAL_TIME), TIME_DATE|TIME_SECONDS),
      (long)tr.deal, HistoryDealGetInteger(tr.deal, DEAL_POSITION_ID),
      HistoryDealGetString(tr.deal, DEAL_SYMBOL),
      HistoryDealGetInteger(tr.deal, DEAL_TYPE), HistoryDealGetInteger(tr.deal, DEAL_ENTRY),
      DoubleToString(HistoryDealGetDouble(tr.deal, DEAL_VOLUME), 2),
      DoubleToString(HistoryDealGetDouble(tr.deal, DEAL_PRICE), _Digits),
      DoubleToString(HistoryDealGetDouble(tr.deal, DEAL_SL), _Digits),
      DoubleToString(HistoryDealGetDouble(tr.deal, DEAL_TP), _Digits),
      DoubleToString(HistoryDealGetDouble(tr.deal, DEAL_PROFIT), 2),
      DoubleToString(HistoryDealGetDouble(tr.deal, DEAL_COMMISSION), 2),
      DoubleToString(HistoryDealGetDouble(tr.deal, DEAL_SWAP), 2),
      HistoryDealGetInteger(tr.deal, DEAL_REASON),
      DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE), 2));
   FileClose(h);
  }
//+------------------------------------------------------------------+
