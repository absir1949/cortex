import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useGroups } from '../api/groups'
import { useRecentNewSignals } from '../api/signals'
import SignalItem from '../components/SignalItem'
import type { Signal } from '../api/types'
import { formatTime } from '../utils/time'

function formatToday() {
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'long',
    day: 'numeric',
    weekday: 'long',
  }).format(new Date())
}

export default function Dashboard() {
  const { data: groups = [] } = useGroups()
  const { data: newSignals = [] } = useRecentNewSignals(30)
  const [activeLeadIndex, setActiveLeadIndex] = useState(0)

  const leadSignals = useMemo(() => newSignals.slice(0, 3), [newSignals])
  const leadSignal = leadSignals[activeLeadIndex] || leadSignals[0]
  const leadSignalIds = useMemo(() => new Set(leadSignals.map((s) => s.id)), [leadSignals])
  const timelineSignals = newSignals.filter((s) => !leadSignalIds.has(s.id))
  const hasTopics = groups.length > 0

  useEffect(() => {
    setActiveLeadIndex(0)
  }, [leadSignals.length])

  useEffect(() => {
    if (leadSignals.length <= 1) return
    const timer = window.setInterval(() => {
      setActiveLeadIndex((index) => (index + 1) % leadSignals.length)
    }, 9000)
    return () => window.clearInterval(timer)
  }, [leadSignals.length])

  return (
    <div className="home-page">
      <section className="home-edition">
        <div className="home-edition-main">
          <div className="home-edition-kicker">
            <span className="soft-label">{formatToday()}</span>
            <Link className="text-link-button" to="/topics">专题</Link>
          </div>

          {leadSignal ? (
            <>
              <LeadSignalCard signal={leadSignal} />
              {leadSignals.length > 1 && (
                <div className="home-lead-dots">
                  {leadSignals.map((s, index) => (
                    <button
                      key={s.id}
                      type="button"
                      className={`home-lead-dot ${index === activeLeadIndex ? 'active' : ''}`}
                      aria-label={`切换到第 ${index + 1} 条`}
                      onClick={() => setActiveLeadIndex(index)}
                    />
                  ))}
                </div>
              )}
            </>
          ) : (
            <div className="home-empty-note">
              <strong>{hasTopics ? '暂无新信号' : '暂无专题'}</strong>
              <Link to="/topics">{hasTopics ? '查看专题' : '订阅专题'}</Link>
            </div>
          )}
        </div>

        <aside className="home-edition-side">
          <div className="home-side-title">
            <strong>{leadSignals.length} 条新信号</strong>
          </div>
          {leadSignals.length === 0 ? (
            <p className="muted-line">暂无</p>
          ) : (
            leadSignals.map((s, index) => (
              <article key={s.id} className={`home-side-signal ${index === activeLeadIndex ? 'active' : ''}`}>
                <button type="button" onClick={() => setActiveLeadIndex(index)}>
                  {s.summary}
                </button>
                <SignalMeta signal={s} />
              </article>
            ))
          )}
        </aside>
      </section>

      <section className="feed-section">
        <div className="feed-header">
          <h1>时间线</h1>
          <span className="reader-tag">{timelineSignals.length}</span>
        </div>
        {timelineSignals.length === 0 ? (
          <div className="empty-feed"><p>{newSignals.length === 0 ? '暂无新观点' : '暂无更多'}</p></div>
        ) : (
          <div className="signal-feed">
            {timelineSignals.map((s) => (
              <SignalItem key={s.id} signal={s} showGroupName />
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

function LeadSignalCard({ signal }: { signal: Signal }) {
  return (
    <article className="home-lead-signal">
      <SignalMeta signal={signal} />
      <Link to={signal.group_id ? `/groups/${signal.group_id}` : '/'} className="home-lead-title">
        {signal.summary}
      </Link>
      <small>{formatTime(signal.created_at)}</small>
    </article>
  )
}

function SignalMeta({ signal }: { signal: Signal }) {
  const creatorPath = signal.group_id && signal.source_id
    ? `/groups/${signal.group_id}/creators/${signal.source_id}`
    : null
  return (
    <div className="home-signal-meta">
      {signal.group_id ? (
        <Link to={`/groups/${signal.group_id}`}>{signal.group_name || '专题'}</Link>
      ) : (
        <span>{signal.group_name || '专题'}</span>
      )}
      <span>·</span>
      {creatorPath ? (
        <Link to={creatorPath}>{signal.source_name || '作者'}</Link>
      ) : (
        <span>{signal.source_name || '作者'}</span>
      )}
    </div>
  )
}
