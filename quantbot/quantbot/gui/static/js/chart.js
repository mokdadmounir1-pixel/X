/* Graphique de prix (TradingView Lightweight Charts) + zones Order Block / FVG dessinées sur un calque synchronisé + lignes Entrée / SL / TP + marqueurs de trades. */
import { h, isNum } from "./util.js";
const LW = window.LightweightCharts;
const COL = { up: "#26c281", dn: "#f0504d", acc: "#4c8dff", amb: "#e0a43a", tx: "#9099a6", grid: "#12161c", line: "#1e242d" };
export class PriceChart {
  constructor(container, { volume = true } = {}) {
    this.box = h("div", { class: "chartbox" }); this.lw = h("div", { class: "lw" }); this.cv = h("canvas", { class: "zones" }); this.legend = h("div", { class: "legend" });
    this.box.append(this.lw, this.cv, this.legend); container.append(this.box);
    this.zones = []; this.showZones = true; this.lines = []; this.last = null;
    this.chart = LW.createChart(this.lw, {
      layout: { background: { type: "solid", color: "#0d1015" }, textColor: COL.tx, fontFamily: '"JetBrains Mono","Cascadia Mono",Consolas,monospace', fontSize: 11, attributionLogo: true },
      grid: { vertLines: { color: COL.grid }, horzLines: { color: COL.grid } }, rightPriceScale: { borderColor: COL.line, scaleMargins: { top: 0.06, bottom: volume ? 0.2 : 0.06 } },
      timeScale: { borderColor: COL.line, timeVisible: true, secondsVisible: false, rightOffset: 6 }, crosshair: { mode: 0 }, autoSize: true,
    });
    this.candles = this.chart.addSeries(LW.CandlestickSeries, { upColor: COL.up, downColor: COL.dn, borderUpColor: COL.up, borderDownColor: COL.dn, wickUpColor: COL.up, wickDownColor: COL.dn });
    this.vol = volume ? this.chart.addSeries(LW.HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "vol", color: "#2a3340" }) : null;
    if (this.vol) this.chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.84, bottom: 0 } });
    this.markers = LW.createSeriesMarkers ? LW.createSeriesMarkers(this.candles, []) : null;
    const redraw = () => this.queue();
    this.chart.timeScale().subscribeVisibleLogicalRangeChange(redraw);
    for (const ev of ["wheel", "pointermove", "pointerup", "dblclick"]) this.lw.addEventListener(ev, redraw, { passive: true });
    new ResizeObserver(redraw).observe(this.box);
    this.chart.subscribeCrosshairMove((p) => this.cross(p));
  }
  cross(p) {
    const d = p && p.seriesData && p.seriesData.get(this.candles);
    if (!d) { this.legend.textContent = this.last ? this.fmt(this.last) : ""; return; }
    this.legend.textContent = this.fmt(d);
  }
  fmt(d) { const f = (x) => (isNum(x) ? x.toFixed(Math.abs(x) < 50 ? 5 : 2) : "—"); return `O ${f(d.open)}  H ${f(d.high)}  L ${f(d.low)}  C ${f(d.close)}`; }
  setData(candles) {
    this.data = candles; this.candles.setData(candles.map(({ time, open, high, low, close }) => ({ time, open, high, low, close })));
    if (this.vol) this.vol.setData(candles.map((c) => ({ time: c.time, value: c.volume || 0, color: c.close >= c.open ? "rgba(38,194,129,.28)" : "rgba(240,80,77,.28)" })));
    this.last = candles.length ? candles[candles.length - 1] : null; if (this.last) this.legend.textContent = this.fmt(this.last);
    this.queue();
  }
  fit() { this.chart.timeScale().fitContent(); this.queue(); }
  focus(t0, t1) { if (!this.data || !this.data.length) return; const span = Math.max(t1 - t0, 3600 * 3); this.chart.timeScale().setVisibleRange({ from: t0 - span * 1.2, to: t1 + span * 1.2 }); this.queue(); }
  setLevels(levels) { /* levels : [{price,color,title,style}] */
    for (const l of this.lines) this.candles.removePriceLine(l); this.lines = [];
    for (const l of levels) if (isNum(l.price)) this.lines.push(this.candles.createPriceLine({ price: l.price, color: l.color, lineWidth: 1, lineStyle: l.style ?? 2, axisLabelVisible: true, title: l.title }));
  }
  setMarkers(ms) { if (this.markers) this.markers.setMarkers(ms.slice().sort((a, b) => a.time - b.time)); }
  setZones(zones) { this.zones = zones || []; this.queue(); }
  queue() { if (this._raf) return; this._raf = requestAnimationFrame(() => { this._raf = 0; this.drawZones(); }); }
  drawZones() {
    const cv = this.cv, r = this.box.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
    if (cv.width !== Math.round(r.width * dpr) || cv.height !== Math.round(r.height * dpr)) { cv.width = Math.round(r.width * dpr); cv.height = Math.round(r.height * dpr); cv.style.width = r.width + "px"; cv.style.height = r.height + "px"; }
    const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, r.width, r.height);
    if (!this.showZones || !this.zones.length || !this.data || !this.data.length) return;
    const ts = this.chart.timeScale(), W = r.width - 70, t0 = this.data[0].time;
    const X = (t) => { const x = ts.timeToCoordinate(Math.max(t, t0)); return x == null ? (t < t0 ? 0 : null) : x; };
    for (const z of this.zones) {
      const x0 = X(z.t0), x1 = X(z.t1); if (x0 == null || x1 == null) continue;
      const a = Math.min(x0, W), b = Math.min(Math.max(x1, a + 3), W); if (b <= 0 || a >= W) continue;
      const bull = z.dir === "bullish", live = z.open, base = bull ? "38,194,129" : "240,80,77";
      const rect = (lo, hi, fill, stroke, dash) => {
        const yA = this.candles.priceToCoordinate(hi), yB = this.candles.priceToCoordinate(lo); if (yA == null || yB == null) return;
        g.fillStyle = `rgba(${fill})`; g.fillRect(a, yA, b - a, yB - yA); g.setLineDash(dash || []); g.strokeStyle = `rgba(${stroke})`; g.lineWidth = 1; g.strokeRect(a + .5, yA + .5, b - a - 1, yB - yA - 1);
      };
      rect(z.ob[0], z.ob[1], `${base},${live ? .22 : .10}`, `${base},${live ? .8 : .35}`);                          // Order Block
      rect(z.fvg[0], z.fvg[1], `224,164,58,${live ? .20 : .09}`, `224,164,58,${live ? .85 : .35}`, [4, 3]);       // Fair Value Gap
      const yc = this.candles.priceToCoordinate(z.ce);
      if (yc != null) { g.setLineDash([2, 3]); g.strokeStyle = `rgba(${base},.7)`; g.beginPath(); g.moveTo(a, yc); g.lineTo(b, yc); g.stroke(); }
      const yT = this.candles.priceToCoordinate(z.ob[1]); g.setLineDash([]); g.fillStyle = `rgba(${base},.95)`; g.font = '10px "JetBrains Mono",Consolas,monospace';
      if (yT != null && b - a > 40) g.fillText(`OB${bull ? "▲" : "▼"} + FVG${live ? "" : " · " + (z.status || "")}`, a + 4, yT - 3);
    }
    g.setLineDash([]);
  }
  destroy() { this.chart.remove(); this.box.remove(); }
}
export function tradeMarkers(trades) {
  const out = [];
  for (const t of trades) {
    out.push({ time: t.t0, position: t.side === "long" ? "belowBar" : "aboveBar", color: t.side === "long" ? "#4c8dff" : "#e0a43a", shape: t.side === "long" ? "arrowUp" : "arrowDown", text: t.side === "long" ? "BUY" : "SELL" });
    if (isNum(t.t1)) out.push({ time: t.t1, position: t.side === "long" ? "aboveBar" : "belowBar", color: t.r > 0 ? "#26c281" : "#f0504d", shape: "circle", text: (t.r > 0 ? "+" : "") + (isNum(t.r) ? t.r.toFixed(2) : "") + "R" });
  }
  return out;
}
