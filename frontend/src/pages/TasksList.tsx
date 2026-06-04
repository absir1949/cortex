import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useTasks } from '../api/tasks'

export default function TasksList() {
  const [kind, setKind] = useState<string>('')
  const [status, setStatus] = useState<string>('')
  const { data: tasks = [] } = useTasks({ kind: kind || undefined, status: status || undefined, limit: 100 })

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">任务</h1>

      <div className="flex gap-2">
        <select className="input w-40" value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="">所有类型</option>
          <option value="ingest">ingest</option>
          <option value="research">research</option>
        </select>
        <select className="input w-40" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">所有状态</option>
          <option value="pending">pending</option>
          <option value="running">running</option>
          <option value="succeeded">succeeded</option>
          <option value="failed">failed</option>
          <option value="canceled">canceled</option>
        </select>
      </div>

      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th>ID</th><th>类型</th><th>状态</th><th>创建时间</th><th>完成时间</th>
            </tr>
          </thead>
          <tbody>
            {tasks.length === 0 && <tr><td colSpan={5} className="text-muted text-center py-4">无任务</td></tr>}
            {tasks.map((t) => (
              <tr key={t.id}>
                <td>
                  <Link to={`/tasks/${t.id}`} className="hover:text-accent font-mono text-xs">
                    {t.id.slice(0, 8)}
                  </Link>
                </td>
                <td>{t.kind}</td>
                <td>{t.status}</td>
                <td className="text-xs text-muted">{t.created_at.slice(0, 19)}</td>
                <td className="text-xs text-muted">{t.finished_at?.slice(0, 19) || '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
