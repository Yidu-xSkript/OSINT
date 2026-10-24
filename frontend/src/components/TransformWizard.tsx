import { useEffect, useState } from 'react'
import { api } from '../api'
import { ENTITY_TYPES, type EntityType, type Setting, type Tool, type Transform } from '../types'

const TOOL_STATE: Record<Tool['state'], { label: string; cls: string }> = {
  'built-in': { label: 'Built in', cls: 'bg-green-500/15 text-green-400' },
  available: { label: 'Available', cls: 'bg-green-500/15 text-green-400' },
  'needs-setup': { label: 'Needs setup', cls: 'bg-amber-500/15 text-amber-400' },
  'unsupported-version': { label: 'Unsupported version', cls: 'bg-rose-500/15 text-rose-400' },
  error: { label: 'Error', cls: 'bg-rose-500/15 text-rose-400' },
}

type Tab = 'list' | 'tools' | 'local' | 'remote' | 'keys'
const splitArgs = (s: string) => [...s.matchAll(/"([^"]*)"|(\S+)/g)].map((m) => m[1] ?? m[2])
const splitList = (s: string) => s.split(',').map((x) => x.trim()).filter(Boolean)

const BLANK = { name: '', inputType: 'Domain' as EntityType, description: '', linkLabel: '', settings: '', timeout: '60', command: 'python', args: '', workingDir: '', url: '' }

export default function TransformWizard({ transforms, onChanged, onClose, initialTab = 'list' }: { transforms: Transform[]; onChanged(): void; onClose(): void; initialTab?: Tab }) {
  const [tab, setTab] = useState<Tab>(initialTab)
  const [f, setF] = useState(BLANK)
  const [err, setErr] = useState('')
  const [settings, setSettings] = useState<Setting[]>([])
  const [aiSettings, setAiSettings] = useState<{ name: string; placeholder: string; secret: boolean }[]>([])
  const [key, setKey] = useState({ name: '', value: '', secret: true })
  const [toolList, setToolList] = useState<Tool[]>([])

  const loadSettings = () => api.settings().then(setSettings)
  useEffect(() => {
    loadSettings()
    api.tools().then(setToolList).catch(() => {})
    fetch('/api/ai/settings').then((r) => r.json()).then(setAiSettings).catch(() => {})
  }, [])

  const set = (k: keyof typeof BLANK) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value })
  const row = (label: string, k: keyof typeof BLANK, placeholder = '', hint = '') => (
    <label className="mb-2 block">
      <span className="text-xs text-zinc-400">{label}</span>
      <input className="field" value={f[k]} onChange={set(k)} placeholder={placeholder} />
      {hint && <span className="text-[11px] text-zinc-500">{hint}</span>}
    </label>
  )

  const save = async (kind: 'local' | 'remote') => {
    setErr('')
    try {
      await api.addTransform({
        kind,
        name: f.name,
        inputType: f.inputType,
        description: f.description,
        linkLabel: f.linkLabel || null,
        settings: splitList(f.settings),
        timeout: Number(f.timeout) || 60,
        ...(kind === 'local'
          ? { command: f.command, args: splitArgs(f.args), workingDir: f.workingDir || null }
          : { url: f.url }),
      })
      setF(BLANK)
      onChanged()
      setTab('list')
    } catch (e) {
      setErr(String((e as Error).message))
    }
  }

  const needed = [...new Set(transforms.flatMap((t) => t.settings))]
  const common = (
    <>
      {row('Display name', 'name', 'To Breach Records')}
      <label className="mb-2 block">
        <span className="text-xs text-zinc-400">Input entity type</span>
        <select className="field" value={f.inputType} onChange={set('inputType')}>
          {Object.keys(ENTITY_TYPES).map((t) => <option key={t}>{t}</option>)}
        </select>
      </label>
      {row('Default link label', 'linkLabel', 'e.g. Found In Breach', 'Used when the transform does not set link#maltego.link.label')}
      {row('Settings / API keys passed to it', 'settings', 'hibp.apikey, other.setting', 'Comma-separated names from the API Keys tab')}
      {row('Timeout (seconds)', 'timeout')}
      {row('Description', 'description')}
    </>
  )

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-black/60" onMouseDown={onClose}>
      <div className="flex max-h-[85vh] w-[640px] flex-col rounded-lg border border-zinc-700 bg-zinc-900" onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-1 border-b border-zinc-800 p-2">
          {(['list', 'tools', 'local', 'remote', 'keys'] as Tab[]).map((t) => (
            <button key={t} onClick={() => { setTab(t); setErr('') }} className={`rounded px-3 py-1 ${tab === t ? 'bg-sky-800' : 'hover:bg-zinc-800'}`}>
              {{ list: 'Transforms', tools: 'Tools', local: 'Add Local', remote: 'Add Remote (TRX)', keys: 'API Keys & Settings' }[t]}
            </button>
          ))}
          <button className="ml-auto px-2 text-zinc-400 hover:text-white" onClick={onClose}>✕</button>
        </div>

        <div className="overflow-auto p-4">
          {err && <p className="mb-3 rounded bg-rose-950 px-2 py-1 text-rose-300">{err}</p>}

          {tab === 'list' && (
            <div className="mb-2 flex items-center gap-2 border-b border-zinc-800 pb-2">
              <span className="text-xs text-zinc-400">Import Maltego transforms from a <code>.mtz</code> config:</span>
              <label className="btn cursor-pointer">
                Import .mtz
                <input type="file" accept=".mtz" hidden onChange={async (e) => {
                  const file = e.target.files?.[0]; e.currentTarget.value = ''
                  if (!file) return
                  setErr('')
                  try {
                    const r = await api.importFile('/api/import/mtz', file)
                    onChanged()
                    setErr(`Added ${r.added.length}${r.skipped.length ? `, skipped ${r.skipped.length}: ${r.skipped.slice(0, 3).join('; ')}` : ''}`)
                  } catch (x) { setErr(String((x as Error).message)) }
                }} />
              </label>
            </div>
          )}
          {tab === 'list' &&
            Object.keys(ENTITY_TYPES).map((type) => {
              const list = transforms.filter((t) => t.inputType === type)
              return list.length ? (
                <div key={type}>
                  <div className="h">{type}</div>
                  {list.map((t) => (
                    <div key={t.id} className="flex items-center gap-2 py-0.5">
                      <span className={`rounded px-1.5 text-[10px] uppercase ${t.kind === 'builtin' ? 'bg-zinc-800 text-zinc-400' : 'bg-sky-900 text-sky-300'}`}>{t.kind}</span>
                      <span className="flex-1" title={t.description}>{t.name}</span>
                      <span className="truncate text-xs text-zinc-500">{t.url ?? (t.command ? [t.command, ...(t.args ?? [])].join(' ') : '')}</span>
                      {t.kind !== 'builtin' && (
                        <button className="text-zinc-500 hover:text-rose-400" onClick={() => api.deleteTransform(t.id).then(onChanged)}>✕</button>
                      )}
                    </div>
                  ))}
                </div>
              ) : null
            })}

          {tab === 'tools' && (
            <>
              <p className="mb-3 text-xs text-zinc-400">
                Investigative tools and their status. <b>Built-in</b> ships with the app; <b>external</b> tools are
                detected on your system and run with explicit arguments, a timeout, and no shell. Set a custom path
                under <b>API Keys &amp; Settings</b> (e.g. <code>nmap.path</code>) if a tool isn't on your PATH.
              </p>
              {toolList.length === 0 && <p className="text-xs text-zinc-500">No tools reported.</p>}
              {toolList.map((t) => {
                const st = TOOL_STATE[t.state]
                return (
                  <div key={t.id} className="mb-2 rounded border border-zinc-800 p-2">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-zinc-200">{t.label}</span>
                      <span className={`rounded px-1.5 text-[10px] ${st.cls}`}>{st.label}</span>
                      {t.version && <span className="text-[11px] text-zinc-500">v{t.version}</span>}
                      {t.scoped && <span className="rounded bg-zinc-700/40 px-1.5 text-[10px] text-zinc-300">scope required</span>}
                      <span className="ml-auto text-[10px] uppercase tracking-wider text-zinc-600">{t.kind}</span>
                    </div>
                    <div className="mt-1 text-[11px] text-zinc-400">{t.detail}</div>
                    {t.state === 'needs-setup' && t.install && (
                      <div className="mt-1 text-[11px] text-amber-400/90">Install: <code>{t.install}</code></div>
                    )}
                  </div>
                )
              })}
            </>
          )}

          {tab === 'local' && (
            <>
              <p className="mb-3 text-xs text-zinc-400">
                Runs <code>command args… &lt;value&gt; [k=v#k2=v2]</code> and reads Maltego XML from stdout: the maltego-trx
                local protocol. For a maltego-trx project use args <code>project.py local &lt;transformname&gt;</code> with
                its folder as the working directory. Runs with a scrubbed environment and timeout; settings arrive as
                <code> TRX_SETTING_*</code> env vars.
              </p>
              {row('Command', 'command', 'python')}
              {row('Arguments', 'args', 'examples/dns_to_ip_local.py', 'Space-separated; quote paths with spaces')}
              {row('Working directory', 'workingDir', 'C:\\path\\to\\project (optional)')}
              {common}
              <button className="btn" onClick={() => save('local')}>Add local transform</button>
            </>
          )}

          {tab === 'remote' && (
            <>
              <p className="mb-3 text-xs text-zinc-400">
                POSTs a <code>MaltegoTransformRequestMessage</code> to the URL. Works with any maltego-trx server
                (<code>python project.py runserver</code> → <code>http://host:8080/run/&lt;name&gt;/</code>). Settings are sent as
                TransformFields, and only over https unless the host is localhost.
              </p>
              {row('Transform URL', 'url', 'http://localhost:8080/run/dnstoip/')}
              {common}
              <button className="btn" onClick={() => save('remote')}>Add remote transform</button>
            </>
          )}

          {tab === 'keys' && (
            <>
              <p className="mb-3 text-xs text-zinc-400">
                Stored server-side. Secret values are never sent back to the browser. A transform only receives the settings it declares.
              </p>
              {settings.map((s) => (
                <div key={s.name} className="flex items-center gap-2 py-0.5">
                  <code className="flex-1">{s.name}</code>
                  <span className="text-zinc-500">{s.secret ? '•••••• (secret)' : s.value}</span>
                  <button className="text-zinc-500 hover:text-rose-400" onClick={() => api.deleteSetting(s.name).then(loadSettings)}>✕</button>
                </div>
              ))}
              {needed.filter((n) => !settings.some((s) => s.name === n)).map((n) => (
                <div key={n} className="py-0.5 text-amber-400/80">
                  <code>{n}</code>: used by a transform, not set{' '}
                  <button className="underline" onClick={() => setKey({ ...key, name: n, secret: true })}>set it</button>
                </div>
              ))}

              <div className="h">AI assist</div>
              <p className="mb-1 text-xs text-zinc-400">
                Pick a provider: <code>anthropic</code> (Claude, default model <code>claude-opus-5-5</code>) or <code>openai</code>.
                For an open-weight / self-hosted model (Ollama, vLLM, llama.cpp, LM Studio), set provider to <code>openai</code>,
                point <code>openai.baseurl</code> at the server (e.g. <code>http://localhost:11434/v1</code>) and set <code>openai.model</code>.
              </p>
              {aiSettings.map((a) => {
                const cur = settings.find((s) => s.name === a.name)
                return (
                  <div key={a.name} className="flex items-center gap-2 py-0.5 text-xs">
                    <code className="w-36 shrink-0">{a.name}</code>
                    {cur ? (
                      <span className="flex-1 text-zinc-500">{cur.secret ? '•••••• (secret)' : cur.value}</span>
                    ) : (
                      <span className="flex-1 text-zinc-600">{a.placeholder}</span>
                    )}
                    {cur
                      ? <button className="text-zinc-500 hover:text-rose-400" onClick={() => api.deleteSetting(a.name).then(loadSettings)}>✕</button>
                      : <button className="underline text-sky-400" onClick={() => setKey({ name: a.name, value: '', secret: a.secret })}>set</button>}
                  </div>
                )
              })}

              <div className="mt-3 flex gap-1">
                <input className="field" placeholder="name" value={key.name} onChange={(e) => setKey({ ...key, name: e.target.value })} />
                <input className="field" placeholder="value" type={key.secret ? 'password' : 'text'} value={key.value} onChange={(e) => setKey({ ...key, value: e.target.value })} />
                <label className="flex items-center gap-1 whitespace-nowrap text-xs">
                  <input type="checkbox" checked={key.secret} onChange={(e) => setKey({ ...key, secret: e.target.checked })} /> secret
                </label>
                <button
                  className="btn"
                  disabled={!key.name}
                  onClick={() => api.putSetting(key.name, key.value, key.secret).then(() => { setKey({ name: '', value: '', secret: true }); loadSettings() })}
                >
                  Save
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
