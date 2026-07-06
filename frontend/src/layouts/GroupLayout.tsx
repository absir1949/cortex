import { useEffect, useState } from 'react'
import { Link, Outlet, useNavigate, useParams } from 'react-router-dom'
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
import { useSchedulerJobs } from '../api/scheduler'
import { useTask } from '../api/tasks'

function formatTime(value?: string | null) {
  if (!value) return '待安排'
  return value.slice(0, 16).replace('T', ' ')
}

function firstChar(value: string) {
  return value.trim().slice(0, 1).toUpperCase() || 'C'
}

/** 知识库容器布局：hero + 侧边栏，子页面通过 Outlet 渲染在主内容区 */
export default function GroupLayout() {
  const { id, sid } = useParams()
  const gid = Number(id)
  const { data: group, isLoading } = useGroup(gid)
  const { data: jobs = [] } = useSchedulerJobs()
  const update = useUpdateGroup(gid)
  const createSrc = useCreateSource(gid)
  const deleteSrc = useDeleteSource(gid)
  const runSrc = useRunSource(gid)
  const runGroup = useRunGroup(gid)
  const analyzeGroup = useAnalyzeGroup(gid)
  const deleteGroup = useDeleteGroup()
  const navigate = useNavigate()
  const qc = useQueryClient()

  const [showAdd, setShowAdd] = useState(false)
  const [notice, setNotice] = useState('')
  const [analyzeTaskId, setAnalyzeTaskId] = useState<string | null>(null)
  const analyzeTask = useTask(analyzeTaskId)
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

  useEffect(() => {
    setNotice('')
  }, [gid, sid])

  useEffect(() => {
    if (!analyzeTaskId || !analyzeTask.data) return
    const st = analyzeTask.data.status
    if (st === 'succeeded') {
      const rid = analyzeTask.data.result?.report_id
      setNotice(rid ? `✓ 报告已生成。` : '没有可整理的新内容。')
      setAnalyzeTaskId(null)
      qc.invalidateQueries({ queryKey: ['reports', 'group', gid] })
    } else if (st === 'failed' || st === 'canceled') {
      setNotice('整理失败：' + ((analyzeTask.data.error || '').slice(0, 80) || '未知错误'))
      setAnalyzeTaskId(null)
    }
  }, [analyzeTask.data, analyzeTaskId, gid, qc])

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
    setNotice('已加入关注列表，下次更新会一起整理。')
    setSourceForm({ type: 'creator', identifier: '', display_name: '' })
    setShowAdd(false)
  }

  const onRunSource = async (sid: number) => {
    await runSrc.mutateAsync(sid)
    setNotice('已经开始刷新这个关注源。')
  }

  const onRunGroup = async () => {
    await runGroup.mutateAsync({ force: true, analyze: true })
    setNotice('已经开始刷新专题，完成后会生成新的日报。')
  }

  const onAnalyze = async () => {
    const res = await analyzeGroup.mutateAsync()
    setAnalyzeTaskId(res.task_id)
    setNotice('正在整理报告，通常需要几分钟，完成后会自动显示。')
  }

  const onSaveSettings = async () => {
    await update.mutateAsync({
      defaults: { ...(group.defaults || {}), ...settings },
    })
    setNotice('更新节奏已保存。')
  }

  const onToggleEnabled = async () => {
    await update.mutateAsync({ enabled: !group.enabled })
    setNotice(group.enabled ? '已暂停自动更新。' : '已恢复自动更新。')
  }

  const onDeleteGroup = async () => {
    if (!confirm(`真的删除 "${group.name}" 吗？`)) return
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
            {group.sources.length} 个关注源，每 {settings.interval_hours} 小时自动整理。下一次：{formatTime(job?.next_run)}。
          </p>
        </div>
        <div className="topic-actions">
          <button className="pill-button primary" onClick={onRunGroup} disabled={runGroup.isPending}>
            {runGroup.isPending ? '刷新中' : '刷新今日简报'}
          </button>
          <button className="pill-button" onClick={onAnalyze} disabled={analyzeGroup.isPending} title="不重新采集，只基于已有信号整理报告">
            {analyzeGroup.isPending ? '整理中' : '只整理报告'}
          </button>
          <Link to={`/groups/${gid}/research`} className="pill-button">追问</Link>
          <button className="pill-button quiet" onClick={onToggleEnabled}>
            {group.enabled ? '暂停' : '恢复'}
          </button>
        </div>
      </section>

      {notice && <div className="notice-line">{notice}</div>}

      <div className="topic-layout">
        <main className="topic-reader">
          <Outlet />
        </main>

        <aside className="topic-rail">
          {/* 关注的博主（可点击进博主主页）*/}
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
                  placeholder={sourceForm.type === 'creator' ? '抖音号 / sec_uid' : '关键词'}
                  value={sourceForm.identifier}
                  onChange={(e) => setSourceForm({ ...sourceForm, identifier: e.target.value })}
                />
                <input
                  className="input"
                  placeholder="显示名"
                  value={sourceForm.display_name}
                  onChange={(e) => setSourceForm({ ...sourceForm, display_name: e.target.value })}
                />
                <button type="submit" className="pill-button primary" disabled={createSrc.isPending}>
                  {createSrc.isPending ? '解析中' : '加入'}
                </button>
              </form>
            )}

            <div className="follow-list">
              {group.sources.length === 0 && <div className="muted-line">还没有关注源。</div>}
              {group.sources.map((s) => (
                <div className="follow-item" key={s.id}>
                  <Link to={`/groups/${gid}/creators/${s.id}`} className="follow-avatar follow-link">
                    {firstChar(s.display_name)}
                  </Link>
                  <div className="follow-body">
                    <Link to={`/groups/${gid}/creators/${s.id}`} className="follow-link">
                      <strong>{s.display_name}</strong>
                    </Link>
                    <small>{s.type === 'creator' ? '作者' : '关键词'} · {formatTime(s.last_check)}</small>
                    {s.last_error && <em>{s.last_error.slice(0, 80)}</em>}
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

          {/* 更新节奏 */}
          <section className="rail-block rhythm-block">
            <div>
              <span className="soft-label">RHYTHM</span>
              <h2>更新节奏</h2>
            </div>
            <div className="settings-grid">
              <label>
                <span>间隔（小时）</span>
                <input className="input" type="number" min={1} max={720}
                  value={settings.interval_hours}
                  onChange={(e) => setSettings({ ...settings, interval_hours: Number(e.target.value) })}
                />
              </label>
              <label>
                <span>回看天数</span>
                <input className="input" type="number" min={1} max={365}
                  value={settings.days}
                  onChange={(e) => setSettings({ ...settings, days: Number(e.target.value) })}
                />
              </label>
              <label>
                <span>每源内容</span>
                <input className="input" type="number" min={1} max={200}
                  value={settings.content_limit}
                  onChange={(e) => setSettings({ ...settings, content_limit: Number(e.target.value) })}
                />
              </label>
              <label>
                <span>评论</span>
                <input className="input" type="number" min={0} max={100}
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
