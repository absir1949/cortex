/**
 * 时间格式化工具。
 *
 * 系统里有两类时间：
 *   - 平台返回的时间（create_time、视频发布时间）：已经是东八区，直接显示。
 *   - 系统生成的时间（created_at、first_seen_at）：服务器在 UTC 环境，
 *     存的是 UTC，理论上需要 +8。
 *
 * 但目前后端 datetime.now() 在 Docker 里跑的是 UTC，前端无法区分一个
 * ISO 字符串到底是 UTC 还是 CST（都没有时区后缀）。统一加 +8 会导致
 * 平台时间被加两遍。因此暂时不做时区转换，直接格式化显示原始值。
 *
 * 后续如果要彻底解决：后端在写入 DB 时统一用东八区（settings 里设时区
 * 或用 datetime.now(timezone(timedelta(hours=8)))），这样所有时间一致。
 */

export function formatTime(value?: string | null): string {
  if (!value) return '-'
  return value.slice(0, 16).replace('T', ' ')
}
