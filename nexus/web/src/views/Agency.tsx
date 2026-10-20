import { useState } from 'react'
import { api, newKey, Role, rank } from '../api'
import { Tag, Modal, fmtDate, useAction, usePoll } from '../ui'
import Approvals from './Approvals'

export default function Agency({ role }: { role: Role }) {
  const { data: d, error, reload } = usePoll<any>('/views/agency')
  const act = useAction()
  const [name, setName] = useState('')
  const [sector, setSector] = useState('')
  const [issues, setIssues] = useState('')
  const [text, setText] = useState<string | null>(null)
  if (error) return <div className="err">{error}</div>
  if (!d) return <p className="muted">Chargement…</p>
  const submit = () => act.run(async () => {
    await api('/demo/agency', { method: 'POST', key: newKey(), body: { name, sector: sector || null, documented_issues: issues.split('\n').map((s) => s.trim()).filter(Boolean), is_fictional: true } })
    setName(''); setSector(''); setIssues(''); reload()
  })
  const show = (id: string) => act.run(async () => setText((await api(`/proposals/${id}`)).body_md))
  return (
    <>
      <div className="row"><span className="sim">DÉMO — aucun envoi externe</span><span className="muted small">Prospects fictifs uniquement dans cette version.</span></div>
      <h2>Importer un prospect fictif</h2>
      <div className="grid">
        <div><input placeholder="Nom (fictif)" value={name} onChange={(e) => setName(e.target.value)} /></div>
        <div><input placeholder="Secteur" value={sector} onChange={(e) => setSector(e.target.value)} /></div>
        <div style={{ gridColumn: '1 / -1' }}><textarea rows={3} placeholder="Problèmes documentés (un par ligne)" value={issues} onChange={(e) => setIssues(e.target.value)} /></div>
      </div>
      <p><button className="btn primary" disabled={rank[role] < 1 || !name || act.busy} onClick={submit}>Analyser et préparer un brouillon</button></p>
      {act.error && <div className="err">{act.error}</div>}
      <h2>Prospects</h2>
      <div className="tablewrap"><table><thead><tr><th>Nom</th><th>Secteur</th><th>Problèmes documentés</th><th>Fictif</th></tr></thead>
        <tbody>{d.prospects.map((p: any) => <tr key={p.id}><td>{p.name}</td><td>{p.sector || '—'}</td><td className="small">{p.documented_issues.join(' · ') || '—'}</td><td>{p.is_fictional ? 'oui' : 'non'}</td></tr>)}
          {d.prospects.length === 0 && <tr><td colSpan={4} className="muted">Aucun.</td></tr>}</tbody></table></div>
      <h2>Propositions</h2>
      <div className="tablewrap"><table><thead><tr><th>Prospect</th><th>État</th><th>Contrôle</th><th>Créée</th><th /></tr></thead>
        <tbody>{d.proposals.map((p: any) => <tr key={p.id}><td>{p.prospect}</td>
          <td><Tag s={p.status === 'awaiting_approval' ? 'awaiting_approval' : p.status === 'approved_not_sent' ? 'succeeded' : 'draft'}>{p.status}</Tag></td>
          <td className="small">{p.review ? (p.review.passed ? 'réussi' : 'refusé : ' + Object.entries(p.review.checks).filter(([, v]) => !v).map(([k]) => k).join(', ')) : '—'}</td>
          <td className="small">{fmtDate(p.created_at)}</td><td><button className="btn" onClick={() => show(p.id)}>Lire</button></td></tr>)}
          {d.proposals.length === 0 && <tr><td colSpan={5} className="muted">Aucune.</td></tr>}</tbody></table></div>
      <Approvals role={role} />
      {text !== null && <Modal onClose={() => setText(null)}><pre>{text}</pre></Modal>}
    </>
  )
}
