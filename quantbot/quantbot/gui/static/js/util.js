/* Utilitaires : construction DOM sûre (aucun innerHTML sur des données), formats numériques et temporels. */
export function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k === "class") el.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "text") el.textContent = v;
    else if (k === "pressed") el.setAttribute("aria-pressed", String(v));
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
export const clear = (el) => { while (el.firstChild) el.removeChild(el.firstChild); return el; };
export const isNum = (x) => typeof x === "number" && Number.isFinite(x);
export function num(x, d = 2) { return isNum(x) ? x.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }) : "—"; }
export function sgn(x, d = 2) { return isNum(x) ? (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }) : "—"; }
export function pct(x, d = 1) { return isNum(x) ? (x * 100).toFixed(d) + " %" : "—"; }
export const pnlClass = (x) => (isNum(x) ? (x > 0 ? "up" : x < 0 ? "dn" : "mute") : "mute");
export function price(x, ref) { if (!isNum(x)) return "—"; const d = Math.abs(ref ?? x) < 50 ? 5 : Math.abs(ref ?? x) < 5000 ? 2 : 1; return x.toFixed(d); }
const p2 = (n) => String(n).padStart(2, "0");
export function utcMs(ms) { if (!isNum(ms) || ms <= 0) return "—"; const d = new Date(ms); return `${d.getUTCFullYear()}-${p2(d.getUTCMonth() + 1)}-${p2(d.getUTCDate())} ${p2(d.getUTCHours())}:${p2(d.getUTCMinutes())}:${p2(d.getUTCSeconds())}.${String(d.getUTCMilliseconds()).padStart(3, "0")}`; }
export function barTime(s) { return s ? String(s).replace("T", " ").slice(0, 16) : "—"; }
export function epochStamp(e) { const d = new Date(e * 1000); return `${d.getUTCFullYear()}-${p2(d.getUTCMonth() + 1)}-${p2(d.getUTCDate())} ${p2(d.getUTCHours())}:${p2(d.getUTCMinutes())}`; }
export function ago(s) { if (!isNum(s)) return "—"; s = Math.round(s); return s < 90 ? s + " s" : s < 5400 ? Math.round(s / 60) + " min" : (s / 3600).toFixed(1) + " h"; }
export const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
export const reasonLabel = (k) => ({ take_profit: "Objectif atteint (TP)", stop_loss: "Stop touché (SL)", max_hold: "Durée maximale", weekend: "Fermeture week-end", ftmo_weekend: "Fermeture week-end", end: "Fin des données", data_hole: "Trou de données", data_gap: "Trou de données", active_risk_flatten: "Clôture contrôle de risque", ftmo_flatten: "Clôture garde-fou FTMO" }[k] || k || "—");
export function badge(status) {
  const cls = { OUVERT: "b-open", TP: "b-tp", SL: "b-sl", TEMPS: "b-time" }[status] || "b-oth";
  return h("span", { class: "badge " + cls, text: status });
}
