import { useEffect, useState } from 'react'
import { useConfig, useUpdateConfig, usePrompts, useUpdatePrompt } from '../api/config'

export default function Settings() {
  const { data: cfg } = useConfig()
  const update = useUpdateConfig()
  const { data: prompts } = usePrompts()
  const updatePrompt = useUpdatePrompt()

  const [form, setForm] = useState<Record<string, any>>({})
  const [promptEdits, setPromptEdits] = useState<Record<string, string>>({})
  const [msg, setMsg] = useState('')

  useEffect(() => {
    if (cfg?.values) setForm({ ...cfg.values })
  }, [cfg?.values])

  useEffect(() => {
    if (prompts) setPromptEdits({ ...prompts })
  }, [prompts])

  if (!cfg) return <div className="text-muted">加载中...</div>

  const onSave = async () => {
    const changed: Record<string, any> = {}
    for (const k in form) {
      if (JSON.stringify(form[k]) !== JSON.stringify(cfg.values[k])) {
        changed[k] = form[k]
      }
    }
    if (Object.keys(changed).length === 0) {
      setMsg('没有变化')
      return
    }
    await update.mutateAsync(changed)
    setMsg(`✓ 已保存 ${Object.keys(changed).length} 项`)
    setTimeout(() => setMsg(''), 2000)
  }

  const onSavePrompt = async (name: string) => {
    await updatePrompt.mutateAsync({ name, content: promptEdits[name] })
    setMsg(`✓ 已保存 ${name}`)
    setTimeout(() => setMsg(''), 2000)
  }

  const renderField = (key: string) => {
    const schema = cfg.schema[key]
    if (!schema) return null
    const value = form[key] ?? ''
    const set = (v: any) => setForm((f) => ({ ...f, [key]: v }))

    if (schema.type === 'bool') {
      return (
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={!!value} onChange={(e) => set(e.target.checked)} />
          <span>{schema.label}</span>
        </label>
      )
    }
    if (schema.type === 'int') {
      return (
        <div>
          <label className="text-sm text-muted mb-1 block">{schema.label}</label>
          <input
            className="input" type="number"
            min={schema.min} max={schema.max}
            value={value}
            onChange={(e) => set(Number(e.target.value))}
          />
        </div>
      )
    }
    if (schema.type === 'float') {
      return (
        <div>
          <label className="text-sm text-muted mb-1 block">{schema.label}</label>
          <input
            className="input" type="number" step="0.1"
            min={schema.min} max={schema.max}
            value={value}
            onChange={(e) => set(Number(e.target.value))}
          />
        </div>
      )
    }
    if (schema.type === 'secret') {
      return (
        <div>
          <label className="text-sm text-muted mb-1 block">{schema.label}</label>
          <input
            className="input" type="password"
            placeholder="（保持不变则不填）"
            value={value}
            onChange={(e) => set(e.target.value)}
          />
        </div>
      )
    }
    // string
    return (
      <div>
        <label className="text-sm text-muted mb-1 block">{schema.label}</label>
        {schema.presets && (
          <div className="flex gap-1 mb-1 flex-wrap">
            {Object.entries(schema.presets).map(([name, url]) => (
              <button
                key={name}
                type="button"
                className="btn-ghost text-xs"
                onClick={() => set(url)}
              >
                {name}
              </button>
            ))}
          </div>
        )}
        <input className="input" value={value} onChange={(e) => set(e.target.value)} />
      </div>
    )
  }

  const fieldKeys = Object.keys(cfg.schema)
  const groupedKeys = {
    '采集': fieldKeys.filter((k) => ['content_limit', 'days', 'interval_hours', 'comment_top_n'].includes(k)),
    '转录': fieldKeys.filter((k) => k.startsWith('transcribe_')),
    'LLM': fieldKeys.filter((k) => k.startsWith('llm_')),
    '研究': fieldKeys.filter((k) => k.startsWith('research_')),
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">设置</h1>
        <div className="flex items-center gap-2">
          {msg && <span className="text-accent text-sm">{msg}</span>}
          <button className="btn-primary" onClick={onSave}>保存</button>
        </div>
      </div>

      {Object.entries(groupedKeys).map(([section, keys]) => (
        <section key={section}>
          <h2 className="text-lg font-semibold mb-2">{section}</h2>
          <div className="card grid grid-cols-1 md:grid-cols-2 gap-4">
            {keys.map((k) => <div key={k}>{renderField(k)}</div>)}
          </div>
        </section>
      ))}

      <section>
        <h2 className="text-lg font-semibold mb-2">Prompt 模板</h2>
        {Object.keys(promptEdits).map((name) => (
          <div key={name} className="card mb-3">
            <div className="flex items-center justify-between mb-2">
              <div className="font-medium">{name}</div>
              <button className="btn-ghost text-xs" onClick={() => onSavePrompt(name)}>保存</button>
            </div>
            <textarea
              className="input font-mono text-xs h-48"
              value={promptEdits[name] || ''}
              onChange={(e) => setPromptEdits({ ...promptEdits, [name]: e.target.value })}
            />
          </div>
        ))}
      </section>
    </div>
  )
}
