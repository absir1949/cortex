import { useState, type FormEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useCreateResearch } from '../api/research'

export default function ResearchForm() {
  const { id } = useParams()
  const gid = Number(id)
  const create = useCreateResearch(gid)
  const navigate = useNavigate()

  const [question, setQuestion] = useState('')
  const [days, setDays] = useState(7)
  const [limit, setLimit] = useState(10)
  const [topN, setTopN] = useState(20)

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!question.trim()) return
    const { task_id } = await create.mutateAsync({
      question: question.trim(),
      days,
      search_limit: limit,
      comment_top_n: topN,
    })
    navigate(`/tasks/${task_id}`)
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold">追问</h1>
      </div>

      <form onSubmit={onSubmit} className="card space-y-4">
        <div>
          <label className="text-sm text-muted mb-1 block">你的问题</label>
          <textarea
            className="input h-24"
            placeholder="例如：最近一个月微信小店的保证金政策有什么变化？"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
          />
        </div>

        <div className="grid grid-cols-3 gap-4">
          <div>
            <label className="text-sm text-muted mb-1 block">时间范围（天）</label>
            <input
              className="input"
              type="number"
              min={1}
              max={365}
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
            />
          </div>
          <div>
            <label className="text-sm text-muted mb-1 block">视频数量</label>
            <input
              className="input"
              type="number"
              min={1}
              max={50}
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
            />
          </div>
          <div>
            <label className="text-sm text-muted mb-1 block">每条评论数</label>
            <input
              className="input"
              type="number"
              min={0}
              max={100}
              value={topN}
              onChange={(e) => setTopN(Number(e.target.value))}
            />
          </div>
        </div>

        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={() => navigate(`/groups/${gid}`)}>
            取消
          </button>
          <button type="submit" className="btn-primary" disabled={!question.trim() || create.isPending}>
            {create.isPending ? '提交中...' : '开始追问'}
          </button>
        </div>
      </form>
    </div>
  )
}
