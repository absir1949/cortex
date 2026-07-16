const revealItems = document.querySelectorAll("[data-reveal]")

if ("IntersectionObserver" in window) {
  const revealObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible")
          revealObserver.unobserve(entry.target)
        }
      })
    },
    { threshold: 0.14 }
  )

  revealItems.forEach((item) => revealObserver.observe(item))
} else {
  revealItems.forEach((item) => item.classList.add("is-visible"))
}

const trialForm = document.querySelector("#trialForm")
const formNote = document.querySelector("#formNote")

trialForm?.addEventListener("submit", (event) => {
  event.preventDefault()

  const formData = new FormData(trialForm)
  const email = String(formData.get("email") || "").trim()
  const wechat = String(formData.get("wechat") || "").trim()
  const industry = String(formData.get("industry") || "").trim()
  const sources = String(formData.get("sources") || "").trim()
  const leadEmail = trialForm.dataset.leadEmail || "hello@aitingfeng.cn"

  if (!email || !wechat) {
    formNote.textContent = "请先填写邮箱和微信，我们才好联系你。"
    formNote.classList.remove("is-success")
    return
  }

  const subject = "申请听风试用"
  const body = [
    "你好，我想申请听风试用。",
    "",
    `邮箱：${email}`,
    `微信：${wechat}`,
    `关注行业：${industry || "未填写"}`,
    "",
    "希望听风帮我盯：",
    sources || "未填写",
  ].join("\n")

  const mailto = `mailto:${leadEmail}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`
  window.location.href = mailto

  formNote.textContent = "申请邮件已经生成。发送后，我们会根据适配情况联系你。"
  formNote.classList.add("is-success")
})
