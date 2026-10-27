/* SYSTÈME : intégrité (registre, journal de données), automatisation, approbations humaines, avertissements connus. */
import { h, clear, ago, barTime, num, isNum, sgn, pct, pnlClass } from "../util.js";
import { api, poller } from "../api.js";

export function mount(root, ctx) {
  const box = h("div", { class: "cols", style: { gridTemplateColumns: "repeat(2,minmax(0,1fr))" } });
  const kv = (rows) => h("div", { class: "kv" }, rows.flatMap(([k, v, c]) => [h("span", { class: "k", text: k }), h("span", { class: "v " + (c || ""), text: v })]));
  const panel = (t, ...k) => h("div", { class: "panel" }, h("div", { class: "ph" }, h("h2", { text: t })), h("div", { class: "pb" }, ...k));
  async function load() {
    let S, L, P, Y, G; try { [S, L, P, Y, G] = await Promise.all([api("/api/state", { quiet: true }), api("/api/live", { quiet: true }), api("/api/paper", { quiet: true }), api("/api/sync", { quiet: true }), api("/api/ledger", { quiet: true })]); } catch (e) { return; }
    const d = S.daemon, q = S.queue, age = d ? Date.now() / 1000 - d.ts : null, st = S.status;
    clear(box).append(
      panel("Intégrité", kv([["Registre d'essais", st.registry_chain_ok ? "chaîne intègre" : "ALTÉRÉ", st.registry_chain_ok ? "up" : "dn"], ["Essais", `${st.trials} / ${st.trials_budget}`], ["Lectures période verrouillée", String(st.locked_reads)], ["Journal des données", d ? (d.chain_ok ? "chaîne intègre" : "ALTÉRÉ") : "jamais lancé", d && !d.chain_ok ? "dn" : ""], ["Mode interface", "LECTURE SEULE (aucun ordre, aucune approbation écrite)", "up"]])),
      panel("Extraction MT5 (data_daemon)", kv([["État", !d ? "jamais lancé" : age < 180 ? (d.connected ? "actif" : "terminal déconnecté") : "arrêté", d && age < 180 && d.connected ? "up" : "amb"], ["Dernier passage", d ? "il y a " + ago(age) : "—"], ["Séries", d ? String((d.series || []).length) : "0"], ["Ordres envoyés", d ? String(d.orders_sent) : "0"]]),
        h("div", { class: "note", text: "Lecture seule : barres clôturées uniquement, aucune barre existante jamais réécrite." })),
      panel("Synchronisation automatique des données", kv(Y.available ? Y.results.map((r) => [r.source === "coinbase" ? `Coinbase ${r.product} ${r.tf}` : r.source === "cot" ? "COT or (CFTC)" : r.source === "fred" ? "Calendrier macro (FRED)" : "MetaTrader 5", r.status === "ok" ? ("à jour" + (r.appended != null ? ` (+${r.appended} barres, dernière ${barTime(r.last_bar)})` : r.rows != null ? ` (${r.rows} lignes)` : "")) : (r.status + (r.error ? " : " + r.error : r.note ? " : " + r.note : "")), r.status === "ok" ? "up" : "amb"]).concat([["Dernier passage", "il y a " + ago(Date.now() / 1000 - Y.ts)], ["Ordres envoyés", String(Y.orders_sent)]]) : [["État", "jamais exécutée", "amb"]]),
        h("div", { class: "note", text: Y.available ? "Lecture seule, toutes les " + Math.round(Y.interval_s / 60) + " min. Un échec est affiché et réessayé, jamais comblé." : (Y.note || "") })),
      panel("Portefeuille FTMO simulé (compte unique 100 000 $)", kv([["Equity simulée", num(G.equity, 0)], ["PnL du jour", `${sgn(G.pnl_today, 0)} (${pct(G.daily_pct, 2)} / limite −${pct(G.limits.daily, 0)})`, G.daily_pct <= -G.limits.daily_buffer ? "dn" : pnlClass(G.pnl_today)], ["PnL total", `${sgn(G.pnl_realised + G.pnl_latent, 0)} (${pct(G.total_pct, 2)} / limite −${pct(G.limits.total, 0)})`, G.total_pct <= -G.limits.total_buffer ? "dn" : pnlClass(G.total_pct)],
        ["Coupe-circuit global", G.halt_new || G.kill_file_present ? "ACTIF : " + (G.reasons.join(" · ") || "fichier KILL présent") : "inactif", G.halt_new || G.kill_file_present ? "dn" : "up"], ["Trades clos / ouverts", `${G.n_closed} / ${G.n_open}`]]),
        h("div", { class: "note", text: G.note + " Levée du coupe-circuit : humaine (supprimer runtime/paper/KILL)." })),
      panel("Processus automatiques (lancés et relancés par le terminal)", kv(S.supervisor && S.supervisor.workers ? S.supervisor.workers.map((w) => [w.name, w.state === "en cours" ? `en cours · pid ${w.pid} · ${Math.round(w.uptime_s)} s` : `${w.state} · relances ${w.restarts} · code ${w.last_exit ?? "—"} · prochain essai ${Math.round(w.next_start_in_s)} s`, w.state === "en cours" ? "up" : "amb"]) : [["Superviseur", "non lancé (terminal ouvert avec --no-workers ou exécutable compilé)", "amb"]]),
        h("div", { class: "note", text: S.supervisor && S.supervisor.workers ? S.supervisor.workers.map((w) => w.tail && w.tail.length ? `${w.name} : ${w.tail[w.tail.length - 1]}` : "").filter(Boolean).join("  ·  ") : "Journaux : runtime/logs/" })),
      panel("Simulation PAPER", kv([["Simulations", P.available ? String(P.runners.length) : "0"], ["Total cumulé", P.available ? (P.total_R >= 0 ? "+" : "") + P.total_R.toFixed(2) + " R" : "—"], ["Source", P.available ? [...new Set(P.runners.map((r) => r.source))].join(", ") : "—"]]),
        h("div", { class: "note", text: P.available ? "Prix réels, exécutions simulées : aucune approbation lue, aucun broker d'ordres." : (P.note || "") })),
      panel("Lanceur (OBSERVATION / DEMO_ACTIF)", kv([["Mode", L.available ? L.mode : "non démarré"], ["Dernière barre", L.available ? barTime(L.last_bar) : "—"], ["Coupe-circuit", L.available && L.kill_reasons.length ? "ACTIF" : "inactif", L.available && L.kill_reasons.length ? "dn" : "up"], ["Approbations humaines", String((L.approvals.entries || []).length)]]),
        h("div", { class: "note", text: (L.kill_reasons || []).join(" · ") || L.approvals.note })),
      panel("File de recherche", kv([["Essais", q ? `${q.n_trials} / ${q.budget}` : "—"], ["En attente", q ? String((q.pending || []).length) : "—"], ["Bloquées", q ? String(Object.keys(q.blocked || {}).length) : "—"]]),
        h("div", { class: "note", text: "Chaque item = une spec préenregistrée, exécutée une fois, dans le budget d'essais." })),
      panel("À savoir", h("ul", { style: { margin: 0, paddingLeft: "16px", color: "var(--tx2)", lineHeight: "1.7" } },
        h("li", { text: "Aucun avantage de trading n'est validé : les simulations servent à observer, pas à prouver." }),
        h("li", { text: "USTEC annonce trade_mode = 0 (désactivé) sur le compte démo : à vérifier en séance." }),
        h("li", { text: "Les coûts crypto (Coinbase) et les swaps sont des hypothèses déclarées." }),
        h("li", { text: "Passage en DEMO_ACTIF : décision humaine, approbation signée liée à l'empreinte de la spec." }))));
  }
  root.append(box); const s = poller(load, 5000); return () => s();
}
