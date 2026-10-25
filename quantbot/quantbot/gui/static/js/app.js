/* Terminal : routeur d'onglets, horloge UTC, pastilles d'état, barre d'état. Lecture seule. */
import { h, clear } from "./util.js";
import { api, poller } from "./api.js";
import { mount as mMarche } from "./views/marche.js";
import { mount as mTrades } from "./views/trades.js";
import { mount as mBacktest } from "./views/backtest.js";
import { mount as mRisque } from "./views/risque.js";
import { mount as mRecherche } from "./views/recherche.js";
import { mount as mSysteme } from "./views/systeme.js";

const TABS = [["trades", "Live trades & attribution", mTrades], ["marche", "Marché", mMarche], ["backtest", "Backtests", mBacktest], ["risque", "Risque", mRisque], ["recherche", "Recherche", mRecherche], ["systeme", "Système", mSysteme]];
const store = { period: "session" };
let current = null, unmount = null;
const $ = (s) => document.querySelector(s);

function pills(S, L, D) {
  const P = [], st = S && S.status, d = S && S.daemon, age = d ? Date.now() / 1000 - d.ts : null;
  const pill = (cls, text, title) => h("span", { class: "pill " + cls, title }, h("i"), text);
  if (st) { P.push(pill(st.edge_validated ? "ok" : "warn", "Avantage " + (st.edge_validated ? "validé" : "non validé"), "Une stratégie a-t-elle franchi toutes les portes de validation ?")); P.push(pill(st.registry_chain_ok ? "ok" : "bad", `Essais ${st.trials}/${st.trials_budget}`, "Registre d'essais (chaîne de hachage)")); }
  P.push(pill(D && D.available ? "ok" : "warn", D && D.available ? `Simulation ${D.runners.length}` : "Simulation à l'arrêt", "Simulations PAPER sur prix réels"));
  P.push(pill(d && age < 180 && d.connected ? "ok" : "warn", d && age < 180 ? (d.connected ? "Données en direct" : "Terminal déconnecté") : "Données à l'arrêt", "Extraction MT5 en lecture seule"));
  P.push(pill("", "LECTURE SEULE", "Cette interface n'envoie jamais d'ordre"));
  clear($("#pills")).append(...P);
}
function go(id, opts) {
  if (unmount) { try { unmount(); } catch (e) { /* vue déjà détruite */ } unmount = null; }
  const tab = TABS.find((t) => t[0] === id) || TABS[0]; current = tab[0];
  try { localStorage.setItem("qb.tab", current); } catch (e) { /* stockage indisponible */ }
  try { history.replaceState(null, "", "#" + current); } catch (e) { /* idem */ }
  clear($("#tabs")).append(...TABS.map(([k, label]) => h("button", { class: "tab", role: "tab", "aria-selected": k === current, onclick: () => go(k) }, label)));
  const view = $("#view"); clear(view); store.runner = (opts && opts.runner) || store.runner;
  unmount = tab[2](view, { store, go, setStatus: (t) => { $("#sb-left").textContent = t; } }, opts || {});
}
function clock() { const d = new Date(), p = (n) => String(n).padStart(2, "0"); $("#clock").textContent = `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())} UTC`; }
async function boot() {
  clock(); setInterval(clock, 1000);
  const hash = location.hash.slice(1); let saved = null; try { saved = localStorage.getItem("qb.tab"); } catch (e) { /* ignoré */ }
  go(TABS.some((t) => t[0] === hash) ? hash : TABS.some((t) => t[0] === saved) ? saved : "trades");
  poller(async () => {
    const [S, L, D] = await Promise.all([api("/api/state", { quiet: true }), api("/api/live", { quiet: true }), api("/api/paper", { quiet: true })]);
    pills(S, L, D); const b = $("#banner"), ok = S.status.edge_validated;
    b.className = ok ? "ok" : ""; b.textContent = ok ? "Au moins une stratégie a franchi les portes de recherche — pas encore confirmée sur le futur ni sur la période verrouillée." : "Aucun avantage de trading validé · interface en lecture seule : aucun ordre, aucune approbation écrite · les trades affichés sont des simulations PAPER sur prix réels.";
    $("#sb-right").textContent = `quantbot · registre ${S.status.registry_chain_ok ? "intègre" : "ALTÉRÉ"} · ${S.status.trials}/${S.status.trials_budget} essais`;
  }, 8000);
}
boot();
