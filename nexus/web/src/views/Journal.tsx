import { useState } from 'react'
import { api } from '../api'
import { Tag, fmtDate, useAction, usePoll } from '../ui'

export default function Journal() {
  const [outcome, setOutcome] = useState('')
  const { data, error } = usePoll<any[]>(`/audit?limit=300${outcome ? `&outcome=${outcome}` : ''}`, 4000)
  const [verify, setVerify] = useState<any>(null)
  const act = useAction()
  const inc = usePoll<any[]>('/incidents', 15000)
  return (
    <>
      <div className="row">
        <select style={{ width: 'auto' }} value={outcome} onChange={(e) => setOutcome(e.target.value)}>
          <option value="">Tous les résultats</option><option value="ok">ok</option><option value="denied">refusés</option><option value="error">erreurs</option>
        </select>
        <button className="btn" disabled={act.busy} onClick={() => act.run(async () => setVerify(await api('/audit/verify')))}>Vérifier la chaîne d'empreintes</button>
        {verify && (verify.ok ? <span className="ok">Chaîne saine — {verify.events} événements</span> : <span className="err">ALTÉRATION détectée à partir de l'événement n°{verify.first_bad_seq}</span>)}
      </div>
      {(error || act.error) && <div className="err">{error || act.error}</div>}
      <h2>Incidents (incident → cause racine → correctif → tests → revue → déploiement)</h2>
      <div className="tablewrap"><table><thead><tr><th>Gravité</th><th>Titre</th><th>Étape</th><th>Cause racine</th></tr></thead>
        <tbody>{(inc.data || []).map((i) => <tr key={i.id}><td>{i.severity}</td><td>{i.title}</td><td>{i.status}</td><td className="small">{i.root_cause || '—'}</td></tr>)}
          {(inc.data || []).length === 0 && <tr><td colSpan={4} className="muted">Aucun incident.</td></tr>}</tbody></table></div>
      <h2>Journal (append-only)</h2>
      <div className="tablewrap"><table><thead><tr><th>#</th><th>Date</th><th>Acteur</th><th>Action</th><th>Objet</th><th>Résultat</th><th>Détails</th></tr></thead>
        <tbody>{(data || []).map((e) => (
          <tr key={e.seq}><td>{e.seq}</td><td className="small">{fmtDate(e.ts)}</td><td>{e.actor}</td><td>{e.action}</td>
            <td className="small">{e.entity_type}{e.entity_id ? ` ${String(e.entity_id).slice(0, 8)}` : ''}</td><td><Tag s={e.outcome} /></td>
            <td className="small"><code>{JSON.stringify(e.details)}</code></td></tr>))}</tbody></table></div>
    </>
  )
}
