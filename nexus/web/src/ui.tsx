import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from './api'

export const Dot = ({ s }: { s: string }) => <span className={`dot s-${s}`} />
export const Tag = ({ s, children }: { s: string; children?: React.ReactNode }) => <span className={`tag s-${s}`}>{children ?? s}</span>
export const fmtDate = (v?: string | null) => (v ? new Date(v).toLocaleString('fr-FR') : '—')
export const euros = (cents: number) => (cents / 100).toLocaleString('fr-FR', { style: 'currency', currency: 'EUR' })
export const errText = (e: unknown) => (e instanceof ApiError ? `${e.message} (${e.code})` : String(e))

/** Charge une ressource et la rafraîchit toutes les `every` ms tant que le composant est affiché. */
export function usePoll<T>(path: string, every = 5000) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState('')
  const load = useCallback(async () => {
    try { setData(await api<T>(path)); setError('') } catch (e) { setError(errText(e)) }
  }, [path])
  useEffect(() => {
    load()
    const t = setInterval(load, every)
    return () => clearInterval(t)
  }, [load, every])
  return { data, error, reload: load }
}

export function useAction() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
  const run = async (fn: () => Promise<unknown>, okMsg = '') => {
    setBusy(true); setError(''); setInfo('')
    try { await fn(); setInfo(okMsg) } catch (e) { setError(errText(e)) } finally { setBusy(false) }
  }
  return { busy, error, info, run }
}

export function Modal({ children, onClose }: { children: React.ReactNode; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => { const k = (e: KeyboardEvent) => e.key === 'Escape' && onClose(); window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k) }, [onClose])
  return <div className="modal" onClick={onClose}><div ref={ref} onClick={(e) => e.stopPropagation()}>{children}<p><button className="btn" onClick={onClose}>Fermer</button></p></div></div>
}
