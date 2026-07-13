import { useMemo, useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import { useGroupReports } from '../api/reports'
import { useGroupSignals, useGroupInsights, type InsightResult, type Trend } from '../api/signals'
import {
  useAskConversation,
  useAskConversations,
  useCreateAskConversation,
  useContinueAskConversation,
  type AskConversationBrief,
  type AskMessage,
  type AskRequest,
} from '../api/ask'
import { usePlatforms, type PlatformMeta } from '../api/platforms'
import type { ReportBrief, Signal } from '../api/types'
import SignalItem from '../components/SignalItem'
import { formatTime } from '../utils/time'

function reportKind(kind: string) {
  if (kind === 'scheduled') return '报告'
  return kind
}

type TopicTab = 'signals' | 'insights' | 'reports' | 'ask'

export default function GroupDetail() {
  const { id } = useParams()
  const gid = Number(id)
  const { data: reports = [] } = useGroupReports(gid, 50)
  const { data: allSignals = [] } = useGroupSignals(gid)
  const [activeTab, setActiveTab] = useState<TopicTab>('signals')
  const { data: insights, isFetching: isFetchingInsights } = useGroupInsights(gid, 14, activeTab === 'insights')
  const [showRepeats, setShowRepeats] = useState(false)

  const scheduledReports = useMemo(() => reports.filter((r) => r.kind === 'scheduled'), [reports])

  const newSignals = allSignals.filter((s) => s.is_new)
  const repeatSignals = allSignals.filter((s) => !s.is_new)
  const trends = insights?.trends ?? []

  const tabs: { key: TopicTab; label: string; meta?: string }[] = [
    { key: 'signals', label: '最近信号', meta: `${newSignals.length || allSignals.length} 条` },
    { key: 'insights', label: '洞察', meta: trends.length ? `${trends.length} 个趋势` : undefined },
    { key: 'reports', label: '报告', meta: scheduledReports.length ? `${scheduledReports.length} 份` : undefined },
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
          insights={insights}
          trends={trends}
          rawSignalCount={insights?.raw_signal_count ?? 0}
          days={insights?.days ?? 14}
          isFetching={isFetchingInsights}
        />
      )}

      {activeTab === 'reports' && (
        <ReportsPane
          reports={scheduledReports}
          scheduledCount={scheduledReports.length}
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
  insights,
  trends,
  rawSignalCount,
  days,
  isFetching,
}: {
  insights?: InsightResult | null
  trends: Trend[]
  rawSignalCount: number
  days: number
  isFetching: boolean
}) {
  const periodLabel = insights?.period?.start && insights?.period?.end
    ? `${insights.period.start} 至 ${insights.period.end}`
    : null
  return (
    <>
      <section className="reader-block topic-tab-panel">
        <div className="reader-block-head">
          <div>
            <h2>洞察</h2>
          </div>
          <span className="reader-tag">{periodLabel || (insights?.generated_at ? formatTime(insights.generated_at) : `近 ${days} 天`)}</span>
        </div>
        {insights?.overview && (
          <div className="insight-overview">
            <ReactMarkdown>{insights.overview}</ReactMarkdown>
          </div>
        )}
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
              ? '正在读取'
              : rawSignalCount >= 2
                ? `${rawSignalCount} 条新信号，暂无共同趋势`
                : '暂无共同趋势'}
          </div>
        )}
      </section>
    </>
  )
}

function ReportsPane({
  reports,
  scheduledCount,
}: {
  reports: ReportBrief[]
  scheduledCount: number
}) {
  return (
    <>
      <section className="reader-block">
        <div className="reader-block-head">
          <div>
            <h2>报告</h2>
          </div>
          <div className="archive-count">
            {scheduledCount} 份
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
  const { data: platforms = [] } = usePlatforms()
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const { data: selectedConversation } = useAskConversation(groupId, selectedId)
  const createConversation = useCreateAskConversation(groupId)
  const continueConversation = useContinueAskConversation(groupId, selectedId)
  const [question, setQuestion] = useState('')
  const [followup, setFollowup] = useState('')
  const [useExternal, setUseExternal] = useState(false)
  const [showSearchOptions, setShowSearchOptions] = useState(false)
  const [externalDays, setExternalDays] = useState(7)
  const [externalLimit, setExternalLimit] = useState(10)
  const [commentTopN, setCommentTopN] = useState(20)
  const [selectedPlatforms, setSelectedPlatforms] = useState<string[]>([])
  const suggestions = [
    '最近这些人在共同强调什么？',
    '最近观点有什么变化？',
    '关于价格战，他们分别怎么说？',
  ]
  const searchablePlatforms = platforms.filter((p) => p.capabilities.includes('search'))

  const askPayload = (q: string): AskRequest => ({
    question: q,
    use_internal: true,
    use_external: useExternal,
    platforms: selectedPlatforms,
    external_days: externalDays,
    external_limit: externalLimit,
    comment_top_n: commentTopN,
  })

  const togglePlatform = (platformId: string) => {
    setSelectedPlatforms((current) =>
      current.includes(platformId)
        ? current.filter((id) => id !== platformId)
        : [...current, platformId],
    )
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const q = question.trim()
    if (!q) return
    const res = await createConversation.mutateAsync(askPayload(q))
    setSelectedId(res.id)
    setQuestion('')
  }

  const submitFollowup = async (e: FormEvent) => {
    e.preventDefault()
    const q = followup.trim()
    if (!q || !selectedId) return
    await continueConversation.mutateAsync(askPayload(q))
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
          placeholder="问这个专题"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          rows={3}
        />
        <AskSourceControls
          useExternal={useExternal}
          showSearchOptions={showSearchOptions}
          externalDays={externalDays}
          externalLimit={externalLimit}
          commentTopN={commentTopN}
          platforms={searchablePlatforms}
          selectedPlatforms={selectedPlatforms}
          onToggleExternal={() => {
            setUseExternal((v) => !v)
            setShowSearchOptions(false)
          }}
          onToggleSearchOptions={() => setShowSearchOptions((v) => !v)}
          onExternalDays={setExternalDays}
          onExternalLimit={setExternalLimit}
          onCommentTopN={setCommentTopN}
          onAllPlatforms={() => setSelectedPlatforms([])}
          onTogglePlatform={togglePlatform}
        />
        <div className="ask-chat-actions">
          <div className="ask-suggestions">
            {suggestions.map((s) => (
              <button type="button" key={s} onClick={() => useSuggestion(s)}>{s}</button>
            ))}
          </div>
          <button className="pill-button primary" disabled={createConversation.isPending || !question.trim()}>
            {createConversation.isPending ? '提交中' : '问听风'}
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
                  placeholder="继续问这条对话..."
                  value={followup}
                  onChange={(e) => setFollowup(e.target.value)}
                  rows={2}
                />
                <button className="pill-button primary" disabled={continueConversation.isPending || !followup.trim()}>
                  {continueConversation.isPending ? '提交中' : '继续问'}
                </button>
              </form>
              {continueConversation.error && <div className="notice-line danger">继续提问失败：{(continueConversation.error as any)?.message || '未知错误'}</div>}
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

function boundedNumber(value: string, fallback: number, min: number, max: number) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return fallback
  return Math.max(min, Math.min(max, parsed))
}

function AskSourceControls({
  useExternal,
  showSearchOptions,
  externalDays,
  externalLimit,
  commentTopN,
  platforms,
  selectedPlatforms,
  onToggleExternal,
  onToggleSearchOptions,
  onExternalDays,
  onExternalLimit,
  onCommentTopN,
  onAllPlatforms,
  onTogglePlatform,
}: {
  useExternal: boolean
  showSearchOptions: boolean
  externalDays: number
  externalLimit: number
  commentTopN: number
  platforms: PlatformMeta[]
  selectedPlatforms: string[]
  onToggleExternal: () => void
  onToggleSearchOptions: () => void
  onExternalDays: (value: number) => void
  onExternalLimit: (value: number) => void
  onCommentTopN: (value: number) => void
  onAllPlatforms: () => void
  onTogglePlatform: (platformId: string) => void
}) {
  return (
    <div className="ask-source-line">
      <label className="ask-source-check">
        <input type="checkbox" checked={useExternal} onChange={onToggleExternal} />
        <span>补充找资料</span>
      </label>

      {useExternal && (
        <div className="ask-search-settings">
          <button type="button" className="ask-search-summary" onClick={onToggleSearchOptions}>
            近 {externalDays} 天 · 最多 {externalLimit} 条
          </button>
          {showSearchOptions && (
            <div className="ask-search-popover">
              <div className="ask-source-fieldset">
                <label>
                  <span>搜最近</span>
                  <span className="ask-number-field">
                    <input
                      type="number"
                      min={1}
                      max={365}
                      value={externalDays}
                      onChange={(e) => onExternalDays(boundedNumber(e.target.value, externalDays, 1, 365))}
                    />
                    <em>天</em>
                  </span>
                </label>
                <label>
                  <span>最多看</span>
                  <span className="ask-number-field">
                    <input
                      type="number"
                      min={1}
                      max={50}
                      value={externalLimit}
                      onChange={(e) => onExternalLimit(boundedNumber(e.target.value, externalLimit, 1, 50))}
                    />
                    <em>条</em>
                  </span>
                </label>
                <label>
                  <span>每条评论</span>
                  <span className="ask-number-field">
                    <input
                      type="number"
                      min={0}
                      max={100}
                      value={commentTopN}
                      onChange={(e) => onCommentTopN(boundedNumber(e.target.value, commentTopN, 0, 100))}
                    />
                    <em>条</em>
                  </span>
                </label>
              </div>
              <div className="ask-platforms">
                <button
                  type="button"
                  className={`ask-platform ${selectedPlatforms.length === 0 ? 'active' : ''}`}
                  onClick={onAllPlatforms}
                >
                  所有平台
                </button>
                {platforms.map((platform) => (
                  <button
                    type="button"
                    key={platform.id}
                    className={`ask-platform ${selectedPlatforms.includes(platform.id) ? 'active' : ''}`}
                    onClick={() => onTogglePlatform(platform.id)}
                  >
                    {platform.label}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
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
            <AskEvidenceRow key={askEvidenceKey(ev)} evidence={ev} />
          ))}
        </div>
      )}
    </div>
  )
}

function askEvidenceKey(evidence: AskMessage['evidence'][number]) {
  if (evidence.kind === 'external_search_task') return `task-${evidence.task_id || evidence.status}`
  return `${evidence.platform || 'content'}-${evidence.global_content_id || evidence.content_id}`
}

function AskEvidenceRow({ evidence }: { evidence: AskMessage['evidence'][number] }) {
  if (evidence.kind === 'external_search_task') {
    return (
      <div className={`ask-evidence-row task ${evidence.status || ''}`}>
        <strong>{evidence.title || '外部资料搜索'}</strong>
        <span>{evidence.status === 'failed' ? '失败' : '搜索中'}</span>
        {evidence.snippet && <small>{evidence.snippet}</small>}
        {evidence.task_id && <small className="mono-text">{evidence.task_id.slice(0, 12)}</small>}
      </div>
    )
  }

  const body = (
    <>
      <strong>{evidence.author}</strong>
      <span>{evidence.title || evidence.signal_summary || evidence.content_id}</span>
      {evidence.snippet && <small>{evidence.snippet}</small>}
    </>
  )

  if (!evidence.url) {
    return <div className="ask-evidence-row">{body}</div>
  }

  return (
    <a
      href={evidence.url}
      target="_blank"
      rel="noreferrer"
      className="ask-evidence-row"
    >
      {body}
    </a>
  )
}
