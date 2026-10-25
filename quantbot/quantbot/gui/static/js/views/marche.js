/* MARCHÉ : graphique temps réel (bougies clôturées), zones Order Block / FVG, position (entrée, SL, TP), état du contrôle de risque et positions ouvertes. */
import { h, clear, num, sgn, pct, pnlClass, price, isNum, barTime, ago } from "../util.js";
import { api, poller } from "../api.js";
import { PriceChart, tradeMarkers } from "../chart.js";

export function mount(root, ctx, opts = {}) {
  let runner = opts.runner || ctx.store.runner || null, chart = null, stop = null, first = true;
  const sel = h("select", { "aria-label": "Simulation", onchange: () => { runner = sel.value; ctx.store.runner = runner; first = true; load(); } });
  const flags = { zones: true, trades: true };
  const side = h("div", { class: "stack" }), list = h("div"), riskBox = h("div");
  const title = h("span", { class: "meta mono" });
  const chartHost = h("div", { class: "pb flush", style: { display: "flex", minHeight: "420px" } });
  const toggles = h("div", { class: "seg" },
    h("button", { pressed: true, onclick: (e) => { flags.zones = !flags.zones; e.target.setAttribute("aria-pressed", flags.zones); if (chart) { chart.showZones = flags.zones; chart.queue(); } } }, "Zones OB/FVG"),
    h("button", { pressed: true, onclick: (e) => { flags.trades = !flags.trades; e.target.setAttribute("aria-pressed", flags.trades); load(); } }, "Trades"));
  const kv = (k, v, c) => [h("span", { class: "k", text: k }), h("span", { class: "v " + (c || ""), text: v })];
  const gauge = (label, val, lim, text) => h("div", null, h("div", { class: "bar", style: { justifyContent: "space-between" } }, h("span", { class: "lbl", text: label }), h("span", { class: "mono mute", text: text })),
    h("div", { class: "gauge " + (val / lim > 0.85 ? "bad" : val / lim > 0.5 ? "warn" : "good") }, h("i", { style: { width: Math.min(100, Math.max(0, val / lim * 100)) + "%" } })));

  async function load() {
    let c; try { c = await api("/api/chart" + (runner ? `?runner=${encodeURIComponent(runner)}` : ""), { quiet: true }); } catch (e) { return; }
    if (!c.available) { clear(chartHost).append(h("div", { class: "empty", style: { margin: "auto", color: "var(--tx3)", textAlign: "center", padding: "30px" } }, c.note || "Aucune donnée")); chart = null; return; }
    runner = c.runner; ctx.store.runner = runner;
    clear(sel).append(...c.runners.map((r) => h("option", { value: r, text: r.replace("_", " · "), selected: r === runner })));
    if (!chart) { clear(chartHost); chart = new PriceChart(chartHost); chart.showZones = flags.zones; first = true; }
    chart.setData(c.candles); chart.setZones(c.zones);
    const L = [];
    if (c.position) L.push({ price: c.position.entry, color: "#4c8dff", title: "ENTRÉE", style: 0 }, { price: c.position.stop, color: "#f0504d", title: "SL" }, { price: c.position.tp, color: "#26c281", title: "TP" });
    if (c.pending) L.push({ price: c.pending.entry, color: "#4c8dff", title: "ordre", style: 3 }, { price: c.pending.stop, color: "#f0504d", title: "SL prévu", style: 3 }, { price: c.pending.tp, color: "#26c281", title: "TP prévu", style: 3 });
    chart.setLevels(L); chart.setMarkers(flags.trades ? tradeMarkers(c.trades) : []);
    if (first && c.candles.length) { first = false; const n = c.candles.length; chart.chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - 160), to: n + 6 }); }
    title.textContent = `${c.symbol} · ${c.strategy} · ${c.source} · ${c.mode} · dernière barre ${barTime(c.last_bar)} UTC${c.zones_error ? " · zones: " + c.zones_error : ""}`;
    paintSide(c);
  }
  function paintSide(c) {
    const last = c.candles.length ? c.candles[c.candles.length - 1].close : null, p = c.position;
    const kvbox = h("div", { class: "kv" });
    if (p) { const sg = p.side === "long" ? 1 : -1, pnl = isNum(last) ? (last - p.entry) * p.size * sg : null, d = Math.abs(p.entry - p.stop), r = isNum(last) && d ? (last - p.entry) * sg / d : null;
      kvbox.append(...kv("Sens", p.side === "long" ? "BUY" : "SELL", p.side === "long" ? "up" : "dn"), ...kv("Entrée", price(p.entry, p.entry)), ...kv("Stop (SL)", price(p.stop, p.entry), "dn"), ...kv("Objectif (TP)", price(p.tp, p.entry), "up"),
        ...kv("Taille", num(p.size, 4)), ...kv("Dernier", price(last, p.entry)), ...kv("PnL latent", sgn(pnl, 2), pnlClass(pnl)), ...kv("R latent (approx.)", sgn(r, 2), pnlClass(r)), ...kv("Depuis (barre)", barTime(p.entry_time))); }
    else kvbox.append(h("span", { class: "dim", style: { gridColumn: "1/-1" }, text: c.pending ? `Ordre décidé, exécution à l'ouverture suivante (${c.pending.side})` : "Aucune position ouverte." }));
    clear(side).append(h("div", { class: "panel" }, h("div", { class: "ph" }, h("h2", { text: "Position" })), h("div", { class: "pb" }, kvbox)),
      h("div", { class: "panel" }, h("div", { class: "ph" }, h("h2", { text: "Contrôle de risque actif" })), h("div", { class: "pb" }, riskPanel(c.risk))));
  }
  function riskPanel(r) {
    if (!r) return h("div", { class: "dim", text: "Désactivé pour cette simulation (specs figées : le contrôle actif n'a pas été utilisé dans les essais passés)." });
    const lim = ctx.store.risk || { daily: 0.015, dd: 0.06 };
    return h("div", null, h("div", { class: "bar", style: { marginBottom: "6px" } }, h("span", { class: "badge " + (r.halt ? "b-sl" : "b-tp"), text: r.halt ? "ARRÊT" : "ACTIF" }), h("span", { class: "mono mute", text: `risque ×${(r.multiplier ?? 1).toFixed(2)}` })),
      gauge("Perte du jour", Math.max(0, -(r.daily_pnl_pct || 0)), lim.daily, pct(r.daily_pnl_pct, 2) + " / −" + pct(lim.daily, 1)), gauge("Drawdown", r.drawdown_pct || 0, lim.dd, pct(r.drawdown_pct, 2) + " / " + pct(lim.dd, 1)),
      h("div", { class: "note", text: (r.reasons || []).join(" · ") || `volatilité ×${isNum(r.vol_ratio) ? r.vol_ratio.toFixed(1) : "—"} · Kelly f=${isNum(r.kelly_f) ? r.kelly_f.toFixed(2) : "n/a"}` }));
  }
  async function loadList() {
    let b; try { b = await api("/api/book?period=all", { quiet: true }); } catch (e) { return; }
    const open = b.rows.filter((r) => r.open);
    clear(list).append(h("table", { class: "plain" }, h("thead", null, h("tr", null, ...["Stratégie", "Actif", "Sens", "PnL"].map((x, i) => h("th", { class: i > 2 ? "r" : "", text: x })))),
      h("tbody", null, open.length ? open.map((r) => h("tr", { style: { cursor: "pointer" }, onclick: () => { runner = r.runner; ctx.store.runner = runner; first = true; load(); } }, h("td", { class: "strat", text: r.strategy_code }), h("td", { text: r.symbol }),
        h("td", { class: r.side === "long" ? "up" : "dn", text: r.side === "long" ? "BUY" : "SELL" }), h("td", { class: "r " + pnlClass(r.pnl), text: sgn(r.pnl, 2) }))) : [h("tr", null, h("td", { colspan: 4, class: "dim", text: "Aucune position ouverte." }))])));
  }
  root.append(h("div", { class: "cols", style: { gridTemplateColumns: "minmax(0,1fr) 330px", height: "100%" } },
    h("div", { class: "panel", style: { minHeight: "520px" } }, h("div", { class: "ph" }, h("h2", { text: "Marché" }), sel, toggles, h("span", { class: "sp" }), title), chartHost),
    h("div", { class: "stack", style: { overflow: "auto" } }, side, h("div", { class: "panel" }, h("div", { class: "ph" }, h("h2", { text: "Positions ouvertes (toutes stratégies)" })), h("div", { class: "pb" }, list)))));
  const s1 = poller(load, 3000), s2 = poller(loadList, 4000);
  return () => { s1(); s2(); if (chart) chart.destroy(); };
}
