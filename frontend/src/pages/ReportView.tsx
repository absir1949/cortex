import { useParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import { useReport } from '../api/reports'

export default function ReportView() {
  const { id } = useParams()
  const { data: report, isLoading } = useReport(Number(id))

  if (isLoading) return <div className="text-muted">加载中...</div>
  if (!report) return <div className="text-danger">未找到</div>

  return (
    <div className="space-y-4">
      <div>
        <div className="text-xs text-muted">
          {report.kind} · {report.created_at.slice(0, 19)}
        </div>
        <h1 className="text-2xl font-semibold">{report.title}</h1>
        <div className="flex gap-2 mt-2">
          <a
            href={`/api/reports/${report.id}/download?format=md`}
            className="btn-ghost text-xs"
          >
            下载 MD
          </a>
          {report.content_json_path && (
            <a
              href={`/api/reports/${report.id}/download?format=json`}
              className="btn-ghost text-xs"
            >
              下载 JSON
            </a>
          )}
        </div>
      </div>

      <div className="card prose-cortex">
        <ReactMarkdown>{report.content_md || '（空）'}</ReactMarkdown>
      </div>
    </div>
  )
}
