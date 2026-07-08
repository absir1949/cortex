import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import {
  useCreateSource,
  useDeleteGroup,
  useDeleteSource,
  useGroup,
  useRunSource,
  useUpdateGroup,
  useUpdateSource,
} from '../api/groups'
import { usePlatforms } from '../api/platforms'
import { useGroupSourceSummaries, type SourceSummary } from '../api/sources'

function formatTime(value?: string | null) {
  if (!value) return '还没刷新'
  return value.slice(0, 16).replace('T', ' ')
}

function sourceKind(s: SourceSummary) {
  return s.type === 'creator' ? '作者' : '关键词'
}

function errorMessage(err: unknown) {
  return err instanceof Error ? err.message : '未知错误'
}

export default function ListeningManage() {
  const { id } = useParams()
  const gid = Number(id)
  const { data: group, isLoading } = useGroup(gid)
  const { data: summaries = [] } = useGroupSourceSummaries(gid, 7)
  const { data: platforms = [] } = usePlatforms()
  const updateGroup = useUpdateGroup(gid)
  const createSrc = useCreateSource(gid)
  const updateSrc = useUpdateSource(gid)
  const deleteSrc = useDeleteSource(gid)
  const runSrc = useRunSource(gid)
  const deleteGroup = useDeleteGroup()
  const qc = useQueryClient()
  const navigate = useNavigate()

  const [notice, setNotice] = useState('')
  const [showAdd, setShowAdd] = useState(false)
  const [editingSid, setEditingSid] = useState<number | null>(null)
  const [editForm, setEditForm] = useState({ display_name: '', enabled: true })
  const [sourceForm, setSourceForm] = useState({
    type: 'creator' as 'creator' | 'keyword',
    platform: 'douyin',
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

  const totals = useMemo(() => ({
    enabled: summaries.filter((s) => s.enabled).length,
    failed: summaries.filter((s) => !!s.last_error).length,
    recentContent: summaries.reduce((sum, s) => sum + s.recent_content_count, 0),
    recentSignals: summaries.reduce((sum, s) => sum + s.recent_new_signal_count, 0),
  }), [summaries])

  if (isLoading) return <div className="muted-line">正在打开关注列表...</div>
  if (!group) return <div className="text-danger">未找到</div>

  const refreshSources = () => {
    qc.invalidateQueries({ queryKey: ['group', gid] })
    qc.invalidateQueries({ queryKey: ['source-summaries', gid] })
  }

  const onAddSource = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!sourceForm.identifier.trim()) return
    try {
      await createSrc.mutateAsync({
        type: sourceForm.type,
        platform: sourceForm.platform,
        identifier: sourceForm.identifier.trim(),
        display_name: sourceForm.display_name.trim(),
        interval_hours: settings.interval_hours,
        days: settings.days,
        content_limit: settings.content_limit,
        comment_top_n: settings.comment_top_n,
      })
      refreshSources()
      setNotice('已加入关注列表。')
      setSourceForm({ type: 'creator', platform: sourceForm.platform, identifier: '', display_name: '' })
      setShowAdd(false)
    } catch (err: any) {
      setNotice('添加失败：' + (err?.message || '未知错误'))
    }
  }

  const onEditSource = (s: SourceSummary) => {
    setEditingSid(s.id)
    setEditForm({ display_name: s.display_name, enabled: s.enabled })
  }

  const onSaveEdit = async () => {
    if (editingSid === null) return
    try {
      await updateSrc.mutateAsync({ sourceId: editingSid, ...editForm })
      refreshSources()
      setNotice('已保存关注源。')
      setEditingSid(null)
    } catch (err) {
      setNotice('保存失败：' + errorMessage(err))
    }
  }

  const onRunSource = async (sourceId: number) => {
    try {
      await runSrc.mutateAsync({ sourceId })
      setNotice('已经开始刷新这个关注源。')
    } catch (err) {
      setNotice('刷新失败：' + errorMessage(err))
    }
  }

  const onDeleteSource = async (s: SourceSummary) => {
    if (!confirm(`移除 ${s.display_name}?`)) return
    try {
      await deleteSrc.mutateAsync(s.id)
      refreshSources()
      setNotice('已移除关注源。')
    } catch (err) {
      setNotice('移除失败：' + errorMessage(err))
    }
  }

  const onSaveSettings = async () => {
    try {
      await updateGroup.mutateAsync({
        defaults: { ...(group.defaults || {}), ...settings },
      })
      setNotice('更新节奏已保存。')
    } catch (err) {
      setNotice('保存节奏失败：' + errorMessage(err))
    }
  }

  const onDeleteGroup = async () => {
    if (!confirm(`真的删除 "${group.name}" 吗？`)) return
    try {
      await deleteGroup.mutateAsync({ id: gid, cascade: true })
      navigate('/')
    } catch (err) {
      setNotice('删除专题失败：' + errorMessage(err))
    }
  }

  return (
    <div className="listening-page">
      <section className="listening-hero">
        <div>
          <h1>关注</h1>
        </div>
        <button className="pill-button primary" onClick={() => setShowAdd((v) => !v)}>
          {showAdd ? '收起' : '添加'}
        </button>
      </section>

      {notice && <div className="notice-line">{notice}</div>}

      <section className="listening-overview">
        <div><strong>{summaries.length}</strong><span>总关注</span></div>
        <div><strong>{totals.enabled}</strong><span>启用中</span></div>
        <div><strong>{totals.recentContent}</strong><span>7 天内容</span></div>
        <div><strong>{totals.recentSignals}</strong><span>7 天新信号</span></div>
        <div><strong>{totals.failed}</strong><span>异常</span></div>
      </section>

      {showAdd && (
        <section className="listening-panel">
          <div className="panel-head">
            <div>
              <h2>添加关注</h2>
            </div>
          </div>
          <form onSubmit={onAddSource} className="listening-add-form">
            <select
              className="input"
              value={sourceForm.type}
              onChange={(e) => setSourceForm({ ...sourceForm, type: e.target.value as any })}
            >
              <option value="creator">作者</option>
              <option value="keyword">关键词</option>
            </select>
            {sourceForm.type === 'creator' && (
              <select
                className="input"
                value={sourceForm.platform}
                onChange={(e) => setSourceForm({ ...sourceForm, platform: e.target.value })}
              >
                {platforms.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
              </select>
            )}
            <input
              className="input"
              placeholder={
                sourceForm.type === 'creator'
                  ? (platforms.find((p) => p.id === sourceForm.platform)?.identifier_hint || '平台 ID')
                  : '关键词'
              }
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
        </section>
      )}

      <section className="listening-panel" id="settings">
        <div className="panel-head">
          <div>
            <h2>收听名单</h2>
          </div>
        </div>

        <div className="listening-list">
          {summaries.length === 0 && <div className="empty-topic">暂无关注源</div>}
          {summaries.map((s) => (
            <article key={s.id} className={`listening-row ${s.last_error ? 'has-error' : ''}`}>
              <div className="listening-row-main">
                <Link to={`/groups/${gid}/creators/${s.id}`} className="listening-name">
                  {s.display_name}
                </Link>
                <small>{s.platform} · {sourceKind(s)} · 上次刷新 {formatTime(s.last_check)}</small>
                {s.last_error && <em>{s.last_error.slice(0, 100)}</em>}
              </div>

              <div className="listening-row-stats">
                <span>{s.recent_content_count}<small>内容</small></span>
                <span>{s.recent_new_signal_count}<small>新信号</small></span>
                <span className={s.enabled ? 'ok' : 'muted'}>{s.enabled ? '启用' : '暂停'}</span>
              </div>

              {editingSid === s.id ? (
                <div className="listening-edit">
                  <input
                    className="input"
                    value={editForm.display_name}
                    onChange={(e) => setEditForm({ ...editForm, display_name: e.target.value })}
                  />
                  <label>
                    <input
                      type="checkbox"
                      checked={editForm.enabled}
                      onChange={(e) => setEditForm({ ...editForm, enabled: e.target.checked })}
                    />
                    启用
                  </label>
                  <button className="pill-button small primary" onClick={onSaveEdit} disabled={updateSrc.isPending}>保存</button>
                  <button className="pill-button small" onClick={() => setEditingSid(null)}>取消</button>
                </div>
              ) : (
                <div className="listening-row-actions">
                  <button onClick={() => onRunSource(s.id)}>刷新</button>
                  <button onClick={() => onEditSource(s)}>编辑</button>
                  <button onClick={() => onDeleteSource(s)}>移除</button>
                </div>
              )}
            </article>
          ))}
        </div>
      </section>

      <section className="listening-panel">
        <div className="panel-head">
          <div>
            <h2>更新节奏</h2>
          </div>
        </div>
        <div className="settings-grid listening-settings">
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
        <button className="pill-button primary" onClick={onSaveSettings} disabled={updateGroup.isPending}>
          {updateGroup.isPending ? '保存中' : '保存节奏'}
        </button>
      </section>

      <button className="danger-link" onClick={onDeleteGroup}>删除这个专题</button>
    </div>
  )
}
