import { useEffect, useState } from 'react'
import { Link, Outlet, useParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import {
  useGroup,
  useUpdateGroup,
  useRunGroup,
  useAnalyzeGroup,
} from '../api/groups'
import { useSchedulerJobs } from '../api/scheduler'
import { useTask } from '../api/tasks'

function formatTime(value?: string | null) {
  if (!value) return '待安排'
  return value.slice(0, 16).replace('T', ' ')
}

export default function GroupLayout() {
  const { id } = useParams()
  const gid = Number(id)
  const { data: group, isLoading } = useGroup(gid)
  const { data: jobs = [] } = useSchedulerJobs()
  const update = useUpdateGroup(gid)
  const runGroup = useRunGroup(gid)
  const analyzeGroup = useAnalyzeGroup(gid)
  const qc = useQueryClient()

  const [notice, setNotice] = useState('')
  const [showMore, setShowMore] = useState(false)
  const [analyzeTaskId, setAnalyzeTaskId] = useState<string | null>(null)
  const analyzeTask = useTask(analyzeTaskId)

  useEffect(() => {
    setNotice('')
    setShowMore(false)
  }, [gid])

  useEffect(() => {
    if (!analyzeTaskId || !analyzeTask.data) return
    const st = analyzeTask.data.status
    if (st === 'succeeded') {
      const rid = analyzeTask.data.result?.report_id
      setNotice(rid ? '报告已生成。' : '没有可整理的新内容。')
      setAnalyzeTaskId(null)
      qc.invalidateQueries({ queryKey: ['reports', 'group', gid] })
    } else if (st === 'failed' || st === 'canceled') {
      setNotice('整理失败：' + ((analyzeTask.data.error || '').slice(0, 80) || '未知错误'))
      setAnalyzeTaskId(null)
    }
  }, [analyzeTask.data, analyzeTaskId, gid, qc])

  const job = jobs.find((j) => j.id === `group_${gid}`)
  const intervalHours = Number(group?.defaults?.interval_hours || 24)

  if (isLoading) return <div className="muted-line">正在打开专题...</div>
  if (!group) return <div className="text-danger">未找到</div>

  const onRunGroup = async () => {
    await runGroup.mutateAsync({ force: true, analyze: true })
    setNotice('刷新已开始。')
  }

  const onAnalyze = async () => {
    const res = await analyzeGroup.mutateAsync()
    setAnalyzeTaskId(res.task_id)
    setShowMore(false)
    setNotice('正在整理报告。')
  }

  const onToggleEnabled = async () => {
    await update.mutateAsync({ enabled: !group.enabled })
    setShowMore(false)
    setNotice(group.enabled ? '已暂停自动更新。' : '已恢复自动更新。')
  }

  return (
    <div className="topic-page">
      <section className="topic-hero topic-hero-reading">
        <div className="topic-hero-copy">
          <Link to="/" className="back-link">返回今日</Link>
          <h1>{group.name}</h1>
          <div className="topic-meta-line">
            <span>{group.sources.length} 个关注源</span>
            <span>{intervalHours} 小时</span>
            <span>{formatTime(job?.next_run)}</span>
          </div>
        </div>
        <div className="topic-actions compact">
          <button className="pill-button primary" onClick={onRunGroup} disabled={runGroup.isPending}>
            {runGroup.isPending ? '刷新中' : '刷新专题'}
          </button>
          <div className="more-menu-wrap">
            <button className="pill-button" onClick={() => setShowMore((v) => !v)}>更多</button>
            {showMore && (
              <div className="more-menu">
                <button onClick={onAnalyze} disabled={analyzeGroup.isPending}>
                  {analyzeGroup.isPending ? '整理中' : '整理报告'}
                </button>
                <Link to={`/groups/${gid}/research`}>追问</Link>
                <Link to={`/groups/${gid}/listening#settings`}>更新设置</Link>
                <Link to={`/groups/${gid}/listening`}>关注</Link>
                <button onClick={onToggleEnabled}>{group.enabled ? '暂停专题' : '恢复专题'}</button>
              </div>
            )}
          </div>
        </div>
      </section>

      {notice && <div className="notice-line">{notice}</div>}

      <main className="topic-reader topic-reader-wide">
        <Outlet />
      </main>
    </div>
  )
}
