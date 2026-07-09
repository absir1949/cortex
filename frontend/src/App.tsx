import { Navigate, NavLink, Route, Routes, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'
import Dashboard from './pages/Dashboard'
import Topics from './pages/Topics'
import GroupLayout from './layouts/GroupLayout'
import GroupDetail from './pages/GroupDetail'
import CreatorDetail from './pages/CreatorDetail'
import ListeningManage from './pages/ListeningManage'
import ResearchForm from './pages/ResearchForm'
import TaskProgress from './pages/TaskProgress'
import ReportView from './pages/ReportView'
import Settings from './pages/Settings'
import TasksList from './pages/TasksList'
import Login from './pages/Login'
import { useAuth } from './auth/AuthContext'

function NavItem({ to, label }: { to: string; label: string }) {
  return (
    <NavLink
      to={to}
      end={to === '/'}
      className={({ isActive }) => `top-nav-item ${isActive ? 'active' : ''}`}
    >
      {label}
    </NavLink>
  )
}

export default function App() {
  const auth = useAuth()
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/*" element={<RequireAuth><AppShell isAdmin={auth.isAdmin} userLabel={auth.user?.nickname || auth.user?.phone || ''} onLogout={auth.logout} /></RequireAuth>} />
    </Routes>
  )
}

function RequireAuth({ children }: { children: ReactNode }) {
  const auth = useAuth()
  const location = useLocation()
  if (auth.isLoading) {
    return <div className="auth-loading">正在进入听风...</div>
  }
  if (!auth.isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />
  }
  return <>{children}</>
}

function AppShell({
  isAdmin,
  userLabel,
  onLogout,
}: {
  isAdmin: boolean
  userLabel: string
  onLogout: () => void
}) {
  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="topbar-inner">
          <NavLink to="/" className="brand">
            <span className="brand-mark">C</span>
            <span>
              <strong>听风</strong>
              <small>你的行业听风者</small>
            </span>
          </NavLink>
          <nav className="top-nav">
            <NavItem to="/" label="今日" />
            <NavItem to="/topics" label="专题" />
            {isAdmin && <NavItem to="/settings" label="设置" />}
          </nav>
          <div className="account-chip">
            <span>{userLabel}</span>
            <button type="button" onClick={onLogout}>退出</button>
          </div>
        </div>
      </header>

      <main className="app-main">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/topics" element={<Topics />} />
          <Route path="/groups/:id" element={<GroupLayout />}>
            <Route index element={<GroupDetail />} />
            <Route path="listening" element={<ListeningManage />} />
            <Route path="research" element={<ResearchForm />} />
          </Route>
          <Route path="/groups/:id/creators/:sid" element={<CreatorDetail />} />
          <Route path="/tasks" element={<TasksList />} />
          <Route path="/tasks/:id" element={<TaskProgress />} />
          <Route path="/reports/:id" element={<ReportView />} />
          {isAdmin && <Route path="/settings" element={<Settings />} />}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}
