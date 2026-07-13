import { useState, useEffect, useCallback, useRef } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import { useSourceDetail, useSourceContents, useSourceProfile } from '../api/sources'
import type { SourceContent } from '../api/sources'
import { useRunSource, useGroup } from '../api/groups'
import { useTask } from '../api/tasks'
import TranscriptToggle from '../components/TranscriptCard'
import { formatTime } from '../utils/time'

function formatDate(value?: string | null) {
  if (!value) return ''
  return formatTime(value).slice(0, 10)
}

const PLATFORM_LABELS: Record<string, string> = {
  douyin: '抖音',
  wechat_channels: '视频号',
  xhs: '小红书',
}

const PAGE_SIZE = 20

export default function CreatorDetail() {
  const { id, sid } = useParams()
  const gid = Number(id)
  const sourceId = Number(sid)
  const { data: detail, isLoading } = useSourceDetail(gid, sourceId)
  const { data: group } = useGroup(gid)
  const { data: profile = '' } = useSourceProfile(gid, sourceId)
  const [showProfile, setShowProfile] = useState(true)
  const [refreshDays, setRefreshDays] = useState(7)
  const [refreshTaskId, setRefreshTaskId] = useState<string | null>(null)
  const [notice, setNotice] = useState('')
  const runSource = useRunSource(gid)
  const refreshTask = useTask(refreshTaskId)
  const qc = useQueryClient()

  const [page, setPage] = useState(0)
  const [items, setItems] = useState<SourceContent[]>([])
  const [total, setTotal] = useState(0)
  const [loadingMore, setLoadingMore] = useState(false)
  const { data: pageData, isError: pageError } = useSourceContents(gid, sourceId, PAGE_SIZE, page * PAGE_SIZE)
  const loadedOffsetRef = useRef<number>(-1)  // 追踪已处理的 offset，防竞态重复

  useEffect(() => {
    setPage(0)
    setItems([])
    setTotal(0)
    setLoadingMore(false)
    loadedOffsetRef.current = -1
  }, [sourceId])

  useEffect(() => {
    if (pageError) {
      setLoadingMore(false)
      return
    }
    if (!pageData) return
    const offset = page * PAGE_SIZE
    // 已经处理过这个 offset 的数据，不重复（防竞态）
    if (loadedOffsetRef.current === offset) return
    loadedOffsetRef.current = offset
    setTotal(pageData.total)
    if (offset === 0) {
      setItems(pageData.items)
    } else {
      setItems((prev) => [...prev, ...pageData.items])
    }
    setLoadingMore(false)
  }, [pageData, pageError, page])

  useEffect(() => {
    if (!refreshTaskId || !refreshTask.data) return
    const st = refreshTask.data.status
    if (st === 'succeeded') {
      const n = refreshTask.data.result?.new_contents
      setNotice(n != null ? `✓ 刷新完成，新增 ${n} 条内容。` : '✓ 刷新完成。')
      setRefreshTaskId(null)
      setPage(0)
      setItems([])
      loadedOffsetRef.current = -1
      qc.invalidateQueries({ queryKey: ['source-contents', gid, sourceId] })
      qc.invalidateQueries({ queryKey: ['source-profile', gid, sourceId] })
    } else if (st === 'failed' || st === 'canceled') {
      setNotice('刷新失败：' + ((refreshTask.data.error || '').slice(0, 80) || '未知错误'))
      setRefreshTaskId(null)
    }
  }, [refreshTask.data, refreshTaskId, gid, sourceId, qc])

  const loadMore = useCallback(() => {
    setLoadingMore(true)
    setPage((p) => p + 1)
  }, [])

  if (isLoading) return <div className="muted-line">加载中...</div>
  if (!detail) return <div className="text-danger">未找到博主</div>

  const newCount = items.filter((c) => c.is_new_signal === true).length
  const repeatCount = items.filter((c) => c.is_new_signal === false).length
  const profileText = typeof profile === 'string' ? profile : ''
  const hasProfile = profileText && !profileText.includes('尚未建立') && !profileText.includes('尚未关联')
  const hasMore = items.length < total
  const platformLabel = PLATFORM_LABELS[detail.platform] || detail.platform

  return (
    <div className="creator-page">
      <div className="breadcrumb-bar">
        <Link to="/" className="back-link">今日</Link>
        <span className="breadcrumb-sep">›</span>
        <Link to={`/groups/${gid}`} className="breadcrumb-group">{group?.name || '专题'}</Link>
      </div>

      <section className="creator-hero">
        <div className="creator-hero-row">
          <div className="creator-identity">
            <h1>{detail.name}</h1>
            <div className="creator-metrics">
              <span className="platform-tag">{platformLabel}</span>
              {detail.last_check && <span>最近采集 {formatDate(detail.last_check)}</span>}
              <span>{total} 条内容</span>
              <span>{newCount} 条新信号</span>
              <span>{repeatCount} 条重复</span>
            </div>
          </div>
          <div className="creator-actions">
            <select
              className="input creator-days-select"
              value={refreshDays}
              onChange={(e) => setRefreshDays(Number(e.target.value))}
            >
              <option value={3}>近 3 天</option>
              <option value={7}>近 7 天</option>
              <option value={14}>近 14 天</option>
              <option value={30}>近 30 天</option>
            </select>
            <button
              className="pill-button primary"
              disabled={runSource.isPending || !!refreshTaskId}
              onClick={async () => {
                try {
                  const res = await runSource.mutateAsync({ sourceId, force: true, days: refreshDays })
                  setRefreshTaskId(res.task_id)
                  setNotice(`正在刷新「${detail.name}」近 ${refreshDays} 天的内容...`)
                } catch (err: any) {
                  setNotice('刷新失败：' + (err?.message || '未知错误'))
                }
              }}
            >
              {runSource.isPending || refreshTaskId ? '刷新中' : '刷新这个作者'}
            </button>
          </div>
        </div>
        {detail.last_error && <em className="creator-error">上次采集出错：{detail.last_error.slice(0, 120)}</em>}
        {notice && <div className="notice-line">{notice}</div>}
      </section>

      {hasProfile && (
        <section className="reader-block">
          <div className="reader-block-head">
            <div>
              <h2>观点档案</h2>
            </div>
            <button className="pill-button small" onClick={() => setShowProfile(!showProfile)}>
              {showProfile ? '收起' : '展开'}
            </button>
          </div>
          {showProfile && (
            <div className="creator-profile-body prose-cortex">
              <ReactMarkdown>{profileText}</ReactMarkdown>
            </div>
          )}
        </section>
      )}

      <section className="reader-block">
        <div className="reader-block-head">
          <div>
            <h2>最近内容</h2>
          </div>
          <span className="reader-tag">{total}</span>
        </div>
        {items.length === 0 ? (
          <div className="muted-line">还没有采集到内容。</div>
        ) : (
          <>
            <div className="signal-feed">
              {items.map((c) => (
                <article key={c.content_id} className={`signal-item${c.is_new_signal === false ? ' is-repeat' : ''}`}>
                  <div className="signal-item-head">
                    <span className="signal-item-badge">
                      {c.is_new_signal === true ? '新' : c.is_new_signal === false ? '复' : '·'}
                    </span>
                    <span className="signal-item-summary">{c.title || '（无标题）'}</span>
                  </div>
                  <div className="signal-meta">
                    <span>{formatDate(c.create_time)}</span>
                    {c.statistics && c.statistics.digg_count != null && (
                      <><span>·</span><span>赞 {c.statistics.digg_count}</span></>
                    )}
                    {c.url && (
                      <><span>·</span><a href={c.url} target="_blank" rel="noreferrer">原视频</a></>
                    )}
                    {c.transcribed && (
                      <><span>·</span><TranscriptToggle contentId={c.content_id} /></>
                    )}
                  </div>
                </article>
              ))}
            </div>
            {hasMore && (
              <div style={{ textAlign: 'center', padding: '16px 0' }}>
                <button className="pill-button" onClick={loadMore} disabled={loadingMore}>
                  {loadingMore ? '加载中...' : `加载更多（还有 ${total - items.length} 条）`}
                </button>
              </div>
            )}
          </>
        )}
      </section>
    </div>
  )
}
