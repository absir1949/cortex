import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import {
  useGroup,
  useUpdateGroup,
  useCreateSource,
  useDeleteSource,
  useRunSource,
  useRunGroup,
  useAnalyzeGroup,
  useDeleteGroup,
} from '../api/groups'
import { useGroupReports } from '../api/reports'
import { useSchedulerJobs } from '../api/scheduler'
import { useGroupSignals, useGroupInsights } from '../api/signals'

function formatTime(value?: string | null) {
  if (!value) return '待安排'
  return value.slice(0, 16).replace('T', ' ')
}

function reportKind(kind: string) {
  if (kind === 'scheduled') return '日报'
  if (kind === 'research') return '追问'
  return kind
}

function firstChar(value: string) {
  return value.trim().slice(0, 1).toUpperCase() || 'C'
}

export default function GroupDetail() {
  const { id } = useParams()
  const gid = Number(id)
  const { data: group, isLoading } = useGroup(gid)
  const { data: reports = [] } = useGroupReports(gid, 50)
  const { data: jobs = [] } = useSchedulerJobs()
  const { data: allSignals = [] } = useGroupSignals(gid)
  const { data: insights } = useGroupInsights(gid, 14)
  const trends = insights?.trends ?? []
  const update = useUpdateGroup(gid)
  const createSrc = useCreateSource(gid)
  const deleteSrc = useDeleteSource(gid)
  const runSrc = useRunSource(gid)
  const runGroup = useRunGroup(gid)
  const analyzeGroup = useAnalyzeGroup(gid)
  const qc = useQueryClient()
  const deleteGroup = useDeleteGroup()
  const navigate = useNavigate()

  const [showAdd, setShowAdd] = useState(false)
  const [notice, setNotice] = useState('')
  const [showRepeats, setShowRepeats] = useState(false)
  const [sourceForm, setSourceForm] = useState({
    type: 'creator' as 'creator' | 'keyword',
    identifier: '',
    display_name: '',
  })
  const [settings, setSettings] = useState({
    interval_hours: 24,
    days: 7,
    content_limit: 50,
    comment_top_n: 20,
  })

  useEffect(() => {
    if (!group) return
    setSettings({
      interval_hours: Number(group.defaults?.interval_hours || 24),
      days: Number(group.defaults?.days || 7),
      content_limit: Number(group.defaults?.content_limit || 50),
      comment_top_n: Number(group.defaults?.comment_top_n || 20),
    })
  }, [group])

  const latestReport = useMemo(() => reports[0], [reports])
  const scheduledReports = useMemo(() => reports.filter((r) => r.kind === 'scheduled'), [reports])
  const researchReports = useMemo(() => reports.filter((r) => r.kind === 'research'), [reports])
  const job = jobs.find((j) => j.id === `group_${gid}`)

  if (isLoading) return <div className="muted-line">正在打开专题...</div>
  if (!group) return <div className="text-danger">未找到</div>

  const onAddSource = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!sourceForm.identifier.trim()) return
    await createSrc.mutateAsync({
      type: sourceForm.type,
      platform: 'douyin',
      identifier: sourceForm.identifier.trim(),
      display_name: sourceForm.display_name.trim(),
      interval_hours: settings.interval_hours,
      days: settings.days,
      content_limit: settings.content_limit,
      comment_top_n: settings.comment_top_n,
    })
    setNotice('已经加入关注列表，下次更新会一起整理。')
    setSourceForm({ type: 'creator', identifier: '', display_name: '' })
    setShowAdd(false)
  }

  const onRunSource = async (sid: number) => {
    await runSrc.mutateAsync(sid)
    setNotice('已经开始刷新这个关注源，完成后会沉淀到报告里。')
  }

  const onRunGroup = async () => {
    await runGroup.mutateAsync({ force: true, analyze: true })
    setNotice('已经开始刷新专题，完成后会生成新的日报。')
  }

  const onAnalyze = async () => {
    await analyzeGroup.mutateAsync()
    setNotice('正在基于已有信号整理报告，不重新采集，很快就好。')
    qc.invalidateQueries({ queryKey: ['reports', 'group', gid] })
  }

  // 信号分流：新观点 vs 老调重弹
  const newSignals = allSignals.filter((s) => s.is_new)
  const repeatSignals = allSignals.filter((s) => !s.is_new)

  const onSaveSettings = async () => {
    await update.mutateAsync({
      defaults: {
        ...(group.defaults || {}),
        ...settings,
      },
    })
    setNotice('更新节奏已保存。')
  }

  const onToggleEnabled = async () => {
    await update.mutateAsync({ enabled: !group.enabled })
    setNotice(group.enabled ? '这个专题已暂停自动更新。' : '这个专题已恢复自动更新。')
  }

  const onDeleteGroup = async () => {
    if (!confirm(`真的删除 "${group.name}" 吗？（会连带删除所有关注源）`)) return
    await deleteGroup.mutateAsync({ id: gid, cascade: true })
    navigate('/')
  }

  return (
    <div className="topic-page">
      <section className="topic-hero">
        <div className="topic-hero-copy">
          <Link to="/" className="back-link">返回今日</Link>
          <span className="soft-label">{group.enabled ? '正在追踪' : '已暂停'}</span>
          <h1>{group.name}情报</h1>
          <p>
            {group.sources.length} 个关注源，每 {settings.interval_hours} 小时自动整理一次。下一次：
            {formatTime(job?.next_run)}。
          </p>
        </div>
        <div className="topic-actions">
          <button className="pill-button primary" onClick={onRunGroup} disabled={runGroup.isPending}>
            {runGroup.isPending ? '刷新中' : '刷新今日简报'}
          </button>
          <button className="pill-button" onClick={onAnalyze} disabled={analyzeGroup.isPending} title="不重新采集，只基于已有信号整理报告">
            {analyzeGroup.isPending ? '整理中' : '只整理报告'}
          </button>
          <Link to={`/groups/${gid}/research`} className="pill-button">追问这个专题</Link>
          <button className="pill-button quiet" onClick={onToggleEnabled}>
            {group.enabled ? '暂停更新' : '恢复更新'}
          </button>
        </div>
      </section>

      {notice && <div className="notice-line">{notice}</div>}

      <div className="topic-layout">
        <main className="topic-reader">
          <section className="reader-block lead-block">
            <div className="reader-block-head">
              <div>
                <span className="soft-label">LATEST</span>
                <h2>最新值得看的结论</h2>
              </div>
              {latestReport && <span className="reader-tag">{reportKind(latestReport.kind)}</span>}
            </div>
            {latestReport ? (
              <Link to={`/reports/${latestReport.id}`} className="featured-report">
                <h3>{latestReport.title}</h3>
                <time>{formatTime(latestReport.created_at)}</time>
                <p>{latestReport.summary || '打开查看完整证据、原文和整理过程。'}</p>
                <span>阅读全文</span>
              </Link>
            ) : (
              <div className="empty-topic">
                还没有简报。点“刷新今日简报”，系统会从你关注的人里整理一份报告。
              </div>
            )}
          </section>

          {/* 信号流：时间倒序，视觉分层（趋势置顶 > 新观点展开 > 老调重弹折叠）*/}
          <section className="reader-block">
            <div className="reader-block-head">
              <div>
                <span className="soft-label">SIGNALS</span>
                <h2>最近的信号</h2>
              </div>
              {newSignals.length > 0 && <span className="reader-tag">🆕 {newSignals.length}</span>}
            </div>

            {allSignals.length === 0 && (
              <div className="muted-line">还没有信号。采集后系统会自动判定每条内容是「新观点」还是「老调重弹」。</div>
            )}

            <div className="signal-feed">
              {newSignals.map((s) => (
                <article className="signal-item" key={s.id}>
                  <div className="signal-item-head">
                    <span className="signal-item-badge">🆕</span>
                    <span className="signal-item-summary">{s.summary || '（无摘要）'}</span>
                  </div>
                  {s.new_points.length > 0 && (
                    <ul className="signal-points">
                      {s.new_points.map((p, i) => <li key={i}>{p}</li>)}
                    </ul>
                  )}
                  <div className="signal-meta">
                    <span>{s.source_name || '博主'}</span>
                    <span>·</span>
                    <span>{formatTime(s.created_at)}</span>
                    {s.url && (
                      <>
                        <span>·</span>
                        <a href={s.url} target="_blank" rel="noreferrer">看原视频 ↗</a>
                      </>
                    )}
                  </div>
                </article>
              ))}

              {repeatSignals.length > 0 && (
                showRepeats ? (
                  repeatSignals.map((s) => (
                    <article className="signal-item is-repeat" key={s.id}>
                      <div className="signal-item-head">
                        <span className="signal-item-badge">♻️</span>
                        <span className="signal-item-summary">{s.summary || '（无摘要）'}</span>
                      </div>
                      {s.matched_points.length > 0 && (
                        <ul className="signal-points">
                          {s.matched_points.map((p, i) => <li key={i}>命中已有观点：{p}</li>)}
                        </ul>
                      )}
                      <div className="signal-meta">
                        <span>{s.source_name || '博主'}</span>
                        <span>·</span>
                        <span>{formatTime(s.created_at)}</span>
                      </div>
                    </article>
                  ))
                ) : (
                  <div className="repeat-fold" onClick={() => setShowRepeats(true)}>
                    ♻️ {repeatSignals.length} 条与既有观点重复（点击展开）
                  </div>
                )
              )}
            </div>
          </section>

          <section className="reader-block">
            <div className="reader-block-head">
              <div>
                <span className="soft-label">ARCHIVE</span>
                <h2>简报历史</h2>
              </div>
              <div className="archive-count">
                {scheduledReports.length} 份日报 · {researchReports.length} 个追问
              </div>
            </div>
            <div className="brief-list">
              {reports.length === 0 && <div className="muted-line">还没有报告。</div>}
              {reports.map((r) => (
                <Link to={`/reports/${r.id}`} key={r.id} className="brief-row">
                  <span>{reportKind(r.kind)}</span>
                  <strong>{r.title}</strong>
                  <small>{formatTime(r.created_at)}</small>
                </Link>
              ))}
            </div>
          </section>
        </main>

        <aside className="topic-rail">
          <section className="rail-block">
            <div className="rail-head">
              <div>
                <span className="soft-label">LISTENING</span>
                <h2>正在关注</h2>
              </div>
              <button className="pill-button small" onClick={() => setShowAdd(!showAdd)}>
                {showAdd ? '收起' : '添加'}
              </button>
            </div>

            {showAdd && (
              <form onSubmit={onAddSource} className="follow-form">
                <select
                  className="input"
                  value={sourceForm.type}
                  onChange={(e) => setSourceForm({ ...sourceForm, type: e.target.value as any })}
                >
                  <option value="creator">作者</option>
                  <option value="keyword">关键词</option>
                </select>
                <input
                  className="input"
                  placeholder={sourceForm.type === 'creator' ? '抖音号 / 作者名 / sec_uid' : '关键词'}
                  value={sourceForm.identifier}
                  onChange={(e) => setSourceForm({ ...sourceForm, identifier: e.target.value })}
                />
                <input
                  className="input"
                  placeholder="显示名，例如 爆爆爱爆单(微店)"
                  value={sourceForm.display_name}
                  onChange={(e) => setSourceForm({ ...sourceForm, display_name: e.target.value })}
                />
                <button type="submit" className="pill-button primary" disabled={createSrc.isPending}>
                  {createSrc.isPending ? '解析中' : '加入关注'}
                </button>
              </form>
            )}

            <div className="follow-list">
              {group.sources.length === 0 && <div className="muted-line">还没有关注源。</div>}
              {group.sources.map((s) => (
                <div className="follow-item" key={s.id}>
                  <div className="follow-avatar">{firstChar(s.display_name)}</div>
                  <div className="follow-body">
                    <strong>{s.display_name}</strong>
                    <small>{s.type === 'creator' ? '作者' : '关键词'} · 最近检查 {formatTime(s.last_check)}</small>
                    {s.last_error && <em>{s.last_error.slice(0, 120)}</em>}
                  </div>
                  <div className="follow-actions">
                    <button onClick={() => onRunSource(s.id)}>刷新</button>
                    <button onClick={() => confirm(`删除 ${s.display_name}?`) && deleteSrc.mutate(s.id)}>
                      移除
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </section>

          {trends.length > 0 && (
            <section className="rail-block">
              <div className="rail-head">
                <div>
                  <span className="soft-label">TRENDS</span>
                  <h2>行业趋势</h2>
                </div>
                <span className="reader-tag">{trends.length}</span>
              </div>
              <div className="insight-card" style={{ marginBottom: 0 }}>
                {trends.map((t) => (
                  <div key={t.trend} className="insight-card-row">
                    <strong>{t.signal_count >= 3 ? '🔥 ' : ''}{t.trend}</strong>
                    <span className="muted"> — {t.source_names.slice(0, 3).join('、')}</span>
                    <span className="accent"> {t.momentum}</span>
                  </div>
                ))}
              </div>
            </section>
          )}

          <section className="rail-block rhythm-block">
            <div>
              <span className="soft-label">RHYTHM</span>
              <h2>更新节奏</h2>
              <p>默认每天读一次，回看最近 7 天；需要密集盯盘时再调高频率。</p>
            </div>
            <div className="settings-grid">
              <label>
                <span>间隔（小时）</span>
                <input
                  className="input"
                  type="number"
                  min={1}
                  max={720}
                  value={settings.interval_hours}
                  onChange={(e) => setSettings({ ...settings, interval_hours: Number(e.target.value) })}
                />
              </label>
              <label>
                <span>回看天数</span>
                <input
                  className="input"
                  type="number"
                  min={1}
                  max={365}
                  value={settings.days}
                  onChange={(e) => setSettings({ ...settings, days: Number(e.target.value) })}
                />
              </label>
              <label>
                <span>每源内容</span>
                <input
                  className="input"
                  type="number"
                  min={1}
                  max={200}
                  value={settings.content_limit}
                  onChange={(e) => setSettings({ ...settings, content_limit: Number(e.target.value) })}
                />
              </label>
              <label>
                <span>评论</span>
                <input
                  className="input"
                  type="number"
                  min={0}
                  max={100}
                  value={settings.comment_top_n}
                  onChange={(e) => setSettings({ ...settings, comment_top_n: Number(e.target.value) })}
                />
              </label>
            </div>
            <button className="pill-button primary wide" onClick={onSaveSettings} disabled={update.isPending}>
              {update.isPending ? '保存中' : '保存节奏'}
            </button>
          </section>

          <button className="danger-link" onClick={onDeleteGroup}>删除这个专题</button>
        </aside>
      </div>
    </div>
  )
}
