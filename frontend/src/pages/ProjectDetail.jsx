import { useEffect, useRef, useState } from "react"
import { useParams, Link } from "react-router-dom"
import { supabase, RAILWAY_URL } from "../supabase"

const COLS = [
  { key: "pending",        label: "未着手",    icon: "⏳" },
  { key: "in_progress",    label: "実行中",    icon: "⚡" },
  { key: "review_pending", label: "レビュー待ち", icon: "👀" },
  { key: "done",           label: "完了",      icon: "✅" },
]

export default function ProjectDetail() {
  const { id } = useParams()
  const [project, setProject] = useState(null)
  const [tasks, setTasks] = useState([])
  const [loading, setLoading] = useState(true)
  const [messages, setMessages] = useState([
    { role: "assistant", content: "こんにちは！このプロジェクトについて何か質問や追加要件があればお気軽にどうぞ。" }
  ])
  const [input, setInput] = useState("")
  const [chatLoading, setChatLoading] = useState(false)
  const [running, setRunning] = useState(false)
  const msgEndRef = useRef(null)

  useEffect(() => { load() }, [id])
  useEffect(() => { msgEndRef.current?.scrollIntoView({ behavior: "smooth" }) }, [messages])

  async function load() {
    setLoading(true)
    const { data: p } = await supabase.from("projects").select("*").eq("id", id).single()
    setProject(p)

    const { data: ts } = await supabase
      .from("tasks").select("*").eq("project_id", id).order("priority")
    setTasks(ts || [])
    setLoading(false)
  }

  // Supabase Realtime でタスク更新を監視
  useEffect(() => {
    const ch = supabase
      .channel(`tasks-${id}`)
      .on("postgres_changes", { event: "*", schema: "public", table: "tasks", filter: `project_id=eq.${id}` }, () => {
        load()
      })
      .subscribe()
    return () => supabase.removeChannel(ch)
  }, [id])

  const tasksByStatus = {}
  for (const col of COLS) tasksByStatus[col.key] = []
  for (const t of tasks) {
    const s = t.status || "pending"
    if (!tasksByStatus[s]) tasksByStatus[s] = []
    tasksByStatus[s].push(t)
  }

  async function sendChat() {
    const text = input.trim()
    if (!text || chatLoading) return
    setInput("")
    const newMsgs = [...messages, { role: "user", content: text }]
    setMessages(newMsgs)
    setChatLoading(true)
    try {
      const res = await fetch(`${RAILWAY_URL}/brainstorm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, history: messages, project_id: id }),
      })
      const data = await res.json()
      setMessages([...newMsgs, { role: "assistant", content: data.reply }])
    } catch {
      setMessages([...newMsgs, { role: "assistant", content: "エラーが発生しました。再度お試しください。" }])
    }
    setChatLoading(false)
  }

  async function runPipeline() {
    setRunning(true)
    try {
      await fetch(`${RAILWAY_URL}/trigger-pipeline`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: id }),
      })
      setTimeout(load, 3000)
    } catch { }
    setRunning(false)
  }

  if (loading) return <div className="loading"><span className="spinner" /></div>
  if (!project) return <div className="loading">プロジェクトが見つかりません</div>

  const name = project.name?.replace(/^name:\s*/i, "").split("\n")[0] || id.slice(0, 8)

  return (
    <div className="project-detail">
      <div>
        <Link to="/" style={{ color: "#64748b", fontSize: "0.8rem", textDecoration: "none" }}>← ダッシュボード</Link>
        <div className="project-header" style={{ marginTop: 8 }}>
          <h1>{name}</h1>
          <span className={`badge badge-${project.status || "active"}`}>{project.status || "active"}</span>
        </div>
      </div>

      {/* Kanban */}
      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <div className="section-label">カンバンボード</div>
          <button className="btn btn-secondary" onClick={runPipeline} disabled={running}>
            {running ? <><span className="spinner" /> 実行中…</> : "▶ パイプライン実行"}
          </button>
        </div>
        <div className="kanban">
          {COLS.map(col => (
            <div key={col.key} className="kanban-col">
              <div className="kanban-col-header">
                {col.icon} {col.label}
                <span style={{ marginLeft: "auto", background: "#2d3148", borderRadius: 999, padding: "1px 6px", fontSize: "0.65rem" }}>
                  {tasksByStatus[col.key].length}
                </span>
              </div>
              {tasksByStatus[col.key].length === 0 && (
                <div style={{ color: "#334155", fontSize: "0.75rem", textAlign: "center", paddingTop: 20 }}>—</div>
              )}
              {tasksByStatus[col.key].map(t => (
                <div key={t.id} className="kanban-task">
                  <div className="kanban-task-title">{t.title}</div>
                  {t.description && (
                    <div className="kanban-task-meta">{t.description.slice(0, 60)}{t.description.length > 60 ? "…" : ""}</div>
                  )}
                  <div className="kanban-task-meta" style={{ marginTop: 4 }}>優先度 {t.priority}</div>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>

      {/* Chat */}
      <div className="card">
        <div className="section-label">壁打ちチャット</div>
        <div className="chat-wrap">
          <div className="chat-messages">
            {messages.map((m, i) => (
              <div key={i} className={`chat-msg chat-msg-${m.role}`}>{m.content}</div>
            ))}
            {chatLoading && (
              <div className="chat-msg chat-msg-assistant"><span className="spinner" /></div>
            )}
            <div ref={msgEndRef} />
          </div>
          <div className="chat-input-row">
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              placeholder="追加要件や質問を入力…"
              onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat() } }}
            />
            <button className="btn btn-primary" onClick={sendChat} disabled={chatLoading || !input.trim()}>
              送信
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
