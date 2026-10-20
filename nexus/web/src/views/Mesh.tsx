import { useEffect, useRef, useState } from 'react'
import { Tag, usePoll } from '../ui'

interface N { id: string; type: string; label: string; status: string; kind?: string; x: number; y: number; vx: number; vy: number; fixed?: boolean }
interface E { source: string; target: string; kind: string }
const W = 1000, H = 560
const COLOR: Record<string, string> = {
  up: 'var(--ok)', succeeded: 'var(--ok)', down: 'var(--err)', failed: 'var(--err)', awaiting_approval: 'var(--warn)', degraded: 'var(--warn)',
  running: 'var(--run)', queued: 'var(--idle)', draft: 'var(--idle)', cancelled: 'var(--idle)', unknown: 'var(--idle)', disabled: 'var(--idle)',
}

export default function Mesh() {
  const { data } = usePoll<{ nodes: any[]; edges: E[] }>('/views/mesh', 4000)
  const nodes = useRef<Map<string, N>>(new Map())
  const [, tick] = useState(0)
  const [sel, setSel] = useState<string | null>(null)
  const drag = useRef<string | null>(null)
  const svg = useRef<SVGSVGElement>(null)
  const edges = data?.edges || []

  useEffect(() => {
    if (!data) return
    const m = nodes.current
    const ids = new Set(data.nodes.map((n) => n.id))
    for (const k of [...m.keys()]) if (!ids.has(k)) m.delete(k)
    data.nodes.forEach((n, i) => {
      const old = m.get(n.id)
      const a = (i / Math.max(1, data.nodes.length)) * Math.PI * 2
      m.set(n.id, { ...n, x: old?.x ?? W / 2 + Math.cos(a) * 250, y: old?.y ?? H / 2 + Math.sin(a) * 200, vx: old?.vx ?? 0, vy: old?.vy ?? 0, fixed: old?.fixed })
    })
    tick((x) => x + 1)
  }, [data])

  useEffect(() => {   // simulation de forces minimale, sans dépendance
    let raf = 0, frames = 0
    const step = () => {
      const arr = [...nodes.current.values()]
      for (const a of arr) for (const b of arr) {
        if (a === b) continue
        const dx = a.x - b.x, dy = a.y - b.y, d2 = dx * dx + dy * dy + 0.01, f = 2400 / d2
        a.vx += (dx / Math.sqrt(d2)) * f; a.vy += (dy / Math.sqrt(d2)) * f
      }
      for (const e of edges) {
        const s = nodes.current.get(e.source), t = nodes.current.get(e.target)
        if (!s || !t) continue
        const dx = t.x - s.x, dy = t.y - s.y, d = Math.sqrt(dx * dx + dy * dy) || 1, f = (d - 90) * 0.02
        s.vx += (dx / d) * f; s.vy += (dy / d) * f; t.vx -= (dx / d) * f; t.vy -= (dy / d) * f
      }
      for (const n of arr) {
        n.vx += (W / 2 - n.x) * 0.002; n.vy += (H / 2 - n.y) * 0.002
        if (!n.fixed) { n.x = Math.min(W - 20, Math.max(20, n.x + n.vx)); n.y = Math.min(H - 20, Math.max(20, n.y + n.vy)) }
        n.vx *= 0.8; n.vy *= 0.8
      }
      if (++frames < 400 || drag.current) { tick((x) => x + 1); raf = requestAnimationFrame(step) }
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [data, edges])

  const pt = (e: React.PointerEvent) => {
    const r = svg.current!.getBoundingClientRect()
    return { x: ((e.clientX - r.left) / r.width) * W, y: ((e.clientY - r.top) / r.height) * H }
  }
  if (!data) return <p className="muted">Chargement…</p>
  const list = [...nodes.current.values()]
  const picked = sel ? nodes.current.get(sel) : null
  return (
    <>
      <p className="muted small">Graphe construit à partir des services, agents, tâches et dépendances réellement enregistrés. Cliquer un nœud pour le détail ; glisser pour le déplacer.</p>
      <svg ref={svg} className="mesh" viewBox={`0 0 ${W} ${H}`}
        onPointerMove={(e) => { if (drag.current) { const n = nodes.current.get(drag.current); if (n) { const p = pt(e); n.x = p.x; n.y = p.y; tick((x) => x + 1) } } }}
        onPointerUp={() => { drag.current = null }}>
        {edges.map((e, i) => {
          const s = nodes.current.get(e.source), t = nodes.current.get(e.target)
          return s && t ? <line key={i} x1={s.x} y1={s.y} x2={t.x} y2={t.y} stroke="var(--line)" strokeWidth={e.kind === 'depends_on' ? 1.6 : 1} strokeDasharray={e.kind === 'runs_on' ? '4 3' : undefined} /> : null
        })}
        {list.map((n) => (
          <g key={n.id} transform={`translate(${n.x},${n.y})`} style={{ cursor: 'pointer' }}
            onPointerDown={(e) => { drag.current = n.id; n.fixed = true; setSel(n.id); (e.target as Element).setPointerCapture?.(e.pointerId) }}>
            {n.type === 'service' ? <rect x={-9} y={-9} width={18} height={18} rx={3} fill={COLOR[n.status] || 'var(--idle)'} />
              : n.type === 'agent' ? <polygon points="0,-11 10,7 -10,7" fill={COLOR[n.status] || 'var(--idle)'} />
              : <circle r={6} fill={COLOR[n.status] || 'var(--idle)'} />}
            {sel === n.id && <circle r={14} fill="none" stroke="var(--text)" />}
            <text x={12} y={4}>{n.label.length > 26 ? n.label.slice(0, 25) + '…' : n.label}</text>
          </g>))}
      </svg>
      <div className="row small muted" style={{ marginTop: 8 }}>■ service · ▲ agent · ● tâche · trait pointillé : s'exécute sur · trait plein : dépend de / appartient à</div>
      {picked && <div className="card" style={{ marginTop: 10 }}><b>{picked.label}</b> <Tag s={picked.status} /> <span className="muted small">{picked.type}{picked.kind ? ` · ${picked.kind}` : ''} · {picked.id}</span></div>}
    </>
  )
}
