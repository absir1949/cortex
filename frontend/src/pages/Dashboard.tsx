import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useGroups, useCreateGroup } from '../api/groups'
import { useRecentNewSignals } from '../api/signals'
import SignalItem from '../components/SignalItem'

function formatTime(value?: string | null) {
  if (!value) return ''
  return value.slice(0, 16).replace('T', ' ')
}

function reportLead(title?: string) {
  if (!title) return '还没有简报'
  return title.replace(/^研究：/, '')
}

/** 首页 = 全局时间流。所有知识库的新观点混合按时间倒序，扫一眼掌握全行业。 */
export default function Dashboard() {
  const { data: groups = [], isLoading } = useGroups()
  const { data: newSignals = [] } = useRecentNewSignals(30)
  const createGroup = useCreateGroup()

  const [showCreate, setShowCreate] = useState(false)
  const [name, setName] = useState('')

  const latestSignal = newSignals[0]
  const isEmpty = !isLoading && newSignals.length === 0 && groups.length === 0

  return (
    <div className="home-page">
      {/* 主体：全局新信号流 */}
      <section className="feed-section">
        <div className="feed-header">
          <span className="soft-label">NEW SIGNALS</span>
          <h1>今天的新观点</h1>
          <p>所有专题里判断为「新观点」的内容，按时间倒序。hover 摘要看原文，重复的已自动过滤。</p>
        </div>

        {newSignals.length === 0 ? (
          <div className="empty-feed">
            {groups.length === 0 ? (
              <>
                <p>还没有专题。先订阅一个主题，Cortex 会帮你盯着。</p>
                <button className="pill-button primary" onClick={() => setShowCreate(true)}>订阅第一个专题</button>
              </>
            ) : (
              <p>最近还没有新观点。系统会在下次采集后更新。</p>
            )}
          </div>
        ) : (
          <div className="signal-feed">
            {newSignals.map((s) => (
              <SignalItem key={s.id} signal={s} showGroupName />
            ))}
          </div>
        )}
      </section>

      {/* 专题入口（底部导航，紧凑）*/}
      <section className="section-title-row">
        <div>
          <span className="soft-label">YOUR TOPICS</span>
          <h2>你的专题</h2>
        </div>
        <button className="pill-button" onClick={() => setShowCreate(!showCreate)}>
          {showCreate ? '收起' : '订阅新专题'}
        </button>
      </section>

      {showCreate && (
        <form
          className="new-topic-form"
          onSubmit={async (e) => {
            e.preventDefault()
            if (!name.trim()) return
            const g = await createGroup.mutateAsync({
              name: name.trim(),
              defaults: { interval_hours: 24, days: 7, content_limit: 50, comment_top_n: 20 },
            })
            setName('')
            setShowCreate(false)
            window.location.href = `/groups/${g.id}`
          }}
        >
          <input
            className="input"
            placeholder="专题名，例如：微信小店"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <button className="pill-button primary" disabled={!name.trim() || createGroup.isPending}>
            {createGroup.isPending ? '创建中' : '开始订阅'}
          </button>
        </form>
      )}

      <div className="topic-grid">
        {isLoading && <div className="muted-line">正在加载...</div>}
        {groups.map((g) => (
          <Link to={`/groups/${g.id}`} key={g.id} className="topic-card">
            <div className="topic-card-main">
              <span className="topic-status">{g.enabled ? '自动更新' : '已暂停'}</span>
              <h3>{g.name}</h3>
              <p>{g.source_count} 个关注源</p>
            </div>
          </Link>
        ))}
      </div>
    </div>
  )
}
