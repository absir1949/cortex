import { useMemo } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useGroupReports } from '../api/reports'
import { useGroupSignals, useGroupInsights } from '../api/signals'
import SignalItem from '../components/SignalItem'
import { useState } from 'react'

function formatTime(value?: string | null) {
  if (!value) return ''
  return value.slice(0, 16).replace('T', ' ')
}

function reportKind(kind: string) {
  if (kind === 'scheduled') return '日报'
  if (kind === 'research') return '追问'
  return kind
}

/** 知识库主页（主内容区，由 GroupLayout 的 Outlet 渲染）*/
export default function GroupDetail() {
  const { id } = useParams()
  const gid = Number(id)
  const { data: reports = [] } = useGroupReports(gid, 50)
  const { data: allSignals = [] } = useGroupSignals(gid)
  const { data: insights } = useGroupInsights(gid, 14)
  const trends = insights?.trends ?? []
  const [showRepeats, setShowRepeats] = useState(false)

  const latestReport = useMemo(() => reports[0], [reports])
  const scheduledReports = useMemo(() => reports.filter((r) => r.kind === 'scheduled'), [reports])
  const researchReports = useMemo(() => reports.filter((r) => r.kind === 'research'), [reports])

  const newSignals = allSignals.filter((s) => s.is_new)
  const repeatSignals = allSignals.filter((s) => !s.is_new)

  return (
    <>
      {/* 行业趋势 */}
      {trends.length > 0 && (
        <section className="reader-block lead-block">
          <div className="reader-block-head">
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

      {/* 最新报告 */}
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
            <p>{latestReport.summary || '打开查看完整证据和整理过程。'}</p>
            <span>阅读全文</span>
          </Link>
        ) : (
          <div className="empty-topic">
            还没有简报。点「刷新今日简报」生成报告，或点「只整理报告」基于已有信号立即生成。
          </div>
        )}
      </section>

      {/* 信号流 */}
      <section className="reader-block">
        <div className="reader-block-head">
          <div>
            <span className="soft-label">SIGNALS</span>
            <h2>最近的信号</h2>
          </div>
          {newSignals.length > 0 && <span className="reader-tag">🆕 {newSignals.length}</span>}
        </div>

        {allSignals.length === 0 ? (
          <div className="muted-line">还没有信号。采集后系统会自动判定每条内容。</div>
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
                <div className="repeat-fold" onClick={() => setShowRepeats(true)}>
                  ♻️ {repeatSignals.length} 条与既有观点重复（点击展开）
                </div>
              )
            )}
          </div>
        )}
      </section>

      {/* 简报历史 */}
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
    </>
  )
}
