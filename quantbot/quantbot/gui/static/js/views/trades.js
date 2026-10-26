/* LIVE TRADES & STRATEGY ATTRIBUTION : métriques globales, filtres, grille de données, attribution par stratégie et PnL cumulé par stratégie. */
import { h, clear, num, sgn, pct, pnlClass, price, utcMs, barTime, badge, isNum } from "../util.js";
import { api, poller } from "../api.js";
import { DataGrid } from "../grid.js";

const PALETTE = ["#4c8dff", "#e0a43a", "#2ec4d6", "#9b7bf0", "#26c281", "#f0504d", "#d07fcf", "#8bb3ff"];
export function mount(root, ctx) {
  const F = { strategies: new Set(), status: "ALL", symbol: "ALL", period: ctx.store.period || "session", q: "" };
  let book = null, cum = null, stopPoll = null;
  const metrics = h("div", { class: "metrics" });
  const chips = h("div", { class: "bar" });
  const statusSeg = h("div", { class: "seg", role: "group", "aria-label": "Statut" });
  const periodSeg = h("div", { class: "seg", role: "group", "aria-label": "Période" });
  const symSel = h("select", { "aria-label": "Actif", onchange: () => { F.symbol = symSel.value; apply(); } });
  const search = h("input", { type: "search", placeholder: "Filtrer : stratégie, actif, statut…", "aria-label": "Recherche", oninput: () => { F.q = search.value.trim().toLowerCase(); apply(); } });
  const count = h("span", { class: "meta mono" });

  const cols = [
    { key: "status", label: "Statut", render: (r) => badge(r.status), sortValue: (r) => r.status, width: "86px" },
    { key: "recorded_ms", label: "Enregistré (UTC)", render: (r) => utcMs(r.recorded_ms), title: "Horloge du programme à l'enregistrement, en millisecondes" },
    { key: "symbol", label: "Actif", render: (r) => r.symbol, cls: () => "strat" },
    { key: "side", label: "Sens", render: (r) => h("span", { class: r.side === "long" ? "side-buy" : "side-sell", text: r.side === "long" ? "BUY" : "SELL" }) },
    { key: "entry", label: "Entrée", align: "r", render: (r) => price(r.entry, r.entry) },
    { key: "size", label: "Taille", align: "r", render: (r) => (isNum(r.size) ? num(r.size, r.size < 10 ? 3 : 1) : "—") },
    { key: "sl", label: "SL", align: "r", render: (r) => price(r.sl, r.entry), cls: () => "dn" },
    { key: "tp", label: "TP", align: "r", render: (r) => price(r.tp, r.entry), cls: () => "up" },
    { key: "exit", label: "Dernier / sortie", align: "r", render: (r) => price(r.exit, r.entry) },
    { key: "pnl", label: "PnL", align: "r", render: (r) => sgn(r.pnl, 2), cls: (r) => pnlClass(r.pnl), title: "PnL instantané pour une position ouverte (dernière clôture publiée), réalisé sinon" },
    { key: "r", label: "R", align: "r", render: (r) => sgn(r.r, 2), cls: (r) => pnlClass(r.r) },
    { key: "strategy_code", label: "Stratégie source", render: (r) => r.strategy_code, cls: () => "strat" },
    { key: "source", label: "Source", render: (r) => r.source + (r.paper ? " · PAPER" : " · RÉEL"), cls: () => "dim" },
  ];
  const grid = new DataGrid({ columns: cols, rowKey: (r) => r.id, sort: ["recorded_ms", -1], empty: "Aucun trade. Lancez la simulation (scripts/paper_all.py) pendant une séance de marché.", onSelect: (r) => { ctx.store.selectedTrade = r; detail(r); } });
  const attr = h("div"); const cumBox = h("div", { style: { height: "230px", position: "relative" } }); const det = h("div", { class: "kv" });
  let cumChart = null, cumSeries = [];

  function filtered() {
    if (!book) return [];
    return book.rows.filter((r) => (!F.strategies.size || F.strategies.has(r.strategy_code)) && (F.symbol === "ALL" || r.symbol === F.symbol)
      && (F.status === "ALL" || (F.status === "OPEN" ? r.open : F.status === "TIME" ? ["TEMPS", "WEEK-END", "TROU DONNÉES", "RISQUE ACTIF", "FIN"].includes(r.status) : r.status === F.status))
      && (!F.q || `${r.strategy_code} ${r.symbol} ${r.status} ${r.side} ${r.source}`.toLowerCase().includes(F.q)));
  }
  function apply() { const rows = filtered(); grid.setRows(rows); count.textContent = `${rows.length} / ${book ? book.rows.length : 0}`; if (ctx.store.selectedTrade) grid.sel = ctx.store.selectedTrade.id; paintChips(); }
  function paintMetrics() {
    const m = book.metrics, cap = m.capital;
    clear(metrics).append(
      metric("PnL total (session)", sgn(m.pnl_total, 2), pnlClass(m.pnl_total), `réalisé ${sgn(m.pnl_realized, 2)} · latent ${sgn(m.pnl_unrealized, 2)} · ${sgn(m.r_total, 2)} R`),
      metric("Drawdown en cours", m.drawdown_money > 0 ? "−" + num(m.drawdown_money, 2) : "0.00", m.drawdown_money > 0 ? "dn" : "mute", pct(m.drawdown_pct, 2) + " du capital simulé " + num(cap, 0)),
      metric("Winrate global", m.win_rate == null ? "—" : pct(m.win_rate, 1), m.win_rate == null ? "mute" : m.wr_edge == null ? "amb" : m.wr_edge > 0 ? "up" : "dn", m.breakeven_wr == null ? `${m.n_closed} trades clos` : `seuil d'équilibre ${pct(m.breakeven_wr, 0)} (R:R réalisé ${m.realised_rr.toFixed(2)}) · ${m.n_closed} clos`),
      metric("Sharpe (annualisé)", m.sharpe == null ? "n/a" : m.sharpe.toFixed(2), m.sharpe == null ? "mute" : pnlClass(m.sharpe), m.sharpe == null ? `${m.sharpe_days} j ouvrés < 20 : non significatif` : `${m.sharpe_days} jours ouvrés`),
      metric("Positions ouvertes", String(m.n_open), m.n_open ? "acc" : "mute", "en simulation PAPER"),
      metric("R moyen / trade", m.avg_r == null ? "—" : sgn(m.avg_r, 3), pnlClass(m.avg_r), "R nominal"));
  }
  const metric = (k, v, cls, s) => h("div", { class: "metric" }, h("div", { class: "k", text: k }), h("div", { class: "v " + cls, text: v }), h("div", { class: "s", text: s }));
  function paintChips() {
    if (!book) return; clear(chips);
    for (const s of book.by_strategy) chips.append(h("button", { class: "chip", pressed: F.strategies.has(s.strategy_code), title: "Filtrer par stratégie", onclick: () => { F.strategies.has(s.strategy_code) ? F.strategies.delete(s.strategy_code) : F.strategies.add(s.strategy_code); apply(); } },
      s.strategy_code, h("span", { class: "n", text: String(s.n + s.open) })));
    if (F.strategies.size) chips.append(h("button", { class: "btn", onclick: () => { F.strategies.clear(); apply(); } }, "Tout afficher"));
  }
  function paintSegs() {
    clear(statusSeg).append(...[["ALL", "Tous"], ["OPEN", "Ouverts"], ["TP", "TP"], ["SL", "SL"], ["TIME", "Temps / autre"]].map(([k, l]) => h("button", { pressed: F.status === k, onclick: () => { F.status = k; paintSegs(); apply(); } }, l)));
    clear(periodSeg).append(...[["session", "Session"], ["today", "Aujourd'hui"], ["all", "Tout"]].map(([k, l]) => h("button", { pressed: F.period === k, onclick: () => { F.period = k; ctx.store.period = k; paintSegs(); load(); } }, l)));
  }
  function paintAttribution() {
    const rows = book.by_strategy, maxAbs = Math.max(1e-9, ...rows.map((r) => Math.abs(r.pnl)));
    clear(attr).append(h("table", { class: "plain" }, h("thead", null, h("tr", null, ...["Stratégie", "N", "Win%", "Seuil%", "R", "PnL", ""].map((x, i) => h("th", { class: i && i < 6 ? "r" : "", text: x })))),
      h("tbody", null, rows.length ? rows.map((r, i) => h("tr", { style: { cursor: "pointer" }, onclick: () => { F.strategies.clear(); F.strategies.add(r.strategy_code); apply(); } },
        h("td", null, h("span", { style: { color: PALETTE[i % PALETTE.length] }, text: "■ " }), r.strategy_code), h("td", { class: "r", text: String(r.n + r.open) }), h("td", { class: "r", text: r.win_rate == null ? "—" : pct(r.win_rate, 0) }), h("td", { class: "r " + (r.wr_edge == null ? "dim" : r.wr_edge > 0 ? "up" : "dn"), title: "Taux de réussite d'équilibre = 1/(1+R:R réalisé)", text: r.breakeven_wr == null ? "—" : pct(r.breakeven_wr, 0) }),
        h("td", { class: "r " + pnlClass(r.r), text: sgn(r.r, 2) }), h("td", { class: "r " + pnlClass(r.pnl), text: sgn(r.pnl, 0) }),
        h("td", { style: { width: "60px" } }, h("div", { class: "gauge " + (r.pnl >= 0 ? "good" : "bad") }, h("i", { style: { width: Math.round(Math.abs(r.pnl) / maxAbs * 100) + "%" } }))))) : [h("tr", null, h("td", { colspan: 7, class: "dim", text: "Aucune attribution tant qu'aucun trade n'existe." }))])));
  }
  function paintCum() {
    if (!window.LightweightCharts) return;
    if (!cumChart) {
      cumChart = window.LightweightCharts.createChart(cumBox, { autoSize: true, layout: { background: { type: "solid", color: "#0d1015" }, textColor: "#9099a6", fontFamily: "monospace", fontSize: 10, attributionLogo: false },
        grid: { vertLines: { color: "#12161c" }, horzLines: { color: "#12161c" } }, rightPriceScale: { borderColor: "#1e242d" }, timeScale: { borderColor: "#1e242d", timeVisible: true } });
    }
    for (const s of cumSeries) cumChart.removeSeries(s); cumSeries = [];
    book.curve.forEach((c, i) => {
      if (!c.points.length) return;
      const pts = new Map(); for (const [t, v] of c.points) pts.set(Math.floor(Date.parse(String(t).replace(" ", "T") + "Z") / 1000), v);
      const data = [...pts.entries()].sort((a, b) => a[0] - b[0]).map(([time, value]) => ({ time, value }));
      const ser = cumChart.addSeries(window.LightweightCharts.LineSeries, { color: c.strategy_code === "TOTAL" ? "#d4dae2" : PALETTE[(i - 1 + PALETTE.length) % PALETTE.length], lineWidth: c.strategy_code === "TOTAL" ? 2 : 1, title: c.strategy_code === "TOTAL" ? "TOTAL" : "", priceLineVisible: false });
      ser.setData(data); cumSeries.push(ser);
    });
    cumChart.timeScale().fitContent();
  }
  function detail(r) {
    clear(det);
    if (!r) { det.append(h("span", { class: "dim", text: "Sélectionnez un trade." })); return; }
    const kv = (k, v, cls) => [h("span", { class: "k", text: k }), h("span", { class: "v " + (cls || ""), text: v })];
    det.append(...kv("Identifiant", r.id), ...kv("Stratégie", r.strategy_code, "strat"), ...kv("Actif", r.symbol), ...kv("Sens", r.side === "long" ? "BUY" : "SELL", r.side === "long" ? "up" : "dn"),
      ...kv("Barre d'entrée", barTime(r.entry_time)), ...kv("Barre de sortie", r.exit_time ? barTime(r.exit_time) : "—"), ...kv("Enregistré", utcMs(r.recorded_ms)), ...kv("Prix d'entrée", price(r.entry, r.entry)),
      ...kv("Stop (SL)", price(r.sl, r.entry), "dn"), ...kv("Objectif (TP)", price(r.tp, r.entry), "up"), ...kv("Sortie / dernier", price(r.exit, r.entry)), ...kv("Taille", isNum(r.size) ? String(r.size.toFixed(4)) : "—"),
      ...kv("PnL", sgn(r.pnl, 2), pnlClass(r.pnl)), ...kv("R", sgn(r.r, 3), pnlClass(r.r)), ...kv("Motif", r.reason || "position ouverte"), ...kv("Mode", r.paper ? "PAPER (exécution simulée)" : "RÉEL"),
      h("button", { class: "btn", style: { gridColumn: "1 / -1", marginTop: "6px" }, onclick: () => ctx.go("marche", { runner: r.runner }) }, "Voir sur le graphique"));
  }
  async function load() { try { book = await api(`/api/book?period=${F.period}`, { quiet: true }); } catch (e) { return; }
    const syms = [...new Set(book.rows.map((r) => r.symbol).filter(Boolean))].sort(); const cur = symSel.value || "ALL";
    clear(symSel).append(h("option", { value: "ALL", text: "Tous les actifs" }), ...syms.map((s) => h("option", { value: s, text: s })));
    symSel.value = syms.includes(cur) ? cur : "ALL"; F.symbol = symSel.value;
    paintMetrics(); paintAttribution(); paintCum(); apply(); ctx.setStatus(`${book.rows.length} lignes · ${book.runners.length} lanceurs`); }

  paintSegs();
  root.append(h("div", { class: "stack", style: { height: "100%" } }, metrics,
    h("div", { class: "panel" }, h("div", { class: "ph" }, h("h2", { text: "Live trades & strategy attribution" }), h("span", { class: "sp" }), count),
      h("div", { class: "pb", style: { flex: "none", display: "flex", flexDirection: "column", gap: "8px" } }, h("div", { class: "bar" }, statusSeg, periodSeg, symSel, search), chips)),
    h("div", { class: "cols", style: { gridTemplateColumns: "minmax(0,1fr) 380px", flex: 1, minHeight: 0 } },
      h("div", { class: "panel", style: { minHeight: "320px" } }, h("div", { class: "ph" }, h("h2", { text: "Grille des trades" }), h("span", { class: "sp" }), h("span", { class: "meta", text: "tri : clic sur l'en-tête · ↑↓ pour naviguer" })), grid.el),
      h("div", { class: "stack", style: { overflow: "auto" } },
        h("div", { class: "panel" }, h("div", { class: "ph" }, h("h2", { text: "Attribution par stratégie" })), h("div", { class: "pb" }, attr)),
        h("div", { class: "panel" }, h("div", { class: "ph" }, h("h2", { text: "PnL cumulé réalisé" }), h("span", { class: "sp" }), h("span", { class: "meta", text: "par stratégie · total en blanc" })), h("div", { class: "pb flush" }, cumBox)),
        h("div", { class: "panel" }, h("div", { class: "ph" }, h("h2", { text: "Trade sélectionné" })), h("div", { class: "pb" }, det)))),
    h("div", { class: "note" }, "PAPER : prix réels, exécutions et PnL simulés. « Enregistré » = horloge du programme (ms) ; les heures d'entrée/sortie sont celles des barres (décision à la clôture, exécution à l'ouverture suivante). Un petit nombre de trades ne prouve rien.")));
  detail(null);
  stopPoll = poller(load, 2500);
  return () => { stopPoll && stopPoll(); if (cumChart) cumChart.remove(); };
}
