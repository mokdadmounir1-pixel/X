import { useEffect, useState } from 'react'
import { api, hasToken, Me, setToken } from './api'
import { fmtDate, useAction, usePoll } from './ui'
import OmniBox from './OmniBox'
import Executive from './views/Executive'
import Forge from './views/Forge'
import Agency from './views/Agency'
import Mesh from './views/Mesh'
import Journal from './views/Journal'

const VIEWS = [['exec', 'Vue exécutive'], ['forge', 'Forge Quant'], ['agency', 'Agence'], ['mesh', 'Mesh'], ['journal', 'Journal']] as const

function Login({ onLogin }: { onLogin: () => void }) {
  const [u, setU] = useState('')
  const [p, setP] = useState('')
  const act = useAction()
  return (
    <form className="login" onSubmit={(e) => { e.preventDefault(); act.run(async () => { const r = await api('/auth/login', { method: 'POST', body: { username: u, password: p } }); setToken(r.token); onLogin() }) }}>
      <div className="brand">NEXUS</div>
      <input aria-label="Identifiant" placeholder="Identifiant" autoComplete="username" value={u} onChange={(e) => setU(e.target.value)} />
      <input aria-label="Mot de passe" type="password" placeholder="Mot de passe" autoComplete="current-password" value={p} onChange={(e) => setP(e.target.value)} />
      <button className="btn primary" disabled={act.busy || !u || !p}>Connexion</button>
      {act.error && <div className="err">{act.error}</div>}
      <p className="muted small">Accès local. Les comptes se créent en ligne de commande (voir le guide de démarrage) : il n'existe aucun compte par défaut.</p>
    </form>
  )
}

export default function App() {
  const [auth, setAuth] = useState(hasToken())
  const [me, setMe] = useState<Me | null>(null)
  const [view, setView] = useState<(typeof VIEWS)[number][0]>('exec')
  const [rev, setRev] = useState(0)
  const em = usePoll<any>(auth ? '/emergency' : '/health', 3000)
  const act = useAction()

  useEffect(() => { const h = () => { setAuth(false); setMe(null) }; window.addEventListener('nx-logout', h); return () => window.removeEventListener('nx-logout', h) }, [])
  useEffect(() => { if (auth) api<Me>('/auth/me').then(setMe).catch(() => setAuth(false)) }, [auth])

  if (!auth) return <Login onLogin={() => setAuth(true)} />
  if (!me) return <p className="muted" style={{ padding: 20 }}>Chargement…</p>
  const stopped = !!em.data?.emergency_stop
  const stop = () => {
    const reason = window.prompt("Arrêt d'urgence : motif (obligatoire). Les tâches non démarrées seront annulées, aucune nouvelle action ne partira.")
    if (reason && reason.length >= 3) act.run(async () => { await api('/emergency/stop', { method: 'POST', body: { reason } }); em.reload() })
  }
  const rearm = () => {
    if (window.confirm("Réarmer le système ? Les nouvelles actions seront de nouveau possibles.")) act.run(async () => { await api('/emergency/rearm', { method: 'POST', body: { confirm: 'REARMER' } }); em.reload() })
  }
  const rep = em.data?.report
  return (
    <>
      <header className="top">
        <span className="brand">NEXUS</span>
        <nav>{VIEWS.map(([k, label]) => <button key={k} aria-current={view === k} onClick={() => setView(k)}>{label}</button>)}</nav>
        <span className="spacer" />
        <span className="muted small">{me.username} · {me.role}</span>
        {!stopped && me.role !== 'lecture' && <button className="btn danger" onClick={stop}>Arrêt d'urgence</button>}
        <button className="btn" onClick={() => { api('/auth/logout', { method: 'POST' }).catch(() => undefined); setToken(''); setAuth(false); setMe(null) }}>Déconnexion</button>
      </header>
      {stopped && (
        <div className="banner" role="alert">
          <b>ARRÊT D'URGENCE ACTIF</b> depuis {fmtDate(em.data.stopped_at)} — {em.data.reason}
          <span>annulées : {rep?.cancelled?.length ?? 0} · en cours (arrêt demandé) : {rep?.still_running?.length ?? 0} · actions externes déjà effectuées : {rep?.external_actions_already_done?.length ?? 0}</span>
          <span className="spacer" />
          {me.role === 'fondateur' ? <button className="btn" onClick={rearm}>Réarmer</button> : <span className="small">Réarmement : Fondateur uniquement</span>}
        </div>)}
      {act.error && <div className="err" style={{ padding: '0 20px' }}>{act.error}</div>}
      <main>
        <OmniBox role={me.role} onDone={() => setRev(rev + 1)} />
        <div key={`${view}-${rev}`}>
          {view === 'exec' && <Executive role={me.role} />}
          {view === 'forge' && <Forge role={me.role} />}
          {view === 'agency' && <Agency role={me.role} />}
          {view === 'mesh' && <Mesh />}
          {view === 'journal' && <Journal />}
        </div>
      </main>
    </>
  )
}
