import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import ProjectDetail from './pages/ProjectDetail'
import NewProject from './pages/NewProject'
import PipelineView from './pages/PipelineView'
import './App.css'

function Nav() {
  const loc = useLocation()
  return (
    <nav className="nav">
      <Link to="/" className="nav-brand">🤖 Dev Supervisor</Link>
      <div className="nav-links">
        <Link to="/" className={loc.pathname === '/' ? 'active' : ''}>ダッシュボード</Link>
        <Link to="/new" className={loc.pathname === '/new' ? 'active' : ''}>+ 新規プロジェクト</Link>
      </div>
    </nav>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Nav />
      <main className="main">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/project/:id" element={<ProjectDetail />} />
          <Route path="/new" element={<NewProject />} />
          <Route path="/pipeline/:sessionId" element={<PipelineView />} />
        </Routes>
      </main>
    </BrowserRouter>
  )
}
