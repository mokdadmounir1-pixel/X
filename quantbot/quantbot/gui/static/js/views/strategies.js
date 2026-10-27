/* STRATÉGIES : catalogue de tout ce qui existe dans quantbot, verdict de recherche, état de la simulation PAPER, accès direct au banc d'essai. */
import { h, clear, num, sgn, pnlClass } from "../util.js";
import { api, poller } from "../api.js";

export function mount(root, ctx) {
  const box = h("div", { class: "stack" }); let filter = "";
  const badge = (v) => h("span", { class: "badge " + (v === "PASS" ? "up" : v === "WATCH" ? "amb" : "dn"), text: v || "—" });
  const search = h("input", { type: "search", placeholder: "Filtrer (nom, famille, instrument)…", style: { width: "320px" }, oninput: (e) => { filter = e.target.value.toLowerCase(); paint(); } });
  let C = null;
  function paint() {
    if (!C) return;
    const rows = C.strategies.filter((r) => !filter || `${r.label} ${r.code} ${r.family} ${r.instruments.join(" ")}`.toLowerCase().includes(filter));
    clear(box).append(
      h("div", { class: "panel" }, h("div", { class: "ph" }, h("h2", { text: `Stratégies exécutables : ${C.n_strategies} · simulation PAPER active : ${C.n_paper_running}` }), search),
        h("div", { class: "pb flush" }, h("table", { class: "plain" }, h("thead", null, h("tr", null, ...["Code", "Stratégie", "Famille", "Instruments", "Recherche (verdict · espérance · PF · trades)", "PAPER", ""].map((x) => h("th", { text: x })))),
          h("tbody", null, rows.map((r) => h("tr", null,
            h("td", { text: r.code }), h("td", { text: r.label }), h("td", { text: r.family }), h("td", { text: r.instruments.join(", ") }),
            h("td", null, ...(r.research.length ? r.research.map((x) => h("div", null, badge(x.verdict), ` ${x.instrument} · ${x.expectancy_R == null ? "—" : sgn(x.expectancy_R, 3) + " R"} · PF ${x.profit_factor == null ? "—" : num(x.profit_factor, 2)} · ${x.n_trades ?? "—"} trades`)) : [h("span", { class: "dim", text: "non exécutée en recherche" })])),
            h("td", null, r.paper.running ? h("span", { class: "up", text: `actif · ${r.paper.trades} trades` + (r.paper.open ? ` · ${r.paper.open} ouvert` : "") }) : h("span", { class: "amb", text: r.paper.runners ? "arrêté" : "pas lancé" })),
            h("td", null, h("button", { class: "btn", onclick: () => { ctx.store.bt = { ...(ctx.store.bt || {}), strategy: r.id, instrument: r.instruments[0], segment: "recherche", bars: 6000 }; ctx.go("backtest"); } }, "Backtest")))))))),
      h("div", { class: "panel" }, h("div", { class: "ph" }, h("h2", { text: "Autres modules (pas rejouables dans le banc d'essai) et ce qui manque" })),
        h("div", { class: "pb" }, h("table", { class: "plain" }, h("tbody", null, C.other_modules.map((m) => h("tr", null, h("td", { text: m.label }), h("td", { class: "dim", text: m.status }))))))),
      h("div", { class: "note", text: C.note }));
  }
  async function load() { try { C = await api("/api/catalog", { quiet: true }); paint(); } catch (e) { /* déjà signalé */ } }
  root.append(box); const stop = poller(load, 10000); return () => stop();
}
