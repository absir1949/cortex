import { useNavigate } from 'react-router-dom'

export default function Landing() {
  const navigate = useNavigate()

  return (
    <main className="landing-page">
      <header className="landing-nav">
        <div className="landing-brand">
          <span className="brand-mark">C</span>
          <strong>听风</strong>
        </div>
        <button className="landing-nav-login" onClick={() => navigate('/login')}>
          登录
        </button>
      </header>

      <section className="landing-hero">
        <p className="landing-hero-line">替你盯着一群人。</p>
        <div className="landing-hero-sub">
          <p>他们说什么、不说什么，</p>
          <p>评论里在聊什么，</p>
          <p>风向有没有变——</p>
        </div>
        <p className="landing-hero-tail">
          你不用自己刷，听风替你听着。
        </p>
        <div className="landing-cta">
          <button className="landing-cta-primary" onClick={() => navigate('/login')}>
            开始使用
          </button>
        </div>
      </section>

      <section className="landing-price">
        <div className="landing-price-card">
          <div className="landing-price-amount">¥399<span>/月</span></div>
          <ul className="landing-price-list">
            <li>圈定你关心的博主，听风每天替你听一遍</li>
            <li>口播、评论、直播里的信号，不用自己刷</li>
            <li>发现值得注意的变化，主动告诉你</li>
            <li>随时追问，基于全部积累回答你</li>
          </ul>
          <button className="landing-price-cta" onClick={() => navigate('/login')}>
            订阅听风
          </button>
        </div>
      </section>

      <footer className="landing-footer">
        <span>听风 · 你的行业听风者</span>
      </footer>
    </main>
  )
}
