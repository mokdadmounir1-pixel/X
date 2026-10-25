/* RECHERCHE : verdicts de validation par spec, classement R/jour face à l'objectif, optimisation en marche avant. */
import { h, clear, num, sgn, pct, pnlClass, isNum } from "../util.js";
import { api } from "../api.js";

export function mount(root, ctx) {
  let S = null, sub = ctx.store.sub || "res";
  const host = h("div", { class: "stack" }), segs = h("div", { class: "seg" });
  const verdict = (v) => h("span", { class: "badge " + (v === "PASS" ? "b-tp" : v === "WATCH" ? "b-time" : "b-sl"), text: v || "—" });
  const gate = (g) => h("span", { class: "chip", title: `valeur ${JSON.stringify(g.value)} · seuil ${JSON.stringify(g.threshold)}`, style: { height: "20px", color: g.ok ? "var(--up)" : "var(--dn)", borderColor: g.ok ? "rgba(38,194,129,.3)" : "rgba(240,80,77,.4)" }, text: g.name + (g.eliminatory && !g.ok ? " ⛔" : "") });
  function res() {
    return S.specs.map((sp) => h("div", { class: "panel" }, h("div", { class: "ph" }, h("h2", { text: sp.name }), h("span", { class: "meta", text: sp.parent ? "← " + sp.parent : "" })),
      h("div", { class: "pb flush" }, h("table", { class: "plain" }, h("thead", null, h("tr", null, ...["Essai", "Verdict", "Trades", "Espérance (R)", "PF", "Pire (R)", "R / jour", "Portes"].map((x, i) => h("th", { class: i > 1 && i < 7 ? "r" : "", text: x })))),
        h("tbody", null, sp.results.map((r) => h("tr", null, h("td", { class: "strat", text: r.instrument }), h("td", null, verdict(r.verdict)), h("td", { class: "r", text: r.n_trades ?? "—" }), h("td", { class: "r " + pnlClass(r.expectancy_R), text: sgn(r.expectancy_R, 3) }),
          h("td", { class: "r", text: isNum(r.profit_factor) ? r.profit_factor.toFixed(2) : "—" }), h("td", { class: "r", text: isNum(r.worst_trade_R) ? r.worst_trade_R.toFixed(2) : "—" }), h("td", { class: "r", text: isNum(r.r_per_day) ? r.r_per_day.toFixed(3) : "—" }),
          h("td", null, h("div", { class: "bar", style: { gap: "3px" } }, (r.gates || []).filter((g) => !g.ok).map(gate)))))))), h("div", { class: "pb note", text: sp.hypothesis || sp.change_reason || "" })));
  }
  function objectif() {
    const o = S.objective, mx = Math.max(o.target_r_per_day, ...o.rows.map((r) => r.r_per_day));
    return [h("div", { class: "metrics" }, h("div", { class: "metric" }, h("div", { class: "k", text: "Objectif" }), h("div", { class: "v amb", text: num(o.target_r_per_day, 2) + " R/jour" }), h("div", { class: "s", text: "repère de lecture, jamais un réglage" })),
      h("div", { class: "metric" }, h("div", { class: "k", text: "Meilleur honnête" }), h("div", { class: "v", text: o.best ? num(o.best.r_per_day, 3) + " R/jour" : "—" }), h("div", { class: "s", text: o.best ? o.best.name + " · " + o.best.spec : "" })),
      h("div", { class: "metric" }, h("div", { class: "k", text: "Écart" }), h("div", { class: "v dn", text: o.multiple_of_best ? "× " + o.multiple_of_best.toFixed(1) : "—" }), h("div", { class: "s", text: "objectif / meilleur" }))),
      h("div", { class: "panel" }, h("div", { class: "ph" }, h("h2", { text: "Classement R / jour" })), h("div", { class: "pb flush" }, h("table", { class: "plain" }, h("thead", null, h("tr", null, ...["Essai", "Spec", "Verdict", "Trades", "Espérance", "R/jour", "vs objectif", "Lecture"].map((x, i) => h("th", { class: i > 2 && i < 6 ? "r" : "", text: x })))),
        h("tbody", null, o.rows.map((r) => h("tr", null, h("td", { class: "strat", text: r.name }), h("td", { class: "dim", text: r.spec }), h("td", null, verdict(r.verdict)), h("td", { class: "r", text: r.n_trades }), h("td", { class: "r " + pnlClass(r.expectancy_R), text: sgn(r.expectancy_R, 3) }),
          h("td", { class: "r", text: r.r_per_day.toFixed(3) }), h("td", { style: { width: "160px" } }, h("div", { class: "gauge " + (r.beta ? "warn" : ""), title: r.r_per_day.toFixed(3) }, h("i", { style: { width: Math.max(1, r.r_per_day / mx * 100) + "%" } }))),
          h("td", { class: r.beta ? "amb" : "dim", style: { whiteSpace: "normal", minWidth: "260px" }, text: r.beta ? "bêta, pas un avantage — " + r.beta : "—" })))))))];
  }
  function wf() {
    const W = S.walkforward || [];
    if (!W.length) return [h("div", { class: "panel" }, h("div", { class: "pb dim", text: "Aucun résultat : python scripts/optimize.py specs/wf_v1.json" }))];
    return W.map((r) => { const m = r.summary; return h("div", { class: "panel" }, h("div", { class: "ph" }, h("h2", { text: `${r.instrument} · ${r.strategy}` }), h("span", { class: "meta", text: `${r.n_configs} configurations · entraînement 365 j / test 90 j` })),
      h("div", { class: "pb" }, h("div", { class: "metrics" }, ...[["Espérance hors échantillon", sgn(m.oos_expectancy_R, 3) + " R", pnlClass(m.oos_expectancy_R)], ["PF hors échantillon", isNum(m.oos_profit_factor) ? m.oos_profit_factor.toFixed(2) : "—", ""], ["Écart d'optimisme", sgn(m.optimism_gap_R, 3) + " R", "amb"], ["Config moyenne non sélectionnée", sgn(m.unselected_average_config_oos_R, 3) + " R", ""], ["p (signe)", isNum(m.oos_sign_flip_p) ? m.oos_sign_flip_p.toFixed(3) : "—", ""], ["Fenêtres tradées", `${m.n_windows_traded}/${m.n_windows}`, ""]]
        .map(([k, v, c]) => h("div", { class: "metric" }, h("div", { class: "k", text: k }), h("div", { class: "v " + c, text: v })))))); });
  }
  function paint() {
    clear(segs).append(...[["res", "Verdicts"], ["obj", "Objectif"], ["wf", "Optimisation"]].map(([k, l]) => h("button", { pressed: sub === k, onclick: () => { sub = k; ctx.store.sub = k; paint(); } }, l)));
    clear(host); if (!S) { host.append(h("div", { class: "skel" })); return; }
    host.append(...(sub === "res" ? res() : sub === "obj" ? objectif() : wf()));
    host.append(h("div", { class: "note", text: `Essais comptés : ${S.status.trials}/${S.status.trials_budget} · lectures de la période verrouillée : ${S.status.locked_reads} · aucun avantage validé. Les verdicts utilisent des portes préenregistrées (DSR, test nul, Monte-Carlo, coûts ×2…).` }));
  }
  root.append(h("div", { class: "stack" }, h("div", { class: "bar" }, segs), host)); paint();
  api("/api/state").then((x) => { S = x; paint(); });
  return () => {};
}
