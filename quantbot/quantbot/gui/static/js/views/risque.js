/* RISQUE : état du contrôle actif par simulation, objectifs (R/jour et % mensuel) honnêtement comparés au réalisé. */
import { h, clear, num, sgn, pct, pnlClass, isNum } from "../util.js";
import { api, poller } from "../api.js";

export function mount(root, ctx) {
  const box = h("div", { class: "stack" });
  async function load() {
    let book, state; try { [book, state] = await Promise.all([api("/api/book?period=all", { quiet: true }), api("/api/state", { quiet: true })]); } catch (e) { return; }
    const o = state.objective, m = book.metrics, now = new Date(book.now * 1000), ym = `${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, "0")}`;
    const mtd = book.rows.filter((r) => !r.open && String(r.exit_time || "").startsWith(ym)).reduce((s, r) => s + (r.pnl || 0), 0), mtdPct = m.capital ? mtd / m.capital : 0;
    const goal = (o && o.target_monthly_net) || 0.02, need = goal * m.capital;
    const card = (t, ...kids) => h("div", { class: "panel" }, h("div", { class: "ph" }, h("h2", { text: t })), h("div", { class: "pb" }, ...kids));
    const kv = (k, v, c) => [h("span", { class: "k", text: k }), h("span", { class: "v " + (c || ""), text: v })];
    const g = (v, lim, good) => h("div", { class: "gauge " + (good ? "good" : v / lim > 0.85 ? "bad" : v / lim > 0.5 ? "warn" : "") }, h("i", { style: { width: Math.min(100, Math.max(0, v / lim * 100)) + "%" } }));
    clear(box).append(
      h("div", { class: "cols", style: { gridTemplateColumns: "repeat(3,minmax(0,1fr))" } },
        card("Objectif mensuel", h("div", { class: "kv" }, ...kv("Cible", pct(goal, 1) + " net / mois (repère, jamais un réglage)"), ...kv("Réalisé ce mois (PAPER)", sgn(mtd, 2) + " · " + pct(mtdPct, 2), pnlClass(mtd)), ...kv("Cible en valeur", num(need, 0))),
          g(Math.max(0, mtd), need, mtd >= need), h("div", { class: "note", text: "Un mois de simulation n'a aucune valeur statistique. Atteindre 2 % par mois demanderait un avantage réel : aucun n'est validé à ce jour." })),
        card("Objectif quotidien", h("div", { class: "kv" }, ...kv("Cible", num(o ? o.target_r_per_day : 0.33, 2) + " R / jour ouvré"), ...kv("Meilleur résultat honnête", o && o.best ? num(o.best.r_per_day, 3) + " R/jour" : "—"), ...kv("Écart", o && o.multiple_of_best ? "× " + o.multiple_of_best.toFixed(1) : "—", "amb")),
          h("div", { class: "note", text: o && o.best ? `${o.best.name} (${o.best.spec}) : repère de lecture, hors effet de marché.` : "" })),
        card("Capital simulé", h("div", { class: "kv" }, ...kv("PnL total", sgn(m.pnl_total, 2), pnlClass(m.pnl_total)), ...kv("Drawdown", pct(m.drawdown_pct, 2), m.drawdown_pct > 0 ? "dn" : ""), ...kv("Compte FTMO simulé (unique)", num(m.capital, 0)), ...kv("Équité", num(m.equity, 0)), ...kv("Risque ouvert cumulé", pct(m.open_risk_pct, 2) + " (limite journalière FTMO 5 %)", m.open_risk_pct > 0.03 ? "dn" : ""), ...kv("Lanceurs (même compte)", String(book.runners.length))))),
      h("div", { class: "panel" }, h("div", { class: "ph" }, h("h2", { text: "Contrôle de risque actif par simulation" })), h("div", { class: "pb flush" }, h("table", { class: "plain" },
        h("thead", null, h("tr", null, ...["Simulation", "Mode", "État", "Risque ×", "Perte jour", "Drawdown", "Volatilité", "Kelly f", "Raisons"].map((x, i) => h("th", { class: i > 2 && i < 8 ? "r" : "", text: x })))),
        h("tbody", null, book.runners.map((r) => { const k = r.risk; return h("tr", null, h("td", { class: "strat", text: r.id }), h("td", { text: r.mode || "—" }),
          h("td", null, k ? h("span", { class: "badge " + (k.halt ? "b-sl" : "b-tp"), text: k.halt ? "ARRÊT" : "ACTIF" }) : h("span", { class: "dim", text: "désactivé" })),
          h("td", { class: "r", text: k ? (k.multiplier ?? 1).toFixed(2) : "—" }), h("td", { class: "r " + pnlClass(k && k.daily_pnl_pct), text: k ? pct(k.daily_pnl_pct, 2) : "—" }), h("td", { class: "r", text: k ? pct(k.drawdown_pct, 2) : "—" }),
          h("td", { class: "r", text: k && isNum(k.vol_ratio) ? "×" + k.vol_ratio.toFixed(1) : "—" }), h("td", { class: "r", text: k && isNum(k.kelly_f) ? k.kelly_f.toFixed(2) : "n/a" }), h("td", { class: "dim", text: k ? (k.reasons || []).join(" · ") : "" })); })))),
        h("div", { class: "pb note" }, "Le contrôle actif (perte journalière latente incluse, freinage par drawdown, arrêt sur dérive / série de pertes / volatilité anormale, Kelly plafonné) ne peut que RÉDUIRE ou ARRÊTER l'exposition. Il est désactivé dans les simulations tant qu'une spec ne l'active pas explicitement.")));
  }
  root.append(box); const s = poller(load, 5000); return () => s();
}
