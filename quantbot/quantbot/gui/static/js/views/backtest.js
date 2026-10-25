/* BACKTESTS : rejeu trade par trade d'une stratégie préenregistrée (recherche ou années d'avant) avec entrée, SL, TP, sortie, zones OB/FVG et R par jour face à l'objectif. */
import { h, clear, num, sgn, pct, pnlClass, price, isNum, epochStamp, reasonLabel } from "../util.js";
import { api } from "../api.js";
import { DataGrid } from "../grid.js";
import { PriceChart } from "../chart.js";

export function mount(root, ctx) {
  const E = ctx.store.bt || (ctx.store.bt = { strategy: "orb", instrument: "USTEC", segment: "recherche", bars: 6000 });
  let ST = null, R = null, detailChart = null, eqChart = null, dayChart = null, grid = null, filter = "all";
  const form = h("div", { class: "bar" }), out = h("div", { class: "stack" });
  const kv = (k, v, c) => [h("span", { class: "k", text: k }), h("span", { class: "v " + (c || ""), text: v })];
  function paintForm() {
    if (!ST) { clear(form).append(h("div", { class: "skel", style: { width: "320px" } })); return; }
    const allowed = E.strategy === "patterns" ? ST.patterns.instruments : (ST.strategies.find((s) => s.id === E.strategy) || { instruments: [] }).instruments;
    if (!allowed.includes(E.instrument)) E.instrument = allowed[0];
    const deep = ST.deep_available && ST.deep_available[E.instrument];
    const sel = (label, key, opts, on) => h("label", { class: "f" }, h("span", { class: "lbl", text: label }), h("select", { onchange: (e) => { E[key] = key === "bars" ? +e.target.value : e.target.value; if (on) on(); } }, ...opts.map(([v, t, dis]) => h("option", { value: v, text: t, selected: String(E[key]) === String(v), disabled: dis }))));
    clear(form).append(sel("Stratégie", "strategy", [...ST.strategies.map((s) => [s.id, s.label]), ["patterns", ST.patterns.label]], paintForm), sel("Instrument", "instrument", allowed.map((i) => [i, i])),
      sel("Période", "segment", [["recherche", "Recherche (récent)"], ["avant", deep ? "Années d'avant" : "Années d'avant (historique profond absent)", !deep]]), sel("Barres", "bars", [[3000, "3 000"], [6000, "6 000"], [12000, "12 000"]]),
      h("button", { class: "btn primary", id: "go", onclick: run }, "Lancer le test"));
  }
  async function run(e) {
    const b = e.target; b.disabled = true; b.textContent = "Calcul…"; clear(out).append(h("div", { class: "panel" }, h("div", { class: "pb" }, h("div", { class: "skel" }), h("div", { class: "skel", style: { width: "60%" } }))));
    try { R = await api(`/api/strategy_replay?instrument=${E.instrument}&bars=${E.bars}&strategy=${E.strategy}&segment=${E.segment}`); show(); } catch (err) { clear(out); }
    b.disabled = false; b.textContent = "Lancer le test";
  }
  function metric(k, v, cls, s) { return h("div", { class: "metric" }, h("div", { class: "k", text: k }), h("div", { class: "v " + (cls || ""), text: v }), h("div", { class: "s", text: s || "" })); }
  function show() {
    for (const c of [detailChart, eqChart, dayChart]) if (c && c.remove) c.remove(); else if (c && c.destroy) c.destroy(); detailChart = eqChart = dayChart = null;
    const m = R.metrics, d = R.daily, rows = R.trades.map((t, i) => ({ ...t, id: i, n: i + 1, date: R.bars.t[Math.max(0, t.i0)] }));
    const reasons = Object.entries(R.reasons);
    const gridCols = [
      { key: "n", label: "#", align: "r", width: "50px" }, { key: "date", label: "Entrée (UTC)", render: (r) => epochStamp(r.date), sortValue: (r) => r.date },
      { key: "side", label: "Sens", render: (r) => h("span", { class: r.side === "long" ? "side-buy" : "side-sell", text: r.side === "long" ? "BUY" : "SELL" }) },
      { key: "entry", label: "Entrée", align: "r", render: (r) => price(r.entry, r.entry) }, { key: "stop", label: "SL", align: "r", render: (r) => price(r.stop, r.entry), cls: () => "dn" },
      { key: "tp", label: "TP", align: "r", render: (r) => price(r.tp, r.entry), cls: () => "up" }, { key: "exit", label: "Sortie", align: "r", render: (r) => price(r.exit, r.entry) },
      { key: "reason", label: "Motif", render: (r) => reasonLabel(r.reason) }, { key: "held", label: "Barres", align: "r" }, { key: "r", label: "R", align: "r", render: (r) => sgn(r.r, 2), cls: (r) => pnlClass(r.r) },
    ];
    grid = new DataGrid({ columns: gridCols, rowKey: (r) => r.id, sort: ["n", 1], onSelect: focusTrade, empty: "Aucun trade sur cette fenêtre." });
    const fl = h("div", { class: "seg" }, ...[["all", "Tous"], ["win", "Gagnants"], ["loss", "Perdants"], ["take_profit", "TP"], ["stop_loss", "SL"]].map(([k, l]) => h("button", { pressed: filter === k, onclick: (e) => { filter = k; fl.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", "false")); e.target.setAttribute("aria-pressed", "true"); grid.setRows(rows.filter(pass)); } }, l)));
    const pass = (r) => filter === "all" || (filter === "win" ? r.r > 0 : filter === "loss" ? r.r <= 0 : r.reason === filter);
    const detailHost = h("div", { class: "pb flush", style: { display: "flex", height: "380px" } }), detailKv = h("div", { class: "kv", style: { padding: "10px" } });
    const eqHost = h("div", { style: { height: "190px" } }), dayHost = h("div", { style: { height: "190px" } });
    clear(out).append(
      h("div", { class: "metrics" }, metric("Trades", String(m.n_trades), "", `${R.label} · ${R.instrument}`), metric("Espérance / trade", sgn(m.expectancy_R, 3) + " R", pnlClass(m.expectancy_R), "R nominal"),
        metric("Profit factor", isNum(m.profit_factor) ? m.profit_factor.toFixed(2) : "—", isNum(m.profit_factor) && m.profit_factor > 1 ? "up" : "dn", `gagnants ${pct(m.win_rate, 0)}`),
        metric("R / jour ouvré", sgn(d.avg_R_per_day, 3), d.avg_R_per_day >= d.target ? "up" : "dn", `objectif ${num(d.target, 2)} · ${pct(d.days_ge_target_pct, 0)} des jours`), metric("Drawdown max", pct(m.max_drawdown, 1), "dn", "capital simulé"),
        metric("Fenêtre", `${R.start.slice(0, 10)}`, "", `→ ${R.end.slice(0, 10)} · ${R.n_bars} barres · achat/conservation ${pct(R.buy_hold_return, 1)}`)),
      h("div", { class: "hint", text: "Une fenêtre courte ne prouve rien. Ce rejeu sert à LIRE les trades ; le jugement vient des portes de validation (onglet Recherche) et de l'échantillon futur." }),
      h("div", { class: "cols", style: { gridTemplateColumns: "minmax(0,1fr) 340px" } },
        h("div", { class: "panel" }, h("div", { class: "ph" }, h("h2", { text: "Détail du trade sélectionné" }), h("span", { class: "sp" }), h("span", { class: "meta", text: R.zones ? "zones OB (plein) + FVG (pointillé)" : "" })), detailHost),
        h("div", { class: "panel" }, h("div", { class: "ph" }, h("h2", { text: "Niveaux du trade" })), detailKv)),
      h("div", { class: "cols", style: { gridTemplateColumns: "minmax(0,1.4fr) minmax(0,1fr)" } },
        h("div", { class: "panel", style: { height: "430px" } }, h("div", { class: "ph" }, h("h2", { text: "Tous les trades" }), fl, h("span", { class: "sp" })), grid.el),
        h("div", { class: "stack" }, h("div", { class: "panel" }, h("div", { class: "ph" }, h("h2", { text: "Motifs de sortie" })), h("div", { class: "pb" }, h("table", { class: "plain" }, h("thead", null, h("tr", null, ...["Motif", "N", "Part", "R moyen", "Gagnants"].map((x, i) => h("th", { class: i ? "r" : "", text: x })))),
          h("tbody", null, reasons.map(([k, v]) => h("tr", null, h("td", { text: reasonLabel(k) }), h("td", { class: "r", text: String(v.n) }), h("td", { class: "r", text: pct(v.n / m.n_trades, 0) }), h("td", { class: "r " + pnlClass(v.mean_R), text: sgn(v.mean_R, 3) }), h("td", { class: "r", text: pct(v.win_rate, 0) })))))),
        h("div", { class: "panel" }, h("div", { class: "ph" }, h("h2", { text: "R par jour vs objectif" })), h("div", { class: "pb flush" }, dayHost)),
        h("div", { class: "panel" }, h("div", { class: "ph" }, h("h2", { text: "Capital simulé" })), h("div", { class: "pb flush" }, eqHost))))));
    grid.setRows(rows); grid.paint(true);
    detailChart = new PriceChart(detailHost, { volume: false }); detailChart.setData(R.bars.t.map((t, i) => ({ time: t, open: R.bars.o[i], high: R.bars.h[i], low: R.bars.l[i], close: R.bars.c[i], volume: 0 }))); detailChart.setZones(R.zones || []);
    const LWC = window.LightweightCharts, base = { autoSize: true, layout: { background: { type: "solid", color: "#0d1015" }, textColor: "#9099a6", fontFamily: "monospace", fontSize: 10, attributionLogo: false }, grid: { vertLines: { color: "#12161c" }, horzLines: { color: "#12161c" } }, rightPriceScale: { borderColor: "#1e242d" }, timeScale: { borderColor: "#1e242d" } };
    eqChart = LWC.createChart(eqHost, base); const area = eqChart.addSeries(LWC.AreaSeries, { lineColor: "#4c8dff", topColor: "rgba(76,141,255,.25)", bottomColor: "rgba(76,141,255,0)", priceLineVisible: false });
    const eq = new Map(R.equity.map(([t, v]) => [Math.floor(Date.parse(String(t).replace(" ", "T") + "Z") / 1000), v])); area.setData([...eq.entries()].sort((a, b) => a[0] - b[0]).map(([time, value]) => ({ time, value }))); eqChart.timeScale().fitContent();
    dayChart = LWC.createChart(dayHost, base); const hist = dayChart.addSeries(LWC.HistogramSeries, { priceLineVisible: false });
    hist.setData(d.series.map(([t, v]) => ({ time: Math.floor(Date.parse(t + "T00:00:00Z") / 1000), value: v, color: v >= 0 ? "#26c281" : "#f0504d" }))); hist.createPriceLine({ price: d.target, color: "#e0a43a", lineWidth: 1, lineStyle: 2, title: "objectif" }); dayChart.timeScale().fitContent();
    function focusTrade(t) {
      const tt = R.bars.t, t0 = tt[Math.max(0, t.i0)], t1 = tt[Math.max(0, t.i1)];
      detailChart.setLevels([{ price: t.tp, color: "#26c281", title: "TP" }, { price: t.stop, color: "#f0504d", title: "SL" }, { price: t.entry, color: "#4c8dff", title: "ENTRÉE", style: 0 }]);
      detailChart.setMarkers([{ time: t0, position: t.side === "long" ? "belowBar" : "aboveBar", color: "#4c8dff", shape: t.side === "long" ? "arrowUp" : "arrowDown", text: t.side === "long" ? "BUY" : "SELL" },
        { time: t1, position: t.side === "long" ? "aboveBar" : "belowBar", color: t.r > 0 ? "#26c281" : "#f0504d", shape: "circle", text: sgn(t.r, 2) + "R · " + reasonLabel(t.reason) }]);
      detailChart.focus(t0, t1);
      const risk = isNum(t.stop) ? Math.abs(t.entry - t.stop) : null, rew = isNum(t.tp) ? Math.abs(t.tp - t.entry) : null;
      clear(detailKv).append(...kv("Trade", `#${t.n} · ${t.side === "long" ? "BUY" : "SELL"}`, t.side === "long" ? "up" : "dn"), ...kv("Entrée", price(t.entry, t.entry) + " · " + epochStamp(t0)), ...kv("Stop (SL)", price(t.stop, t.entry), "dn"),
        ...kv("Risque", risk ? `${price(risk, t.entry)} (${pct(risk / t.entry, 2)})` : "—"), ...kv("Objectif (TP)", price(t.tp, t.entry), "up"), ...kv("Gain visé", rew && risk ? (rew / risk).toFixed(2) + " R" : "—"),
        ...kv("Sortie", price(t.exit, t.entry) + " · " + epochStamp(t1)), ...kv("Motif", reasonLabel(t.reason)), ...kv("Durée", `${t.held} barres`), ...kv("Résultat", sgn(t.r, 2) + " R · PnL " + sgn(t.pnl, 2), pnlClass(t.r)));
    }
    if (rows.length) grid.select(0);
  }
  root.append(h("div", { class: "stack" }, h("div", { class: "panel" }, h("div", { class: "ph" }, h("h2", { text: "Banc d'essai des stratégies" }), h("span", { class: "sp" }), h("span", { class: "meta", text: "recherche / années d'avant uniquement — la période verrouillée n'est jamais renvoyée" })), h("div", { class: "pb" }, form)), out));
  paintForm(); api("/api/strategies", { quiet: true }).then((x) => { ST = x; paintForm(); }).catch(() => {});
  if (R) show();
  return () => { for (const c of [detailChart, eqChart, dayChart]) { try { c && (c.remove ? c.remove() : c.destroy()); } catch (e) { /* déjà détruit */ } } };
}
