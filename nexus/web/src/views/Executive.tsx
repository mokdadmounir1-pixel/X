import { useState } from 'react'
import { api, newKey, Role, rank } from '../api'
import { Dot, Tag, euros, fmtDate, useAction, usePoll } from '../ui'
import Approvals from './Approvals'

function Ceo({ role }: { role: Role }) {
  const { data, reload } = usePoll<any>('/ceo', 15000)
  const act = useAction()
  const [draft, setDraft] = useState<Record<string, string>>({})
  const labels: Record<string, string> = { decision_prioritaire: 'Décision prioritaire', action_livree: 'Action livrée', revue_fin_journee: 'Revue de fin de journée' }
  const save = (kind: string, text: string, done: boolean) => act.run(async () => { await api(`/ceo/${kind}`, { method: 'PUT', body: { text: text || null, done } }); reload() })
  return (
    <>
      <h2>Engagements du jour (facultatifs, locaux)</h2>
      <div className="grid">
        {(data?.commitments || []).map((c: any) => (
          <div className="card" key={c.kind}>
            <div className="small muted">{labels[c.kind]}</div>
            <input disabled={rank[role] < 1} placeholder="(facultatif)" value={draft[c.kind] ?? c.text ?? ''} onChange={(e) => setDraft({ ...draft, [c.kind]: e.target.value })} />
            <div className="row" style={{ marginTop: 8 }}>
              <label className="small"><input type="checkbox" style={{ width: 'auto' }} disabled={rank[role] < 1} checked={c.done} onChange={(e) => save(c.kind, draft[c.kind] ?? c.text ?? '', e.target.checked)} /> fait</label>
              <button className="btn" disabled={rank[role] < 1 || act.busy} onClick={() => save(c.kind, draft[c.kind] ?? c.text ?? '', c.done)}>Enregistrer</button>
            </div>
          </div>))}
      </div>
      {act.error && <div className="err">{act.error}</div>}
    </>
  )
}

function Council({ role }: { role: Role }) {
  const [q, setQ] = useState('')
  const [sid, setSid] = useState('')
  const act = useAction()
  const { data } = usePoll<any>(sid ? `/council/${sid}` : '/health', 4000)
  const s = sid ? data : null
  return (
    <>
      <h2>Conseil — proposition, contre-analyse, synthèse</h2>
      <div className="row">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Question soumise au conseil" />
        <button className="btn" disabled={rank[role] < 1 || q.length < 5 || act.busy} onClick={() => act.run(async () => { const r = await api('/demo/council', { method: 'POST', body: { question: q }, key: newKey() }); setSid(r.session_id) })}>Convoquer</button>
      </div>
      {act.error && <div className="err">{act.error}</div>}
      {s && (
        <div className="grid" style={{ marginTop: 12 }}>
          <div className="card"><div className="small muted">Proposition</div><p>{s.proposal || '…'}</p></div>
          <div className="card"><div className="small muted">Contre-analyse</div><p>{s.counter || '…'}</p></div>
          <div className="card"><div className="small muted">Synthèse (désaccords conservés)</div>
            {s.synthesis ? (<><b>Désaccords</b><ul>{s.synthesis.disagreements.map((d: string, i: number) => <li key={i}>{d}</li>)}</ul>
              <b>Accords</b><ul>{s.synthesis.agreements.map((d: string, i: number) => <li key={i}>{d}</li>)}</ul>
              <p className="small muted">{s.synthesis.note}</p></>) : <p>…</p>}</div>
        </div>)}
    </>
  )
}

export default function Executive({ role }: { role: Role }) {
  const { data: d, error } = usePoll<any>('/views/executive')
  if (error) return <div className="err">{error}</div>
  if (!d) return <p className="muted">Chargement…</p>
  const t = d.tasks_by_status as Record<string, number>
  return (
    <>
      <h2>Services</h2>
      <p><button className="btn" disabled={rank[role] < 1} onClick={() => api('/services/probe', { method: 'POST' })}>Vérifier maintenant</button> <span className="muted small">Sondage automatique toutes les 30 s.</span></p>
      <div className="grid">{d.services.map((s: any) => (
        <div className="card" key={s.id}><Dot s={s.status} /><b>{s.name}</b>
          <div className="small muted">{s.status}{s.detail ? ` — ${s.detail}` : ''} · vérifié {fmtDate(s.checked_at)}</div></div>))}</div>
      <h2>Tâches</h2>
      <div className="row">{['draft', 'queued', 'awaiting_approval', 'running', 'succeeded', 'failed', 'cancelled'].map((k) => <Tag key={k} s={k}>{k} · {t[k] || 0}</Tag>)}</div>
      <h2>Tâches bloquées</h2>
      {d.blocked_tasks.length === 0 ? <p className="muted">Aucune.</p> : (
        <div className="tablewrap"><table><thead><tr><th>Tâche</th><th>État</th><th>Erreur</th><th>Créée</th></tr></thead>
          <tbody>{d.blocked_tasks.map((b: any) => <tr key={b.id}><td>{b.title}<div className="small muted">{b.kind}</div></td><td><Tag s={b.status} /></td><td className="small">{b.error_code || ''}</td><td className="small">{fmtDate(b.created_at)}</td></tr>)}</tbody></table></div>)}
      <h2>Finances et pipeline</h2>
      <div className="grid">
        <div className="card"><div className="small muted">Dépenses documentées</div><div className="big">{euros(d.expenses_documented_cents)}</div><div className="small muted">non documentées : {euros(d.expenses_undocumented_cents)}</div></div>
        <div className="card"><div className="small muted">Encaissements documentés</div><div className="big">{euros(d.payments_documented_cents)}</div></div>
        <div className="card"><div className="small muted">Pipeline</div><div className="big">{d.pipeline.prospects} prospect(s)</div>
          <div className="small muted">{Object.entries(d.pipeline.proposals_by_status).map(([k, v]) => `${k}: ${v}`).join(' · ') || 'aucune proposition'}</div></div>
      </div>
      <Approvals role={role} />
      <Ceo role={role} />
      <Council role={role} />
    </>
  )
}
