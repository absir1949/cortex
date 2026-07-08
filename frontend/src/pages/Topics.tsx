import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useCreateGroup, useGroupSummaries } from '../api/groups'

export default function Topics() {
  const { data: groups = [], isLoading } = useGroupSummaries(7)
  const createGroup = useCreateGroup()
  const navigate = useNavigate()
  const [showCreate, setShowCreate] = useState(false)
  const [name, setName] = useState('')

  return (
    <div className="topics-page">
      <section className="topics-head">
        <div>
          <h1>专题</h1>
          <div className="topics-meta">
            <span>{groups.length} 个专题</span>
            <span>近 7 天</span>
          </div>
        </div>
        <button className="pill-button primary" onClick={() => setShowCreate((v) => !v)}>
          {showCreate ? '收起' : '订阅'}
        </button>
      </section>

      {showCreate && (
        <form
          className="new-topic-form"
          onSubmit={async (e) => {
            e.preventDefault()
            if (!name.trim()) return
            const group = await createGroup.mutateAsync({
              name: name.trim(),
              defaults: { interval_hours: 24, days: 7, content_limit: 50, comment_top_n: 20 },
            })
            setName('')
            setShowCreate(false)
            navigate(`/groups/${group.id}`)
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

      <section className="topics-list">
        {isLoading && <div className="muted-line">正在加载专题...</div>}
        {groups.length === 0 && !isLoading && <div className="empty-topic">暂无专题</div>}
        {groups.map((group) => (
          <Link to={`/groups/${group.id}`} key={group.id} className="topic-row">
            <div className="topic-row-main">
              <span className="topic-status">{group.enabled ? '更新中' : '已暂停'}</span>
              <strong>{group.name}</strong>
              <small>{group.source_count} 个关注源</small>
            </div>
            <div className="topic-row-stats">
              <span><b>{group.recent_content_count}</b>内容</span>
              <span><b>{group.recent_new_signal_count}</b>新信号</span>
              <span className={group.failed_source_count ? 'warn' : ''}><b>{group.failed_source_count}</b>异常</span>
            </div>
          </Link>
        ))}
      </section>
    </div>
  )
}
