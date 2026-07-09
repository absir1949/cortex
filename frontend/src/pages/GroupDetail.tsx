import { useMemo, useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import { useGroupReports } from '../api/reports'
import { useGroupSignals, useGroupInsights, type Trend } from '../api/signals'
import {
  useAskConversation,
  useAskConversations,
  useCreateAskConversation,
  useContinueAskConversation,
  type AskConversationBrief,
  type AskMessage,
} from '../api/ask'
import type { ReportBrief, Signal } from '../api/types'
import SignalItem from '../components/SignalItem'

function formatTime(value?: string | null) {
  if (!value) return ''
  return value.slice(0, 16).replace('T', ' ')
}

function reportKind(kind: string) {
  if (kind === 'scheduled') return '日报'
  if (kind === 'research') return '追问'
  return kind
}

type TopicTab = 'signals' | 'insights' | 'ask'

export default function GroupDetail() {
  const { id } = useParams()
  const gid = Number(id)
  const { data: reports = [] } = useGroupReports(gid, 50)
  const { data: allSignals = [] } = useGroupSignals(gid)
  const { data: insights, isFetching: isFetchingInsights } = useGroupInsights(gid, 14)
  const [activeTab, setActiveTab] = useState<TopicTab>('signals')
  const [showRepeats, setShowRepeats] = useState(false)

  const scheduledReports = useMemo(() => reports.filter((r) => r.kind === 'scheduled'), [reports])
  const researchReports = useMemo(() => reports.filter((r) => r.kind === 'research'), [reports])

  const newSignals = allSignals.filter((s) => s.is_new)
  const repeatSignals = allSignals.filter((s) => !s.is_new)
  const trends = insights?.trends ?? []

  const tabs: { key: TopicTab; label: string; meta?: string }[] = [
    { key: 'signals', label: '最近信号', meta: `${newSignals.length || allSignals.length} 条` },
    { key: 'insights', label: '洞察', meta: trends.length ? `${trends.length} 个趋势` : undefined },
    { key: 'ask', label: '问听风' },
  ]

  return (
    <div className="topic-reading-home">
      <nav className="topic-tabs" aria-label="专题内容">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            className={`topic-tab ${activeTab === tab.key ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.key)}
          >
            <span className="topic-tab-copy">
              <strong>{tab.label}</strong>
              {tab.meta && <small>{tab.meta}</small>}
            </span>
          </button>
        ))}
      </nav>

      {activeTab === 'signals' && (
        <SignalsPane
          allSignalsCount={allSignals.length}
          newSignals={newSignals}
          repeatSignals={repeatSignals}
          showRepeats={showRepeats}
          onShowRepeats={() => setShowRepeats(true)}
        />
      )}

      {activeTab === 'insights' && (
        <InsightsPane
          trends={trends}
          reports={reports}
          scheduledCount={scheduledReports.length}
          researchCount={researchReports.length}
          rawSignalCount={insights?.raw_signal_count ?? 0}
          days={insights?.days ?? 14}
          isFetching={isFetchingInsights}
        />
      )}

      {activeTab === 'ask' && <AskPane groupId={gid} />}
    </div>
  )
}

function SignalsPane({
  allSignalsCount,
  newSignals,
  repeatSignals,
  showRepeats,
  onShowRepeats,
}: {
  allSignalsCount: number
  newSignals: Signal[]
  repeatSignals: Signal[]
  showRepeats: boolean
  onShowRepeats: () => void
}) {
  return (
    <section className="reader-block topic-tab-panel">
      <div className="reader-block-head">
        <div>
          <h2>最近信号</h2>
        </div>
        {newSignals.length > 0 && <span className="reader-tag">{newSignals.length} 条新观点</span>}
      </div>

      {allSignalsCount === 0 ? (
        <div className="empty-topic">暂无信号</div>
      ) : (
        <div className="signal-feed">
          {newSignals.map((s) => (
            <SignalItem key={s.id} signal={s} />
          ))}
          {repeatSignals.length > 0 && (
            showRepeats ? (
              repeatSignals.map((s) => (
                <SignalItem key={s.id} signal={s} />
              ))
            ) : (
              <div className="repeat-fold" onClick={onShowRepeats}>
                {repeatSignals.length} 条与既有观点重复，展开看原始判断
              </div>
            )
          )}
        </div>
      )}
    </section>
  )
}

function InsightsPane({
  trends,
  reports,
  scheduledCount,
  researchCount,
  rawSignalCount,
  days,
  isFetching,
}: {
  trends: Trend[]
  reports: ReportBrief[]
  scheduledCount: number
  researchCount: number
  rawSignalCount: number
  days: number
  isFetching: boolean
}) {
  return (
    <>
      <section className="reader-block topic-tab-panel">
        <div className="reader-block-head">
          <div>
            <h2>洞察</h2>
          </div>
          <span className="reader-tag">近 {days} 天</span>
        </div>
        {trends.length > 0 ? (
          <div className="insight-stack">
            {trends.map((t) => (
              <article key={t.trend} className="insight-note">
                <div className="insight-note-kicker">
                  <span>{t.signal_count >= 3 ? '升温' : '共识'}</span>
                  <small>{t.signal_count} 条信号 · {t.momentum}</small>
                </div>
                <h3>{t.trend}</h3>
                <p>{t.why_hot || `${t.source_names.slice(0, 4).join('、')} 都在讲这个方向。`}</p>
                <div className="insight-sources">{t.source_names.slice(0, 5).join(' / ')}</div>
              </article>
            ))}
          </div>
        ) : (
          <div className="empty-topic">
            {isFetching
              ? '正在分析'
              : rawSignalCount >= 2
                ? `${rawSignalCount} 条新信号，暂无共同趋势`
                : '暂无共同趋势'}
          </div>
        )}
      </section>

      <section className="reader-block">
        <div className="reader-block-head">
          <div>
            <h2>整理记录</h2>
          </div>
          <div className="archive-count">
            {scheduledCount} 份日报 · {researchCount} 个追问
          </div>
        </div>
        <div className="brief-list">
          {reports.length === 0 && <div className="muted-line">暂无整理记录</div>}
          {reports.map((r) => (
            <Link to={`/reports/${r.id}`} key={r.id} className="brief-row">
              <span>{reportKind(r.kind)}</span>
              <strong>{r.title}</strong>
              <small>{formatTime(r.created_at)}</small>
            </Link>
          ))}
        </div>
      </section>
    </>
  )
}

function AskPane({ groupId }: { groupId: number }) {
  const { data: conversations = [] } = useAskConversations(groupId)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const { data: selectedConversation } = useAskConversation(groupId, selectedId)
  const createConversation = useCreateAskConversation(groupId)
  const continueConversation = useContinueAskConversation(groupId, selectedId)
  const [question, setQuestion] = useState('')
  const [followup, setFollowup] = useState('')
  const suggestions = [
    '最近这些人在共同强调什么？',
    '最近观点有什么变化？',
    '关于价格战，他们分别怎么说？',
  ]

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const q = question.trim()
    if (!q) return
    const res = await createConversation.mutateAsync({ question: q, days: 30, limit: 12 })
    setSelectedId(res.id)
    setQuestion('')
  }

  const submitFollowup = async (e: FormEvent) => {
    e.preventDefault()
    const q = followup.trim()
    if (!q || !selectedId) return
    await continueConversation.mutateAsync({ question: q, days: 30, limit: 12 })
    setFollowup('')
  }

  const useSuggestion = (value: string) => {
    setQuestion(value)
  }

  return (
    <section className="reader-block topic-tab-panel ask-desk">
      <div className="reader-block-head">
        <div>
          <h2>问听风</h2>
        </div>
      </div>

      <form className="ask-chat-form ask-create-form" onSubmit={submit}>
        <textarea
          className="ask-chat-input"
          placeholder="问这个专题里的已有材料"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          rows={3}
        />
        <div className="ask-chat-actions">
          <div className="ask-suggestions">
            {suggestions.map((s) => (
              <button type="button" key={s} onClick={() => useSuggestion(s)}>{s}</button>
            ))}
          </div>
          <button className="pill-button primary" disabled={createConversation.isPending || !question.trim()}>
            {createConversation.isPending ? '思考中' : '新建对话'}
          </button>
        </div>
      </form>

      {createConversation.error && <div className="notice-line danger">问听风失败：{(createConversation.error as any)?.message || '未知错误'}</div>}

      <div className="ask-workspace">
        <div className="ask-thread-list">
          <div className="ask-section-head">
            <strong>最近对话</strong>
          </div>
          {conversations.length === 0 && <div className="empty-topic">暂无对话</div>}
          {conversations.map((conv) => (
            <ConversationCard
              key={conv.id}
              conversation={conv}
              active={conv.id === selectedId}
              onClick={() => setSelectedId(conv.id)}
            />
          ))}
        </div>

        <div className="ask-thread-detail">
          {selectedConversation ? (
            <>
              <div className="ask-section-head">
                <strong>{selectedConversation.title}</strong>
              </div>
              <div className="ask-messages">
                {selectedConversation.messages.map((msg) => (
                  <AskMessageBubble key={msg.id} message={msg} />
                ))}
              </div>
              <form className="ask-followup-form" onSubmit={submitFollowup}>
                <textarea
                  className="ask-chat-input"
                  placeholder="继续追问这条对话..."
                  value={followup}
                  onChange={(e) => setFollowup(e.target.value)}
                  rows={2}
                />
                <button className="pill-button primary" disabled={continueConversation.isPending || !followup.trim()}>
                  {continueConversation.isPending ? '思考中' : '继续问'}
                </button>
              </form>
              {continueConversation.error && <div className="notice-line danger">继续追问失败：{(continueConversation.error as any)?.message || '未知错误'}</div>}
            </>
          ) : (
            <div className="ask-detail-empty">
              <p>选择对话</p>
            </div>
          )}
        </div>
      </div>
    </section>
  )
}

function ConversationCard({
  conversation,
  active,
  onClick,
}: {
  conversation: AskConversationBrief
  active: boolean
  onClick: () => void
}) {
  return (
    <button className={`ask-thread-card ${active ? 'active' : ''}`} onClick={onClick}>
      <strong>{conversation.title}</strong>
      {conversation.latest_answer && <span>{conversation.latest_answer.slice(0, 96)}</span>}
      <small>{conversation.evidence_count} 条证据 · {formatTime(conversation.updated_at)}</small>
    </button>
  )
}

function AskMessageBubble({ message }: { message: AskMessage }) {
  const [evidenceOpen, setEvidenceOpen] = useState(false)
  const hasEvidence = message.role === 'assistant' && message.evidence.length > 0

  return (
    <div className={`ask-message ${message.role}`}>
      <div className="ask-bubble prose-cortex">
        <ReactMarkdown>{message.content}</ReactMarkdown>
      </div>
      {hasEvidence && (
        <div className="ask-evidence">
          <button type="button" className="ask-evidence-toggle" onClick={() => setEvidenceOpen((v) => !v)}>
            {evidenceOpen ? '收起证据' : `证据 · ${message.evidence.length}`}
          </button>
          {evidenceOpen && message.evidence.map((ev) => (
            <a
              key={`${ev.platform || 'content'}-${ev.global_content_id || ev.content_id}`}
              href={ev.url || undefined}
              target="_blank"
              rel="noreferrer"
              className="ask-evidence-row"
            >
              <strong>{ev.author}</strong>
              <span>{ev.title || ev.signal_summary || ev.content_id}</span>
              {ev.snippet && <small>{ev.snippet}</small>}
            </a>
          ))}
        </div>
      )}
    </div>
  )
}
