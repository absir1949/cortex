import { NavLink, Route, Routes } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import GroupLayout from './layouts/GroupLayout'
import GroupDetail from './pages/GroupDetail'
import CreatorDetail from './pages/CreatorDetail'
import ResearchForm from './pages/ResearchForm'
import TaskProgress from './pages/TaskProgress'
import ReportView from './pages/ReportView'
import Settings from './pages/Settings'
import TasksList from './pages/TasksList'

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
  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="topbar-inner">
          <NavLink to="/" className="brand">
            <span className="brand-mark">C</span>
            <span>
              <strong>Cortex</strong>
              <small>你的行业情报订阅</small>
            </span>
          </NavLink>
          <nav className="top-nav">
            <NavItem to="/" label="今日" />
            <NavItem to="/settings" label="设置" />
          </nav>
        </div>
      </header>

      <main className="app-main">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/groups/:id" element={<GroupLayout />}>
            <Route index element={<GroupDetail />} />
            <Route path="creators/:sid" element={<CreatorDetail />} />
          </Route>
          <Route path="/groups/:id/research" element={<ResearchForm />} />
          <Route path="/tasks" element={<TasksList />} />
          <Route path="/tasks/:id" element={<TaskProgress />} />
          <Route path="/reports/:id" element={<ReportView />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  )
}
