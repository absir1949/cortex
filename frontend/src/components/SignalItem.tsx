import type { Signal } from '../api/types'
import TranscriptToggle from './TranscriptCard'

function formatTime(value?: string | null) {
  if (!value) return ''
  return value.slice(0, 16).replace('T', ' ')
}

interface Props {
  signal: Signal
  showVideoLink?: boolean
  showGroupName?: boolean
}

/** 信号卡片 - 在 Dashboard 和 GroupDetail 复用 */
export default function SignalItem({ signal, showVideoLink = true, showGroupName = false }: Props) {
  const isRepeat = !signal.is_new
  const points = signal.is_new ? signal.new_points : signal.matched_points

  return (
    <article className={`signal-item${isRepeat ? ' is-repeat' : ''}`}>
      <div className="signal-item-head">
        <span className="signal-item-badge">{signal.is_new ? '🆕' : '♻️'}</span>
        <span className="signal-item-summary">{signal.summary || '（无摘要）'}</span>
      </div>
      {points.length > 0 && (
        <ul className="signal-points">
          {points.map((p, i) => (
            <li key={i}>{signal.is_new ? p : `命中已有观点：${p}`}</li>
          ))}
        </ul>
      )}
      <div className="signal-meta">
        <span>{signal.source_name || '博主'}</span>
        {showGroupName && signal.group_name && (
          <>
            <span>·</span>
            <span>{signal.group_name}</span>
          </>
        )}
        <span>·</span>
        <span>{formatTime(signal.created_at)}</span>
        {showVideoLink && signal.url && (
          <>
            <span>·</span>
            <a href={signal.url} target="_blank" rel="noreferrer">看原视频 ↗</a>
          </>
        )}
        <span>·</span>
        <TranscriptToggle contentId={signal.content_id} />
      </div>
    </article>
  )
}
