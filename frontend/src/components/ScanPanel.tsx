import { useEffect, useState } from 'react'
import { api } from '../api'

// Authorized network scan: the analyst must give an explicit target scope, pick a fixed profile, see the
// exact command, and confirm authorization before anything runs. Discovered IPs never auto-scan — a scan
// only ever covers what's typed here.
type Profile = { id: string; label: string; args: string[] }

export default function ScanPanel({ seed, onRun, onFail, onClose }: {
  seed: string
  onRun: (targets: string[], profile: string) => Promise<void>
  onFail: (e: unknown) => void
  onClose: () => void
}) {
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [profile, setProfile] = useState('fast')
  const [text, setText] = useState(seed)
  const [authorized, setAuthorized] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.scanProfiles().then((p) => { setProfiles(p); if (!p.some((x) => x.id === 'fast') && p[0]) setProfile(p[0].id) }).catch(onFail)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const targets = text.split(/[\n,]+/).map((s) => s.trim()).filter(Boolean)
  const cur = profiles.find((p) => p.id === profile)
  const command = cur ? `nmap ${cur.args.join(' ')} -oX - ${targets.join(' ')}` : ''

  const run = async () => {
    setBusy(true)
    try { await onRun(targets, profile); onClose() } catch (e) { onFail(e) } finally { setBusy(false) }
  }

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/60" onMouseDown={onClose}>
      <div className="flex max-h-[85vh] w-[560px] flex-col rounded-lg border border-zinc-700 bg-zinc-900" onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 border-b border-zinc-800 p-2">
          <span className="font-semibold text-rose-300">⊙ Authorized Network Scan (Nmap)</span>
          <button className="ml-auto px-2 text-zinc-400 hover:text-white" onClick={onClose}>✕</button>
        </div>
        <div className="overflow-auto p-4 text-sm">
          <p className="mb-3 rounded border border-rose-800/60 bg-rose-950/40 p-2 text-xs text-rose-200">
            Scan only systems you own or are <b>explicitly authorized</b> to assess. Unauthorized scanning may be
            illegal. Nothing runs until you confirm authorization below; discovered hosts are never scanned automatically.
          </p>

          <label className="mb-1 block text-xs text-zinc-400">Targets (one per line — hostname, IP, or CIDR)</label>
          <textarea className="field mb-3 h-24 font-mono" value={text} onChange={(e) => setText(e.target.value)}
            placeholder={'example.com\n192.0.2.0/24'} />

          <label className="mb-1 block text-xs text-zinc-400">Scan profile</label>
          <select className="field mb-3" value={profile} onChange={(e) => setProfile(e.target.value)}>
            {profiles.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
          </select>

          <label className="mb-1 block text-xs text-zinc-400">Command preview</label>
          <div className="mb-1 break-all rounded border border-zinc-800 bg-zinc-950 p-2 font-mono text-xs text-zinc-300">{command || '—'}</div>
          <p className="mb-3 text-[11px] text-zinc-500">Unprivileged TCP connect scan. Scope cap: 32 targets / 256 addresses. No custom flags.</p>

          <label className="mb-3 flex items-start gap-2 text-xs text-zinc-300">
            <input type="checkbox" className="mt-0.5" checked={authorized} onChange={(e) => setAuthorized(e.target.checked)} />
            <span>I confirm I am authorized to scan {targets.length ? <b>{targets.length} target{targets.length > 1 ? 's' : ''}</b> : 'these targets'}.</span>
          </label>

          <div className="flex justify-end gap-2">
            <button className="btn" onClick={onClose}>Cancel</button>
            <button className="btn border-rose-600 text-rose-300 hover:border-rose-400"
              disabled={busy || !authorized || targets.length === 0} onClick={run}>
              {busy ? 'Scanning…' : 'Run scan'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
