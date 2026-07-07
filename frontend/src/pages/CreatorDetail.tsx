import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import { useSourceDetail, useSourceContents, useSourceProfile } from '../api/sources'
import TranscriptToggle from '../components/TranscriptCard'

function formatTime(value?: string | null) {
  if (!value) return ''
  return value.slice(0, 10)
}

const PLATFORM_LABELS: Record<string, string> = {
  douyin: '抖音',
  wechat: '视频号',
  xhs: '小红书',
}

/** 博主主页：观点档案 + 内容列表 + 信号标记（由 GroupLayout 的 Outlet 渲染）*/
export default function CreatorDetail() {
  const { id, sid } = useParams()
  const gid = Number(id)
  const sourceId = Number(sid)
  const { data: detail, isLoading } = useSourceDetail(gid, sourceId)
  const { data: contentsResp } = useSourceContents(gid, sourceId, 100)
  const { data: profile = '' } = useSourceProfile(gid, sourceId)
  const [showProfile, setShowProfile] = useState(true)

  if (isLoading) return <div className="muted-line">加载中...</div>
  if (!detail) return <div className="text-danger">未找到博主</div>

  const contents = contentsResp?.items ?? []
  const newCount = contents.filter((c) => c.is_new_signal === true).length
  const repeatCount = contents.filter((c) => c.is_new_signal === false).length
  // profile 可能是 string（已建立）或空字符串（未建立）；防御非 string 类型
  const profileText = typeof profile === 'string' ? profile : ''
  const hasProfile = profileText && !profileText.includes('尚未建立') && !profileText.includes('尚未关联')

  return (
    <>
      {/* 博主头部 */}
      <section className="reader-block lead-block">
        <div className="reader-block-head">
          <div>
            <span className="soft-label">{PLATFORM_LABELS[detail.platform] || detail.platform}</span>
            <h2>{detail.name}</h2>
          </div>
          <Link to={`/groups/${gid}`} className="back-link">返回专题</Link>
        </div>
        <div style={{ fontSize: 14, color: '#66756d' }}>
          {detail.aliases.length > 0 && (
            <span>
              {detail.aliases.map((a) => PLATFORM_LABELS[a.platform] || a.platform).join(' · ')}
            </span>
          )}
          {detail.last_check && <span> · 最近采集 {formatTime(detail.last_check)}</span>}
        </div>
        <div style={{ fontSize: 13, color: '#66756d', marginTop: 8 }}>
          共 {contents.length} 条内容 · 🆕 {newCount} 条新观点 · ♻️ {repeatCount} 条重复
        </div>
        {detail.last_error && (
          <em style={{ display: 'block', color: '#c2413a', marginTop: 8, fontSize: 13 }}>
            上次采集出错：{detail.last_error.slice(0, 120)}
          </em>
        )}
      </section>

      {/* 观点档案 */}
      {hasProfile && (
        <section className="reader-block">
          <div className="reader-block-head">
            <div>
              <span className="soft-label">PROFILE</span>
              <h2>观点档案</h2>
            </div>
            <button className="pill-button small" onClick={() => setShowProfile(!showProfile)}>
              {showProfile ? '收起' : '展开'}
            </button>
          </div>
          {showProfile && (
            <div className="card prose-cortex" style={{ marginTop: 12 }}>
              <ReactMarkdown>{profileText}</ReactMarkdown>
            </div>
          )}
        </section>
      )}

      {/* 内容列表 */}
      <section className="reader-block">
        <div className="reader-block-head">
          <div>
            <span className="soft-label">CONTENT</span>
            <h2>最近内容</h2>
          </div>
        </div>
        {contents.length === 0 ? (
          <div className="muted-line">还没有采集到内容。</div>
        ) : (
          <div className="signal-feed">
            {contents.map((c) => (
              <article key={c.content_id} className={`signal-item${c.is_new_signal === false ? ' is-repeat' : ''}`}>
                <div className="signal-item-head">
                  <span className="signal-item-badge">
                    {c.is_new_signal === true ? '🆕' : c.is_new_signal === false ? '♻️' : '·'}
                  </span>
                  <span className="signal-item-summary">{c.title || '（无标题）'}</span>
                </div>
                <div className="signal-meta">
                  <span>{formatTime(c.create_time)}</span>
                  {c.statistics && c.statistics.digg_count != null && (
                    <>
                      <span>·</span>
                      <span>👍 {c.statistics.digg_count}</span>
                    </>
                  )}
                  {c.url && (
                    <>
                      <span>·</span>
                      <a href={c.url} target="_blank" rel="noreferrer">看原视频 ↗</a>
                    </>
                  )}
                  {c.transcribed && (
                    <>
                      <span>·</span>
                      <TranscriptToggle contentId={c.content_id} />
                    </>
                  )}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </>
  )
}
