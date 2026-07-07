import { Link } from 'react-router-dom'
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

export default function SignalItem({ signal, showVideoLink = true, showGroupName = false }: Props) {
  const isRepeat = !signal.is_new
  const points = signal.is_new ? signal.new_points : signal.matched_points
  const creatorPath = signal.group_id && signal.source_id
    ? `/groups/${signal.group_id}/creators/${signal.source_id}`
    : null

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
        {creatorPath ? (
          <Link to={creatorPath} className="signal-meta-link">{signal.source_name || '博主'}</Link>
        ) : (
          <span>{signal.source_name || '博主'}</span>
        )}
        {showGroupName && signal.group_name && signal.group_id && (
          <>
            <span>·</span>
            <Link to={`/groups/${signal.group_id}`} className="signal-meta-link">{signal.group_name}</Link>
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
