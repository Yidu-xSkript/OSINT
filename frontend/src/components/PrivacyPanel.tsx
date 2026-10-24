import { useEffect, useState } from 'react'
import { api } from '../api'
import type { Setting, Transform } from '../types'

// Where does this investigation's data go? Nothing leaves the machine until you RUN something — viewing the
// graph is local. This popover makes the current data-flow posture explicit (reviewer §9E).
export default function PrivacyPanel({ transforms, onClose }: { transforms: Transform[]; onClose: () => void }) {
  const [settings, setSettings] = useState<Setting[] | null>(null)
  useEffect(() => { api.settings().then(setSettings).catch(() => setSettings([])) }, [])

  const val = (name: string) => settings?.find((s) => s.name === name)?.value ?? null
  const has = (name: string) => !!settings?.some((s) => s.name === name)
  const provider = (val('ai.provider') || 'anthropic').toLowerCase()
  const aiOn = provider === 'openai' ? (has('openai.apikey') || !!val('openai.baseurl')) : has('anthropic.apikey')
  const aiDest = provider === 'openai'
    ? (() => { try { return new URL(val('openai.baseurl') || 'https://api.openai.com').host } catch { return 'your configured endpoint' } })()
    : 'api.anthropic.com (Anthropic)'

  const keyless = transforms.filter((t) => (t.credentialSettings?.length ?? 0) === 0).length

  const dot = (color: string) => <span className={`mt-1 inline-block h-2 w-2 shrink-0 rounded-full ${color}`} />
  const Row = ({ c, title, children }: { c: string; title: string; children: React.ReactNode }) => (
    <div className="flex gap-2 py-1.5">{dot(c)}<div><div className="font-medium text-zinc-200">{title}</div><div className="text-zinc-400">{children}</div></div></div>
  )

  return (
    <div className="absolute right-3 top-3 z-20 max-h-[70vh] w-96 overflow-auto rounded border border-zinc-700 bg-zinc-900 p-3 text-xs shadow-xl">
      <div className="mb-2 flex justify-between text-zinc-500"><span className="uppercase tracking-wider">Data flow</span><button onClick={onClose} className="hover:text-white">✕</button></div>
      {settings === null ? <p className="p-2 text-zinc-500">Loading…</p> : <>
        <Row c="bg-green-500" title="Stays on this machine">
          Cases, entities, evidence and notes live in a local SQLite database. API keys are sealed at rest
          {' '}(Windows DPAPI) and never sent to the browser. Viewing or arranging the graph makes no network calls.
        </Row>
        <Row c="bg-amber-500" title="Leaves your machine when you run a transform">
          Most transforms query a third-party source over the network (DNS, crt.sh, Shodan, VirusTotal…). A few are
          fully offline (libphonenumber parse, Sun position). {keyless} of {transforms.length} transforms need no API key.
        </Row>
        <Row c={aiOn ? 'bg-rose-500' : 'bg-zinc-600'} title={aiOn ? 'AI assist sends data off-machine' : 'AI assist is off'}>
          {aiOn
            ? <>When you use ✨ AI, the selected entities / pasted text are sent to <b>{aiDest}</b>. Content collected during an investigation is treated as untrusted and the model is told not to act on instructions hidden in it.</>
            : <>No model is configured, so nothing is sent to any AI service. Configure a provider (including a local open-weight server) under Transforms → API Keys.</>}
        </Row>
        <p className="mt-2 border-t border-zinc-800 pt-2 text-[11px] text-zinc-500">
          Choose the most privacy-preserving providers for your case; a key in a transform URL is redacted before it is stored in the evidence trail.
        </p>
      </>}
    </div>
  )
}
