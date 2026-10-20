import { api, Role } from '../api'
import { Tag, fmtDate, useAction, usePoll } from '../ui'

export default function Approvals({ role }: { role: Role }) {
  const { data, reload } = usePoll<any[]>('/approvals?status=pending')
  const act = useAction()
  const live = (data || []).filter((a) => new Date(a.expires_at) > new Date())
  const decide = (id: string, decision: 'approve' | 'reject') => act.run(async () => { await api(`/approvals/${id}/decide`, { method: 'POST', body: { decision } }); reload() })
  return (
    <>
      <h2>Approbations en attente</h2>
      {act.error && <div className="err">{act.error}</div>}
      {live.length === 0 ? <p className="muted">Aucune.</p> : (
        <div className="tablewrap"><table>
          <thead><tr><th>Action</th><th>Paramètres</th><th>Empreinte</th><th>Expire</th><th /></tr></thead>
          <tbody>{live.map((a) => (
            <tr key={a.id}>
              <td><Tag s="pending">{a.action}</Tag><div className="small muted">{a.title}</div></td>
              <td><code className="small">{JSON.stringify(a.params)}</code></td>
              <td><code className="small">{a.params_hash.slice(0, 12)}</code></td>
              <td className="small">{fmtDate(a.expires_at)}</td>
              <td>{role === 'fondateur' ? (<div className="row">
                <button className="btn primary" disabled={act.busy} onClick={() => decide(a.id, 'approve')}>Approuver</button>
                <button className="btn danger" disabled={act.busy} onClick={() => decide(a.id, 'reject')}>Refuser</button></div>)
                : <span className="muted small">Fondateur requis</span>}</td>
            </tr>))}</tbody>
        </table></div>)}
      <p className="muted small">Approbation liée à l'action, à ses paramètres (empreinte) et à une expiration. Toute modification l'invalide. Aucun envoi externe en v0.1.</p>
    </>
  )
}
