import { useState } from 'react'
import { api, newKey, Role, rank } from './api'
import { Tag, useAction } from './ui'

export default function OmniBox({ role, onDone }: { role: Role; onDone: () => void }) {
  const [text, setText] = useState('')
  const [prev, setPrev] = useState<any>(null)
  const [result, setResult] = useState<any>(null)
  const [key, setKey] = useState(newKey())
  const act = useAction()
  const interpret = () => act.run(async () => { setResult(null); setPrev(await api('/omnibox/interpret', { method: 'POST', body: { text } })) })
  const confirm = () => act.run(async () => {
    const r = await api('/omnibox/execute', { method: 'POST', key, body: { intent: prev.intent, params: prev.params, confirm: true } })
    setResult(r); setPrev(null); setText(''); setKey(newKey()); onDone()
  })
  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <form className="row" onSubmit={(e) => { e.preventDefault(); if (text.trim()) interpret() }}>
        <input aria-label="Omni-Box" placeholder="Omni-Box — ex. « montre l'état », « lance une expérience de démonstration », « crée une tâche : relire le rapport »" value={text} maxLength={500} onChange={(e) => { setText(e.target.value); setPrev(null) }} />
        <button className="btn primary" disabled={act.busy || !text.trim()}>Interpréter</button>
      </form>
      {act.error && <div className="err">{act.error}</div>}
      {prev && (
        <div style={{ marginTop: 10 }}>
          <div className="small muted">Intention proposée par le modèle — validée par le serveur</div>
          <p><b>{prev.intent}</b> <code className="small">{JSON.stringify(prev.params)}</code> {prev.requires_approval && <Tag s="awaiting_approval">approbation du Fondateur requise</Tag>}</p>
          <p>{prev.effect}</p>
          <div className="row">
            <button className="btn primary" disabled={act.busy || (prev.intent !== 'show_status' && rank[role] < 1)} onClick={confirm}>{prev.requires_approval ? 'Créer la demande' : 'Confirmer'}</button>
            <button className="btn" onClick={() => setPrev(null)}>Annuler</button>
          </div>
        </div>)}
      {result && (
        <div style={{ marginTop: 10 }}>
          {result.tasks ? <span className="ok">Créé : {result.tasks.map((t: any) => `${t.kind} (${t.status})`).join(' → ')}</span> : <pre>{JSON.stringify(result.result, null, 2)}</pre>}
        </div>)}
    </div>
  )
}
