import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useGroups, useCreateGroup } from '../api/groups'
import { useRecentReports } from '../api/reports'
import { useSchedulerJobs } from '../api/scheduler'
import { api } from '../api/client'

function formatTime(value?: string | null) {
  if (!value) return '等待第一次更新'
  return value.slice(0, 16).replace('T', ' ')
}

function kindLabel(kind: string) {
  if (kind === 'scheduled') return '日报'
  if (kind === 'research') return '追问'
  return kind
}

function reportLead(title?: string) {
  if (!title) return '还没有新的简报'
  return title.replace(/^研究：/, '')
}

export default function Dashboard() {
  const { data: groups = [], isLoading } = useGroups()
  const { data: recent = [] } = useRecentReports(12)
  const { data: jobs = [] } = useSchedulerJobs()
  const createGroup = useCreateGroup()
  const qc = useQueryClient()

  const [showCreate, setShowCreate] = useState(false)
  const [name, setName] = useState('')
  const [question, setQuestion] = useState('')
  const [selectedGroupId, setSelectedGroupId] = useState<number | ''>('')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    if (!selectedGroupId && groups[0]) setSelectedGroupId(groups[0].id)
  }, [groups, selectedGroupId])

  const latest = recent[0]
  const scheduledReports = useMemo(() => recent.filter((r) => r.kind === 'scheduled'), [recent])
  const researchReports = useMemo(() => recent.filter((r) => r.kind === 'research'), [recent])

  const askResearch = useMutation({
    mutationFn: (body: { groupId: number; question: string }) =>
      api.post<{ task_id: string }>(`/groups/${body.groupId}/research`, {
        question: body.question,
        days: 7,
        search_limit: 10,
        comment_top_n: 20,
      }),
    onSuccess: () => {
      setQuestion('')
      setNotice('已经开始研究，完成后会出现在今日简报里。')
      qc.invalidateQueries({ queryKey: ['reports', 'recent'] })
    },
  })

  const onCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    const group = await createGroup.mutateAsync({
      name: name.trim(),
      defaults: { interval_hours: 24, days: 7, content_limit: 50, comment_top_n: 20 },
    })
    setSelectedGroupId(group.id)
    setName('')
    setShowCreate(false)
  }

  const onAsk = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!question.trim() || !selectedGroupId) return
    await askResearch.mutateAsync({ groupId: Number(selectedGroupId), question: question.trim() })
  }

  return (
    <div className="home-page">
      <section className="daily-letter">
        <div className="daily-copy">
          <span className="soft-label">TODAY'S BRIEF</span>
          <h1>今天的行业信号，都放在这里。</h1>
          <p>
            你关注一组人，Cortex 每天替你扫一遍。不是看后台任务，而是打开就读结论、证据和可追问的问题。
          </p>
        </div>
        <div className="daily-card">
          <span>{latest ? kindLabel(latest.kind) : '今日'}</span>
          <h2>{reportLead(latest?.title)}</h2>
          <p>{latest?.summary || '等专题跑起来以后，这里会优先展示最值得看的新变化。'}</p>
          {latest ? (
            <Link to={`/reports/${latest.id}`} className="pill-button primary">阅读简报</Link>
          ) : (
            <button className="pill-button primary" onClick={() => setShowCreate(true)}>订阅一个专题</button>
          )}
        </div>
      </section>

      <section className="ask-bar">
        <div>
          <h2>临时想查一个问题？</h2>
          <p>选择一个专题，直接追问。结果会沉淀成一篇研究简报。</p>
        </div>
        <form onSubmit={onAsk} className="ask-form">
          <select
            className="input"
            value={selectedGroupId}
            onChange={(e) => setSelectedGroupId(Number(e.target.value))}
          >
            {groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
          </select>
          <input
            className="input"
            placeholder="例如：最近他们怎么解决单号无法直填？"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
          />
          <button className="pill-button primary" disabled={!question.trim() || !selectedGroupId || askResearch.isPending}>
            {askResearch.isPending ? '研究中' : '追问'}
          </button>
        </form>
        {notice && <div className="notice-line">{notice}</div>}
      </section>

      <section className="section-title-row">
        <div>
          <span className="soft-label">SUBSCRIPTIONS</span>
          <h2>你的专题</h2>
          <p>每个专题关注一批作者，固定节奏生成一份可以读的日报。</p>
        </div>
        <button className="pill-button" onClick={() => setShowCreate(!showCreate)}>
          {showCreate ? '收起' : '订阅新专题'}
        </button>
      </section>

      {showCreate && (
        <form onSubmit={onCreate} className="new-topic-form">
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
        {isLoading && <div className="muted-line">正在整理你的专题...</div>}
        {!isLoading && groups.length === 0 && (
          <div className="empty-topic">
            还没有专题。先订阅一个主题，再把你关心的作者放进去。
          </div>
        )}
        {groups.map((g) => {
          const job = jobs.find((j) => j.id === `group_${g.id}`)
          const latestReport = recent.find((r) => r.group_id === g.id)
          return (
            <Link to={`/groups/${g.id}`} key={g.id} className="topic-card">
              <div className="topic-card-main">
                <span className="topic-status">{g.enabled ? '自动更新' : '已暂停'}</span>
                <h3>{g.name}</h3>
                <p>{g.source_count} 个关注源 · 最近 {g.defaults?.days || 7} 天内容</p>
              </div>
              <div className="topic-card-brief">
                <span>最新</span>
                <strong>{reportLead(latestReport?.title)}</strong>
              </div>
              <div className="topic-card-foot">
                <span>{scheduledReports.filter((r) => r.group_id === g.id).length} 份日报</span>
                <span>下次 {formatTime(job?.next_run)}</span>
              </div>
            </Link>
          )
        })}
      </div>

      <section className="recent-strip">
        <div>
          <span className="soft-label">LIBRARY</span>
          <h2>最近沉淀</h2>
        </div>
        <div className="brief-list">
          {recent.length === 0 && <div className="muted-line">还没有简报。</div>}
          {recent.map((r) => (
            <Link to={`/reports/${r.id}`} key={r.id} className="brief-row">
              <span>{kindLabel(r.kind)}</span>
              <strong>{r.title}</strong>
              <small>{formatTime(r.created_at)}</small>
            </Link>
          ))}
        </div>
        {researchReports.length > 0 && (
          <div className="tiny-note">最近有 {researchReports.length} 个按需追问。</div>
        )}
      </section>
    </div>
  )
}
