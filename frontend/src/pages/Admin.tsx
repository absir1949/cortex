import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  useAdminOverview,
  useClearTargetError,
  useRetryAdminTask,
  useRunAdminTarget,
  useUpdateAdminTarget,
  useUpdateAdminUser,
} from '../api/admin'
import { useReloadScheduler, useSchedulerJobs } from '../api/scheduler'
import { useCancelTask } from '../api/tasks'
import type { AdminOverview, AdminTargetRow, AdminTaskRow, AdminUsageSummary, AdminUserRow } from '../api/types'
import Settings from './Settings'
import { formatTime } from '../utils/time'

type Tab = 'overview' | 'users' | 'targets' | 'tasks' | 'usage' | 'system'

const TABS: { id: Tab; label: string }[] = [
  { id: 'overview', label: '概览' },
  { id: 'users', label: '用户' },
  { id: 'targets', label: '采集' },
  { id: 'tasks', label: '任务' },
  { id: 'usage', label: '用量' },
  { id: 'system', label: '系统' },
]

function statusLabel(status: string) {
  if (status === 'succeeded') return '成功'
  if (status === 'failed') return '失败'
  if (status === 'running') return '运行中'
  if (status === 'pending') return '排队中'
  if (status === 'canceled') return '已取消'
  return status
}

function planLabel(user: AdminUserRow) {
  if (user.role === 'admin') return '管理员'
  if (user.plan === 'pro') return '专业版'
  return '未订阅'
}

function errorMessage(err: unknown) {
  return err instanceof Error ? err.message : '操作失败'
}

function isTargetLocked(target: AdminTargetRow) {
  if (!target.running_task_id || !target.locked_at) return false
  const lockedAt = new Date(target.locked_at).getTime()
  if (Number.isNaN(lockedAt)) return false
  return lockedAt > Date.now() - 120 * 60 * 1000
}

function targetStatusLabel(target: AdminTargetRow) {
  if (target.admin_paused) return '管理员暂停'
  return target.enabled ? '启用' : '停用'
}

function formatNumber(value: number) {
  return new Intl.NumberFormat('zh-CN').format(value || 0)
}

export default function Admin() {
  const [tab, setTab] = useState<Tab>('overview')
  const [notice, setNotice] = useState('')
  const noticeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const shouldPoll = tab === 'overview' || tab === 'targets' || tab === 'tasks'
  const { data, isLoading, error } = useAdminOverview({
    refetchInterval: shouldPoll ? 15000 : false,
  })

  useEffect(() => () => {
    if (noticeTimer.current) clearTimeout(noticeTimer.current)
  }, [])

  const showNotice = (msg: string) => {
    if (noticeTimer.current) clearTimeout(noticeTimer.current)
    setNotice(msg)
    noticeTimer.current = setTimeout(() => setNotice(''), 2500)
  }

  if (isLoading) return <div className="muted-line">正在加载后台...</div>
  if (error || !data) return <div className="empty-topic">后台加载失败</div>

  return (
    <div className="console-page">
      <header className="console-header">
        <div>
          <h1>管理后台</h1>
          <p className="console-subtitle">更新于 {formatTime(data.generated_at)}</p>
        </div>
        <div className="console-header-actions">
          {notice && <span className="console-notice">{notice}</span>}
          <Link className="btn-ghost" to="/tasks">全部任务</Link>
        </div>
      </header>

      <nav className="console-tabs">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={tab === item.id ? 'console-tab active' : 'console-tab'}
            onClick={() => setTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </nav>

      {tab === 'overview' && <OverviewTab stats={data.stats} usage={data.usage} targets={data.targets} tasks={data.tasks} onGoTab={setTab} />}
      {tab === 'users' && <UsersTab users={data.users} onNotice={showNotice} />}
      {tab === 'targets' && <TargetsTab targets={data.targets} onNotice={showNotice} />}
      {tab === 'tasks' && <TasksTab tasks={data.tasks} onNotice={showNotice} />}
      {tab === 'usage' && <UsageTab usage={data.usage} />}
      {tab === 'system' && <SystemTab onNotice={showNotice} />}
    </div>
  )
}

function OverviewTab({
  stats,
  usage,
  targets,
  tasks,
  onGoTab,
}: {
  stats: AdminOverview['stats']
  usage: AdminUsageSummary
  targets: AdminTargetRow[]
  tasks: AdminTaskRow[]
  onGoTab: (tab: Tab) => void
}) {
  const errorTargets = targets.filter((t) => t.last_error)
  const failedTasks = tasks.filter((t) => t.status === 'failed')
  const runningTasks = tasks.filter((t) => t.status === 'running' || t.status === 'pending')

  return (
    <div className="console-stack">
      <section className="console-stat-row">
        <StatChip label="用户" value={stats.users} hint={`${stats.active_users} 活跃`} />
        <StatChip label="专题" value={stats.groups} hint={`${stats.enabled_groups} 更新中`} />
        <StatChip label="采集目标" value={stats.ingest_targets} hint={`${stats.active_targets} 启用`} />
        <StatChip label="运行任务" value={stats.running_tasks} hint={`${stats.failed_tasks} 失败`} />
        <StatChip label="30天 Token" value={stats.llm_actual_tokens_30d} hint={`${formatNumber(usage.allocated_total_tokens_30d)} 分摊`} />
        <StatChip label="异常目标" value={stats.targets_with_error} danger={stats.targets_with_error > 0} />
        <StatChip label="异常关注" value={stats.failed_sources} danger={stats.failed_sources > 0} />
      </section>

      <div className="console-grid-2">
        <section className="card">
          <div className="console-section-head">
            <h2>需要处理</h2>
            <button type="button" className="btn-ghost text-xs" onClick={() => onGoTab('targets')}>去采集</button>
          </div>
          {errorTargets.length === 0 && failedTasks.length === 0 && runningTasks.length === 0 && (
            <div className="muted-line">暂无异常</div>
          )}
          <ul className="console-issue-list">
            {errorTargets.slice(0, 5).map((t) => (
              <li key={`target-${t.id}`}>
                <strong title={t.target_key}>{t.target_key.length > 16 ? t.target_key.slice(0, 16) + '…' : t.target_key}</strong>
                <span>{t.platform} · {t.last_error}</span>
              </li>
            ))}
            {failedTasks.slice(0, 5).map((t) => (
              <li key={`task-${t.id}`}>
                <Link to={`/tasks/${t.id}`}>{t.id.slice(0, 8)}</Link>
                <span>{t.kind} · {t.error?.slice(0, 80) || '失败'}</span>
              </li>
            ))}
          </ul>
        </section>

        <section className="card">
          <div className="console-section-head">
            <h2>运行中</h2>
            <button type="button" className="btn-ghost text-xs" onClick={() => onGoTab('tasks')}>去任务</button>
          </div>
          {runningTasks.length === 0 && <div className="muted-line">无运行中任务</div>}
          <ul className="console-issue-list">
            {runningTasks.map((t) => (
              <li key={t.id}>
                <Link to={`/tasks/${t.id}`}>{t.id.slice(0, 8)}</Link>
                <span>{statusLabel(t.status)} · {t.kind} · {t.owner_phone || '-'}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  )
}

function StatChip({
  label,
  value,
  hint,
  danger = false,
}: {
  label: string
  value: number
  hint?: string
  danger?: boolean
}) {
  return (
    <div className={`console-stat ${danger ? 'danger' : ''}`}>
      <span>{label}</span>
      <strong>{formatNumber(value)}</strong>
      {hint && <small>{hint}</small>}
    </div>
  )
}

function UsersTab({ users, onNotice }: { users: AdminUserRow[]; onNotice: (msg: string) => void }) {
  const updateUser = useUpdateAdminUser()
  const [editingId, setEditingId] = useState<number | null>(null)
  const [form, setForm] = useState({ plan: 'none', expires_at: '' })

  const startEdit = (user: AdminUserRow) => {
    setEditingId(user.id)
    setForm({
      plan: user.plan,
      expires_at: user.expires_at?.slice(0, 10) || '',
    })
  }

  const saveUser = async (user: AdminUserRow) => {
    try {
      await updateUser.mutateAsync({
        id: user.id,
        plan: form.plan,
        expires_at: form.expires_at ? `${form.expires_at}T23:59:59` : null,
      })
      setEditingId(null)
      onNotice(`已更新 ${user.phone}`)
    } catch (err) {
      onNotice(errorMessage(err))
    }
  }

  return (
    <section className="card">
      <div className="console-section-head">
        <h2>用户管理</h2>
        <span className="text-muted text-sm">{users.length} 人</span>
      </div>
      <div className="console-table-wrap">
        <table className="table console-table">
          <thead>
            <tr>
              <th>用户</th>
              <th>状态</th>
              <th>专题</th>
              <th>关注</th>
              <th>最近活动</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {users.map((user) => (
              <tr key={user.id}>
                <td>
                  <strong>{user.nickname || user.phone}</strong>
                  <div className="text-xs text-muted">{user.phone}</div>
                </td>
                <td>
                  {editingId === user.id ? (
                    <div className="console-inline-form">
                      <select className="input" value={form.plan} onChange={(e) => setForm({ ...form, plan: e.target.value })}>
                        <option value="none">未订阅</option>
                        <option value="pro">专业版</option>
                      </select>
                      <input
                        className="input"
                        type="date"
                        value={form.expires_at}
                        onChange={(e) => setForm({ ...form, expires_at: e.target.value })}
                      />
                    </div>
                  ) : (
                    <span className="badge">{planLabel(user)}</span>
                  )}
                </td>
                <td>{user.group_count}</td>
                <td>
                  {user.active_source_count}/{user.source_count}
                  {user.failed_source_count > 0 && <div className="text-xs text-danger">{user.failed_source_count} 异常</div>}
                </td>
                <td className="text-xs text-muted">{formatTime(user.last_activity_at || user.created_at)}</td>
                <td>
                  {user.role === 'admin' ? (
                    <span className="text-xs text-muted">-</span>
                  ) : editingId === user.id ? (
                    <div className="console-row-actions">
                      <button type="button" className="btn-primary text-xs" onClick={() => saveUser(user)}>保存</button>
                      <button type="button" className="btn-ghost text-xs" onClick={() => setEditingId(null)}>取消</button>
                    </div>
                  ) : (
                    <button type="button" className="btn-ghost text-xs" onClick={() => startEdit(user)}>编辑订阅</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function TargetsTab({ targets, onNotice }: { targets: AdminTargetRow[]; onNotice: (msg: string) => void }) {
  const clearError = useClearTargetError()
  const runTarget = useRunAdminTarget()
  const updateTarget = useUpdateAdminTarget()
  const [filter, setFilter] = useState<'all' | 'error' | 'running'>('all')

  const rows = useMemo(() => {
    if (filter === 'error') return targets.filter((t) => t.last_error)
    if (filter === 'running') return targets.filter((t) => isTargetLocked(t))
    return targets
  }, [filter, targets])

  const act = async (label: string, fn: () => Promise<unknown>) => {
    try {
      await fn()
      onNotice(label)
    } catch (err) {
      onNotice(errorMessage(err))
    }
  }

  return (
    <section className="card">
      <div className="console-section-head">
        <h2>采集目标</h2>
        <div className="console-toolbar">
          <select className="input w-32" value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)}>
            <option value="all">全部</option>
            <option value="error">仅异常</option>
            <option value="running">运行中</option>
          </select>
        </div>
      </div>
      <div className="console-table-wrap">
        <table className="table console-table">
          <thead>
            <tr>
              <th>目标</th>
              <th>状态</th>
              <th>订阅</th>
              <th>上次检查</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && <tr><td colSpan={5} className="text-muted text-center py-4">无数据</td></tr>}
            {rows.map((target) => (
              <tr key={target.id}>
                <td>
                  <strong title={target.target_key}>{target.target_key.length > 16 ? target.target_key.slice(0, 16) + '…' : target.target_key}</strong>
                  <div className="text-xs text-muted">{target.platform} · {target.kind}</div>
                  {target.last_error && <div className="text-xs text-danger mt-1">{target.last_error}</div>}
                </td>
                <td>
                  <span className="badge">{targetStatusLabel(target)}</span>
                  {target.running_task_id && (
                    <div className="text-xs mt-1">
                      <Link to={`/tasks/${target.running_task_id}`}>{target.running_task_id.slice(0, 8)}</Link>
                    </div>
                  )}
                </td>
                <td>{target.subscriber_count} 关注 · {target.group_count} 专题</td>
                <td className="text-xs text-muted">{formatTime(target.last_check)}</td>
                <td>
                  <div className="console-row-actions">
                    <button
                      type="button"
                      className="btn-ghost text-xs"
                      disabled={runTarget.isPending || isTargetLocked(target)}
                      onClick={() => act(`已触发 ${target.target_key}`, () => runTarget.mutateAsync(target.id))}
                    >
                      采集
                    </button>
                    {target.last_error && (
                      <button
                        type="button"
                        className="btn-ghost text-xs"
                        disabled={clearError.isPending}
                        onClick={() => act('已清除异常', () => clearError.mutateAsync(target.id))}
                      >
                        清错
                      </button>
                    )}
                    <button
                      type="button"
                      className="btn-ghost text-xs"
                      disabled={updateTarget.isPending}
                      onClick={() => act(
                        target.admin_paused ? '已恢复调度' : '已暂停调度',
                        () => updateTarget.mutateAsync({ id: target.id, enabled: target.admin_paused }),
                      )}
                    >
                      {target.admin_paused ? '恢复' : '暂停'}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function TasksTab({ tasks, onNotice }: { tasks: AdminTaskRow[]; onNotice: (msg: string) => void }) {
  const cancelTask = useCancelTask()
  const retryTask = useRetryAdminTask()
  const [status, setStatus] = useState('')

  const rows = useMemo(
    () => (status ? tasks.filter((t) => t.status === status) : tasks),
    [status, tasks],
  )

  const act = async (label: string, fn: () => Promise<unknown>) => {
    try {
      await fn()
      onNotice(label)
    } catch (err) {
      onNotice(errorMessage(err))
    }
  }

  return (
    <section className="card">
      <div className="console-section-head">
        <h2>最近任务</h2>
        <select className="input w-32" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">全部状态</option>
          <option value="running">运行中</option>
          <option value="pending">排队中</option>
          <option value="failed">失败</option>
          <option value="succeeded">成功</option>
        </select>
      </div>
      <div className="console-table-wrap">
        <table className="table console-table">
          <thead>
            <tr>
              <th>任务</th>
              <th>专题</th>
              <th>用户</th>
              <th>状态</th>
              <th>时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && <tr><td colSpan={6} className="text-muted text-center py-4">无任务</td></tr>}
            {rows.map((task) => (
              <tr key={task.id}>
                <td>
                  <Link to={`/tasks/${task.id}`} className="font-mono text-xs">{task.id.slice(0, 8)}</Link>
                  <div className="text-xs text-muted">{task.kind}{task.source_name ? ` · ${task.source_name}` : ''}</div>
                  {task.error && <div className="text-xs text-danger mt-1">{task.error.slice(0, 100)}</div>}
                </td>
                <td>
                  {task.group_id
                    ? <Link to={`/groups/${task.group_id}`}>{task.group_name || task.group_id}</Link>
                    : '-'}
                </td>
                <td className="text-sm">{task.owner_phone || '-'}</td>
                <td><span className="badge">{statusLabel(task.status)}</span></td>
                <td className="text-xs text-muted">{formatTime(task.created_at)}</td>
                <td>
                  <div className="console-row-actions">
                    {task.status === 'running' && (
                      <button
                        type="button"
                        className="btn-ghost text-xs"
                        onClick={() => act('已发送取消', () => cancelTask.mutateAsync(task.id))}
                      >
                        中断
                      </button>
                    )}
                    {(task.status === 'failed' || task.status === 'canceled') && (
                      <button
                        type="button"
                        className="btn-ghost text-xs"
                        onClick={() => act('已重新提交', () => retryTask.mutateAsync(task.id))}
                      >
                        重试
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function UsageTab({ usage }: { usage: AdminUsageSummary }) {
  return (
    <div className="console-stack">
      <section className="console-stat-row">
        <StatChip label="7天真实 Token" value={usage.actual_total_tokens_7d} />
        <StatChip label="30天真实 Token" value={usage.actual_total_tokens_30d} />
        <StatChip label="30天分摊 Token" value={usage.allocated_total_tokens_30d} />
        <StatChip label="未返回 usage" value={usage.missing_events_30d} danger={usage.missing_events_30d > 0} />
        <StatChip label="调用失败" value={usage.failed_events_30d} danger={usage.failed_events_30d > 0} />
      </section>

      <section className="card">
        <div className="console-section-head">
          <h2>动作真实成本</h2>
          <span className="text-muted text-sm">按 provider 返回 token 统计</span>
        </div>
        <div className="console-table-wrap">
          <table className="table console-table">
            <thead>
              <tr>
                <th>动作</th>
                <th>模型</th>
                <th>调用</th>
                <th>Prompt</th>
                <th>Completion</th>
                <th>总 Token</th>
                <th>异常</th>
              </tr>
            </thead>
            <tbody>
              {usage.by_operation.length === 0 && <tr><td colSpan={7} className="text-muted text-center py-4">暂无用量</td></tr>}
              {usage.by_operation.map((row) => (
                <tr key={`${row.operation}-${row.model}`}>
                  <td><strong>{operationLabel(row.operation)}</strong></td>
                  <td className="text-xs text-muted">{row.model || '-'}</td>
                  <td>{formatNumber(row.call_count)}</td>
                  <td>{formatNumber(row.actual_prompt_tokens)}</td>
                  <td>{formatNumber(row.actual_completion_tokens)}</td>
                  <td><strong>{formatNumber(row.actual_total_tokens)}</strong></td>
                  <td className="text-xs">
                    {row.missing_events || row.failed_events
                      ? `${row.missing_events} 未计量 · ${row.failed_events} 失败`
                      : '-'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <div className="console-grid-2">
        <section className="card">
          <div className="console-section-head">
            <h2>用户分摊</h2>
            <span className="text-muted text-sm">共享调用按受益专题均分</span>
          </div>
          <div className="console-table-wrap">
            <table className="table console-table">
              <thead>
                <tr>
                  <th>用户</th>
                  <th>分摊 Token</th>
                  <th>调用</th>
                  <th>范围</th>
                </tr>
              </thead>
              <tbody>
                {usage.by_user.length === 0 && <tr><td colSpan={4} className="text-muted text-center py-4">暂无用量</td></tr>}
                {usage.by_user.map((row) => (
                  <tr key={row.user_id ?? row.phone}>
                    <td>
                      <strong>{row.nickname || row.phone || '-'}</strong>
                      {row.phone && <div className="text-xs text-muted">{row.phone}</div>}
                    </td>
                    <td>
                      <strong>{formatNumber(row.allocated_total_tokens)}</strong>
                      {row.allocated_total_tokens === 0 && row.allocated_estimated_tokens > 0 && (
                        <div className="text-xs text-muted">估算 {formatNumber(row.allocated_estimated_tokens)}</div>
                      )}
                    </td>
                    <td>{formatNumber(row.call_count)}</td>
                    <td className="text-xs text-muted">{row.group_count} 专题 · {row.source_count} 关注</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="card">
          <div className="console-section-head">
            <h2>博主成本</h2>
            <span className="text-muted text-sm">信号与档案更新归属</span>
          </div>
          <div className="console-table-wrap">
            <table className="table console-table">
              <thead>
                <tr>
                  <th>博主</th>
                  <th>真实 Token</th>
                  <th>分摊 Token</th>
                  <th>用户</th>
                </tr>
              </thead>
              <tbody>
                {usage.by_creator.length === 0 && <tr><td colSpan={4} className="text-muted text-center py-4">暂无博主用量</td></tr>}
                {usage.by_creator.map((row) => (
                  <tr key={row.creator_id ?? row.creator_name}>
                    <td><strong>{row.creator_name || '-'}</strong></td>
                    <td>{formatNumber(row.actual_total_tokens)}</td>
                    <td>
                      <strong>{formatNumber(row.allocated_total_tokens)}</strong>
                      {row.allocated_total_tokens === 0 && row.allocated_estimated_tokens > 0 && (
                        <div className="text-xs text-muted">估算 {formatNumber(row.allocated_estimated_tokens)}</div>
                      )}
                    </td>
                    <td className="text-xs text-muted">{row.user_count} 用户 · {row.call_count} 调用</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  )
}

function operationLabel(operation: string) {
  const labels: Record<string, string> = {
    ask_answer: '问听风',
    report_creator_period: '作者阶段摘要',
    report_group_synthesis: '专题综合',
    insight_cluster: '洞察聚类',
    profile_update: '观点档案',
    report_merge: '报告合并',
    report_source_batch: '报告整理',
    research_answer: '外部搜索回答',
    signal_judge: '信号判定',
  }
  return labels[operation] || operation || 'unknown'
}

function SystemTab({ onNotice }: { onNotice: (msg: string) => void }) {
  const { data: jobs = [] } = useSchedulerJobs()
  const reload = useReloadScheduler()

  const onReload = async () => {
    try {
      await reload.mutateAsync()
      onNotice('调度器已重载')
    } catch (err) {
      onNotice(errorMessage(err))
    }
  }

  return (
    <div className="console-stack">
      <section className="card">
        <div className="console-section-head">
          <h2>调度器</h2>
          <button type="button" className="btn-primary text-xs" disabled={reload.isPending} onClick={onReload}>
            重载
          </button>
        </div>
        <table className="table console-table">
          <thead>
            <tr><th>ID</th><th>名称</th><th>下次运行</th></tr>
          </thead>
          <tbody>
            {jobs.length === 0 && <tr><td colSpan={3} className="text-muted text-center py-4">无 job</td></tr>}
            {jobs.map((job) => (
              <tr key={job.id}>
                <td className="font-mono text-xs">{job.id}</td>
                <td>{job.name}</td>
                <td className="text-xs text-muted">{job.next_run || '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <Settings />
    </div>
  )
}
