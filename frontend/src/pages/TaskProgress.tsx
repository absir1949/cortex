import { Link, useParams } from 'react-router-dom'
import { useTask, useCancelTask } from '../api/tasks'

function StatusBadge({ status }: { status: string }) {
  const cls = {
    pending: 'badge',
    running: 'badge-info',
    succeeded: 'badge-ok',
    failed: 'badge-err',
    canceled: 'badge',
  }[status] || 'badge'
  return <span className={cls}>{status}</span>
}

export default function TaskProgress() {
  const { id } = useParams()
  const { data: task, isLoading } = useTask(id)
  const cancel = useCancelTask()

  if (isLoading) return <div className="text-muted">加载中...</div>
  if (!task) return <div className="text-danger">未找到</div>

  const progress = task.progress || {}
  const done = progress.done ?? 0
  const total = progress.total ?? 0
  const percent = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-xs text-muted">{task.id}</div>
          <h1 className="text-2xl font-semibold">{task.kind} 任务</h1>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={task.status} />
          {(task.status === 'running' || task.status === 'pending') && (
            <button className="btn-danger text-xs" onClick={() => cancel.mutate(task.id)}>
              取消
            </button>
          )}
        </div>
      </div>

      <div className="card">
        <div className="flex items-center justify-between mb-2">
          <div className="text-sm text-muted">{progress.stage || '等待中'}</div>
          <div className="text-xs text-muted">
            {total > 0 ? `${done}/${total}` : ''}
          </div>
        </div>
        <div className="h-2 rounded-full bg-border overflow-hidden">
          <div
            className="h-full bg-accent transition-all"
            style={{ width: task.status === 'succeeded' ? '100%' : `${percent}%` }}
          />
        </div>
      </div>

      {task.status === 'succeeded' && task.result?.report_id && (
        <div className="card border-accent/40">
          <div className="text-sm mb-2">研究完成</div>
          <Link to={`/reports/${task.result.report_id}`} className="btn-primary inline-block">
            查看报告
          </Link>
        </div>
      )}

      {task.error && (
        <div className="card border-danger/40">
          <div className="text-danger text-sm font-medium mb-1">错误</div>
          <pre className="text-xs whitespace-pre-wrap text-muted">{task.error}</pre>
        </div>
      )}

      <section>
        <h2 className="text-lg font-semibold mb-2">日志</h2>
        <div className="card max-h-96 overflow-auto font-mono text-xs space-y-1">
          {task.logs.length === 0 && <div className="text-muted">无日志</div>}
          {task.logs.map((log, i) => (
            <div key={i} className="flex gap-2">
              <span className="text-muted">{log.ts.slice(11, 19)}</span>
              <span className={log.level === 'warning' ? 'text-danger' : ''}>{log.message}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
