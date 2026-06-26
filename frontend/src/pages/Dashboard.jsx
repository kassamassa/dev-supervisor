import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { supabase } from "../supabase"

const STATUS_LABELS = {
  active: "稼働中", paused: "停止中", completed: "完了", draft: "下書き",
}

export default function Dashboard() {
  const [projects, setProjects] = useState([])
  const [loading, setLoading] = useState(true)
  const [taskCounts, setTaskCounts] = useState({})

  useEffect(() => {
    load()
  }, [])

  async function load() {
    setLoading(true)
    const { data: ps } = await supabase
      .from("projects")
      .select("*")
      .order("created_at", { ascending: false })
    setProjects(ps || [])

    if (ps && ps.length > 0) {
      const ids = ps.map(p => p.id)
      const { data: tasks } = await supabase
        .from("tasks")
        .select("project_id, status")
        .in("project_id", ids)
      const counts = {}
      for (const t of tasks || []) {
        if (!counts[t.project_id]) counts[t.project_id] = { total: 0, done: 0 }
        counts[t.project_id].total++
        if (t.status === "done") counts[t.project_id].done++
      }
      setTaskCounts(counts)
    }
    setLoading(false)
  }

  if (loading) return <div className="loading"><span className="spinner" /></div>

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <h1>プロジェクト一覧</h1>
        <Link to="/new" className="btn btn-primary">+ 新規プロジェクト</Link>
      </div>

      {projects.length === 0 ? (
        <div className="empty">
          <div style={{ fontSize: "2rem" }}>🚀</div>
          <p>まだプロジェクトがありません。新規プロジェクトを作成してください。</p>
          <Link to="/new" className="btn btn-primary" style={{ marginTop: 16 }}>最初のプロジェクトを作成</Link>
        </div>
      ) : (
        <div className="project-grid">
          {projects.map(p => {
            const c = taskCounts[p.id] || { total: 0, done: 0 }
            const name = p.name?.replace(/^name:\s*/i, "").split("\n")[0] || p.id.slice(0, 8)
            return (
              <Link key={p.id} to={`/project/${p.id}`} className="project-card">
                <div className="project-card-name">{name}</div>
                <div className="project-card-meta">
                  <span className={`badge badge-${p.status || "active"}`}>
                    {STATUS_LABELS[p.status] || p.status || "稼働中"}
                  </span>
                  <span>タスク {c.done}/{c.total}</span>
                  <span>{new Date(p.created_at).toLocaleDateString("ja-JP")}</span>
                </div>
              </Link>
            )
          })}
        </div>
      )}
    </div>
  )
}
