import { FormEvent, useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { useLogin, useRegister, useSendCode } from '../api/auth'
import { getAuthToken } from '../api/client'

type Mode = 'login' | 'register'

export default function Login() {
  const navigate = useNavigate()
  const [mode, setMode] = useState<Mode>('login')
  const [phone, setPhone] = useState('')
  const [code, setCode] = useState('')
  const [inviteCode, setInviteCode] = useState('')
  const sendCode = useSendCode()
  const login = useLogin()
  const register = useRegister()

  if (getAuthToken()) return <Navigate to="/" replace />

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const payload = {
      phone: phone.trim(),
      code: code.trim(),
      invite_code: inviteCode.trim() || undefined,
    }
    if (mode === 'login') {
      await login.mutateAsync(payload)
    } else {
      await register.mutateAsync(payload)
    }
    navigate('/', { replace: true })
  }

  const requestCode = async () => {
    if (!phone.trim()) return
    await sendCode.mutateAsync(phone.trim())
  }

  const pending = login.isPending || register.isPending
  const error = login.error || register.error || sendCode.error

  return (
    <main className="auth-page">
      <section className="auth-panel" aria-label="听风登录">
        <div className="auth-brand">
          <span className="brand-mark">C</span>
          <div>
            <strong>听风</strong>
            <small>你的行业听风者</small>
          </div>
        </div>

        <div className="auth-tabs">
          <button type="button" className={mode === 'login' ? 'active' : ''} onClick={() => setMode('login')}>
            登录
          </button>
          <button type="button" className={mode === 'register' ? 'active' : ''} onClick={() => setMode('register')}>
            注册
          </button>
        </div>

        <form className="auth-form" onSubmit={submit}>
          <label>
            手机号
            <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="请输入手机号" autoComplete="tel" />
          </label>
          <label>
            验证码
            <div className="auth-code-row">
              <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="开发环境填 0000" autoComplete="one-time-code" />
              <button type="button" onClick={requestCode} disabled={!phone.trim() || sendCode.isPending}>
                {sendCode.isPending ? '发送中' : '发码'}
              </button>
            </div>
          </label>
          {mode === 'register' && (
            <label>
              邀请码
              <input value={inviteCode} onChange={(e) => setInviteCode(e.target.value)} placeholder="未开放注册时需要邀请码" />
            </label>
          )}
          {error && <div className="auth-error">{(error as any)?.message || '操作失败'}</div>}
          <button className="auth-submit" disabled={pending || !phone.trim() || !code.trim()}>
            {pending ? '处理中' : mode === 'login' ? '进入听风' : '创建账号'}
          </button>
        </form>
      </section>
    </main>
  )
}
