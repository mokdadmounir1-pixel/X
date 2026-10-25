import { h } from "./util.js";
export function toast(msg) {
  const t = h("div", { class: "toast", role: "alert", text: msg });
  document.getElementById("toasts").append(t); setTimeout(() => t.remove(), 7000);
}
export async function api(path, { quiet = false } = {}) {
  const ctl = new AbortController(); const to = setTimeout(() => ctl.abort(), 120000);
  try {
    const r = await fetch(path, { signal: ctl.signal });
    const j = await r.json().catch(() => ({}));
    if (!r.ok || j.error) throw new Error(j.detail || j.error || `HTTP ${r.status}`);
    return j;
  } catch (e) { if (!quiet) toast(`Erreur ${path.split("?")[0]} : ${e.message}`); throw e; }
  finally { clearTimeout(to); }
}
/* Boucle d'interrogation : suspendue quand l'onglet du navigateur est caché, sans empilement de requêtes. */
export function poller(fn, ms) {
  let stop = false, busy = false, timer = null;
  const tick = async () => {
    if (stop) return;
    if (!document.hidden && !busy) { busy = true; try { await fn(); } catch (e) { /* déjà signalé */ } busy = false; }
    timer = setTimeout(tick, ms);
  };
  tick();
  return () => { stop = true; clearTimeout(timer); };
}
