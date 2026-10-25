/* Grille de données : en-têtes collants, lignes alternées, tri, rendu fenêtré (milliers de lignes), navigation clavier. */
import { h, clear } from "./util.js";
const ROW = 28;
export class DataGrid {
  constructor({ columns, rowKey = (r) => r.id, onSelect = null, empty = "Aucune donnée", sort = null }) {
    this.cols = columns; this.key = rowKey; this.onSelect = onSelect; this.emptyMsg = empty;
    this.rows = []; this.sort = sort; this.sel = null; this.start = 0;
    this.scroller = h("div", { class: "dg", tabindex: "0", role: "grid" });
    this.table = h("table"); this.thead = h("thead"); this.tbody = h("tbody");
    this.table.append(this.thead, this.tbody); this.scroller.append(this.table);
    this.scroller.addEventListener("scroll", () => this.paint(), { passive: true });
    this.scroller.addEventListener("keydown", (e) => this.keys(e));
    this.head(); this.el = this.scroller;
  }
  head() {
    clear(this.thead);
    const tr = h("tr");
    for (const c of this.cols) {
      const active = this.sort && this.sort[0] === c.key;
      tr.append(h("th", { class: c.align === "r" ? "r" : "", style: c.width ? { width: c.width } : null, title: c.title || "Trier",
        onclick: () => { if (c.sortable === false) return; this.sort = this.sort && this.sort[0] === c.key ? [c.key, -this.sort[1]] : [c.key, c.defaultDir || -1]; this.head(); this.resort(); this.paint(true); } },
        c.label, active ? (this.sort[1] > 0 ? " ▲" : " ▼") : ""));
    }
    this.thead.append(tr);
  }
  setRows(rows) { this.rows = rows.slice(); this.resort(); this.paint(true); }
  resort() {
    if (!this.sort) return;
    const [k, d] = this.sort; const col = this.cols.find((c) => c.key === k); const get = col && col.sortValue ? col.sortValue : (r) => r[k];
    this.rows.sort((a, b) => { const x = get(a), y = get(b); if (x == null && y == null) return 0; if (x == null) return 1; if (y == null) return -1; return (x > y ? 1 : x < y ? -1 : 0) * d; });
  }
  select(key, scroll = true) {
    this.sel = key; const i = this.rows.findIndex((r) => this.key(r) === key);
    if (scroll && i >= 0) { const top = i * ROW, v = this.scroller.scrollTop, hgt = this.scroller.clientHeight - ROW * 2; if (top < v) this.scroller.scrollTop = top; else if (top > v + hgt) this.scroller.scrollTop = top - hgt + ROW; }
    this.paint(true); if (this.onSelect && i >= 0) this.onSelect(this.rows[i]);
  }
  keys(e) {
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key) || !this.rows.length) return;
    e.preventDefault(); let i = this.rows.findIndex((r) => this.key(r) === this.sel);
    i = e.key === "ArrowDown" ? Math.min(this.rows.length - 1, i + 1) : e.key === "ArrowUp" ? Math.max(0, i - 1) : e.key === "Home" ? 0 : this.rows.length - 1;
    this.select(this.key(this.rows[i]));
  }
  paint(force) {
    const n = this.rows.length; clear(this.tbody);
    if (!n) { this.tbody.append(h("tr", null, h("td", { colspan: this.cols.length, class: "empty" }, this.emptyMsg))); return; }
    const view = this.scroller.clientHeight || 400; const first = Math.max(0, Math.floor(this.scroller.scrollTop / ROW) - 8); const last = Math.min(n, first + Math.ceil(view / ROW) + 16);
    if (first > 0) this.tbody.append(h("tr", { class: "spacer" }, h("td", { colspan: this.cols.length, style: { height: first * ROW + "px" } })));
    for (let i = first; i < last; i++) {
      const r = this.rows[i]; const k = this.key(r);
      const tr = h("tr", { class: k === this.sel ? "sel" : "", onclick: () => this.select(k, false) });
      for (const c of this.cols) { const v = c.render ? c.render(r) : r[c.key]; tr.append(h("td", { class: (c.align === "r" ? "r " : "") + (c.cls ? c.cls(r) : "") }, v == null ? "—" : v)); }
      this.tbody.append(tr);
    }
    if (last < n) this.tbody.append(h("tr", { class: "spacer" }, h("td", { colspan: this.cols.length, style: { height: (n - last) * ROW + "px" } })));
  }
}
