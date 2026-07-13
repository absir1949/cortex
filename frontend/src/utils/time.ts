/**
 * 时间格式化工具 —— 统一转东八区（UTC+8）显示。
 *
 * 后端存的是 datetime.now().isoformat()（无时区标记，Docker 里按 UTC 跑），
 * 页面上必须转成东八区才符合用户预期。
 */

export function formatTime(value?: string | null): string {
  if (!value) return '-'
  // 后端返回的 ISO 字符串没有时区后缀（如 2026-07-13T06:38:58.704168）
  // Date 构造器会当本地时区解析，但 Docker 里是 UTC，所以手动补 +00:00 再转
  const normalized = value.includes('+') || value.includes('Z') ? value : value + '+00:00'
  const date = new Date(normalized)
  if (isNaN(date.getTime())) return value.slice(0, 16).replace('T', ' ')
  // toLocaleString 转东八区
  const formatted = date.toLocaleString('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
  // toLocaleString 输出格式 2026/07/13 14:38，统一成 2026-07-13 14:38
  return formatted.replace(/\//g, '-')
}
