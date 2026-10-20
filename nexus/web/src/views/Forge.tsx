import { useState } from 'react'
import { api, newKey, Role, rank } from '../api'
import { Tag, fmtDate, useAction, usePoll } from '../ui'
import { Modal } from '../ui'

export default function Forge({ role }: { role: Role }) {
  const { data: d, error, reload } = usePoll<any>('/views/forge')
  const act = useAction()
  const [report, setReport] = useState<string | null>(null)
  const [seed, setSeed] = useState(42)
  if (error) return <div className="err">{error}</div>
  if (!d) return <p className="muted">Chargement…</p>
  const open = (id: string) => act.run(async () => setReport((await api(`/experiments/${id}/report`)).report_md))
  const f = (x: number | null | undefined) => (x === null || x === undefined ? '—' : x)
  return (
    <>
      <div className="row"><span className="sim">MODE SIMULATION</span><span className="muted small">Aucun ordre réel. Les résultats de démonstration ne valident aucune stratégie.</span></div>
      <h2>Expériences</h2>
      <div className="row" style={{ marginBottom: 10 }}>
        <label className="small muted">graine</label>
        <input type="number" style={{ width: 110, flex: 'none', minWidth: 0 }} value={seed} onChange={(e) => setSeed(Number(e.target.value))} />
        <button className="btn primary" disabled={rank[role] < 1 || act.busy} onClick={() => act.run(async () => { await api('/demo/quant', { method: 'POST', body: { seed }, key: newKey() }); reload() })}>Lancer une expérience de démonstration</button>
      </div>
      {act.error && <div className="err">{act.error}</div>}
      <div className="tablewrap"><table>
        <thead><tr><th>Stratégie</th><th>Jeu de données</th><th>État</th><th>Rend. net</th><th>Trades</th><th>PF</th><th>DD max</th><th>Achat-conservation</th><th /></tr></thead>
        <tbody>{d.experiments.map((e: any) => (
          <tr key={e.id}><td>{e.strategy} <span className="muted">{e.strategy_version}</span></td><td className="small">{e.dataset}<br />{e.dataset_version}</td>
            <td><Tag s={e.status === 'reported' ? 'succeeded' : 'running'}>{e.status}</Tag> <span className="sim">{e.mode}</span></td>
            <td>{f(e.metrics?.full.net_return_pct)} %</td><td>{f(e.metrics?.full.trades)}</td><td>{f(e.metrics?.full.profit_factor)}</td>
            <td>{f(e.metrics?.full.max_drawdown_pct)} %</td><td>{f(e.metrics?.full.buy_hold_pct)} %</td>
            <td>{e.has_report && <button className="btn" onClick={() => open(e.id)}>Rapport</button>}</td></tr>))}
          {d.experiments.length === 0 && <tr><td colSpan={9} className="muted">Aucune expérience.</td></tr>}</tbody></table></div>
      <h2>Jeux de données versionnés</h2>
      <div className="tablewrap"><table><thead><tr><th>Nom</th><th>Version</th><th>SHA-256</th><th>Lignes</th><th>Provenance</th></tr></thead>
        <tbody>{d.datasets.map((x: any) => <tr key={x.id}><td>{x.name}</td><td>{x.version}</td><td><code className="small">{x.sha256.slice(0, 16)}…</code></td><td>{x.rows}</td><td className="small">{x.provenance.type} — {x.provenance.note}</td></tr>)}
          {d.datasets.length === 0 && <tr><td colSpan={5} className="muted">Aucun.</td></tr>}</tbody></table></div>
      <h2>Versions de stratégies</h2>
      <div className="tablewrap"><table><thead><tr><th>Nom</th><th>Version</th><th>Définition</th><th>Statut</th></tr></thead>
        <tbody>{d.strategies.map((s: any) => <tr key={s.id}><td>{s.name}</td><td>{s.version}</td><td><code className="small">{JSON.stringify(s.definition)}</code></td><td><span className="sim">{s.status}</span></td></tr>)}
          {d.strategies.length === 0 && <tr><td colSpan={4} className="muted">Aucune.</td></tr>}</tbody></table></div>
      <h2>Dépôts ({d.repositories.length})</h2>
      <div className="tablewrap"><table><thead><tr><th>Nom</th><th>URL</th><th>Statut</th><th>Importé</th></tr></thead>
        <tbody>{d.repositories.map((r: any) => <tr key={r.id}><td>{r.name}</td><td className="small">{r.url || '—'}</td>
          <td><Tag s={r.status === 'audited' ? 'succeeded' : 'pending'}>{r.status === 'downloaded_unaudited' ? 'téléchargé, non audité' : r.status}</Tag></td><td className="small">{fmtDate(r.imported_at)}</td></tr>)}
          {d.repositories.length === 0 && <tr><td colSpan={4} className="muted">Aucun dépôt importé. Importer l'inventaire : <code>python -m app.cli import-repos &lt;inventaire.json&gt;</code></td></tr>}</tbody></table></div>
      {report !== null && <Modal onClose={() => setReport(null)}><pre>{report}</pre></Modal>}
    </>
  )
}
