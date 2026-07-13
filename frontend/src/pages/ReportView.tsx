import { useParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import { useReport } from '../api/reports'
import { getAuthToken } from '../api/client'

function copyText(text: string) {
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(
      () => alert('已复制全文'),
      () => fallbackCopy(text),
    )
  } else {
    fallbackCopy(text)
  }
}

function fallbackCopy(text: string) {
  const ta = document.createElement('textarea')
  ta.value = text
  ta.style.position = 'fixed'
  ta.style.opacity = '0'
  document.body.appendChild(ta)
  ta.select()
  try {
    document.execCommand('copy')
    alert('已复制全文')
  } catch {
    alert('复制失败，请手动选择文本复制')
  }
  document.body.removeChild(ta)
}

function downloadReport(reportId: number, format: 'md' | 'json') {
  const token = getAuthToken()
  fetch(`/api/reports/${reportId}/download?format=${format}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
    .then((res) => {
      if (!res.ok) throw new Error('下载失败')
      return res.blob()
    })
    .then((blob) => {
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `report_${reportId}.${format}`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    })
    .catch(() => alert('下载失败，请重试'))
}

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
          <button
            onClick={() => copyText(report.content_md || '')}
            className="btn-ghost text-xs"
          >
            复制全文
          </button>
          <button
            onClick={() => downloadReport(report.id, 'md')}
            className="btn-ghost text-xs"
          >
            下载 MD
          </button>
          {report.content_json_path && (
            <button
              onClick={() => downloadReport(report.id, 'json')}
              className="btn-ghost text-xs"
            >
              下载 JSON
            </button>
          )}
        </div>
      </div>

      <div className="card prose-cortex">
        <ReactMarkdown>{report.content_md || '（空）'}</ReactMarkdown>
      </div>
    </div>
  )
}
