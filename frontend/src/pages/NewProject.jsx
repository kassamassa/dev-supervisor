import { useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { RAILWAY_URL } from "../supabase"

const WIZARD_STEPS = ["要件入力", "壁打ち", "タスク確認", "実行開始"]

export default function NewProject() {
  const nav = useNavigate()
  const [wizardStep, setWizardStep] = useState(0)
  const [projectName, setProjectName] = useState("")
  const [initialReq, setInitialReq] = useState("")
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState("")
  const [chatLoading, setChatLoading] = useState(false)
  const [tasks, setTasks] = useState([])
  const [launching, setLaunching] = useState(false)
  const msgEndRef = useRef(null)

  async function callBrainstorm(message, history) {
    try {
      const r = await fetch(`${RAILWAY_URL}/brainstorm`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, history }),
      })
      return await r.json()
    } catch { return { reply: "エラーが発生しました。", has_tasks: false, tasks: [] } }
  }

  const [streamSteps, setStreamSteps] = useState([])

  async function startBrainstorm() {
    if (!projectName.trim() || !initialReq.trim()) return
    setWizardStep(1)
    const userMsg = { role: "user", content: `プロジェクト名: ${projectName}\n\n要件:\n${initialReq}` }
    setMessages([userMsg])
    setChatLoading(true)
    setStreamSteps([{ label: "接続中...", status: "running" }])

    try {
      const res = await fetch(`${RAILWAY_URL}/brainstorm/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: userMsg.content, history: [] }),
      })

      if (!res.ok) throw new Error(`HTTP ${res.status}`)

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ""
      let result = null

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split("\n\n")
        buffer = parts.pop()
        for (const chunk of parts) {
          const lines = chunk.trim().split("\n")
          const eventLine = lines.find(l => l.startsWith("event:"))
          const dataLine = lines.find(l => l.startsWith("data:"))
          if (!eventLine || !dataLine) continue
          const event = eventLine.slice(6).trim()
          try {
            const data = JSON.parse(dataLine.slice(5).trim())
            if (event === "step") {
              setStreamSteps(prev => {
                const last = prev[prev.length - 1]
                if (last && last.label === data.label) return prev
                const updated = prev.map(s => s.status === "running" ? { ...s, status: "done" } : s)
                return [...updated, { label: data.label, status: data.status }]
              })
            } else if (event === "result") {
              result = data
            } else if (event === "error") {
              setMessages(prev => [...prev, { role: "assistant", content: `エラー: ${data.message}` }])
            }
          } catch {}
        }
      }

      if (result) {
        setMessages(prev => [...prev, { role: "assistant", content: result.reply }])
        if (result.has_tasks && result.tasks?.length > 0) {
          setTasks(result.tasks)
          setWizardStep(2)
        }
      } else {
        // SSEでresultが来なかった場合は通常エンドポイントにフォールバック
        throw new Error("no result")
      }
    } catch (e) {
      // フォールバック: 通常の /brainstorm エンドポイント
      setStreamSteps([{ label: "⏳ AI に接続中（フォールバック）...", status: "running" }])
      try {
        const res = await callBrainstorm(userMsg.content, [])
        setMessages(prev => [...prev, { role: "assistant", content: res.reply }])
        if (res.has_tasks && res.tasks?.length > 0) {
          setTasks(res.tasks)
          setWizardStep(2)
        }
      } catch {
        setMessages(prev => [...prev, { role: "assistant", content: "接続エラーが発生しました。しばらく待ってから再度お試しください。" }])
      }
    } finally {
      setChatLoading(false)
      setStreamSteps([])
    }
    setTimeout(() => msgEndRef.current?.scrollIntoView({ behavior: "smooth" }), 100)
  }

  async function sendChat() {
    const text = input.trim()
    if (!text || chatLoading) return
    setInput("")
    const newMsgs = [...messages, { role: "user", content: text }]
    setMessages(newMsgs)
    setChatLoading(true)
    const res = await callBrainstorm(text, messages)
    const finalMsgs = [...newMsgs, { role: "assistant", content: res.reply }]
    setMessages(finalMsgs)
    setChatLoading(false)
    if (res.has_tasks && res.tasks?.length > 0) { setTasks(res.tasks); setWizardStep(2) }
    setTimeout(() => msgEndRef.current?.scrollIntoView({ behavior: "smooth" }), 100)
  }

  async function launchPipeline() {
    setLaunching(true)
    setWizardStep(3)
    try {
      const r = await fetch(`${RAILWAY_URL}/pipeline/start`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_name: projectName, requirements: initialReq }),
      })
      const data = await r.json()
      if (data.session_id) { setTimeout(() => nav(`/pipeline/${data.session_id}`), 800); return }
    } catch {}
    setLaunching(false)
    setWizardStep(2)
  }

  return (
    <div className="brainstorm-wrap">
      <div>
        <h1>新規プロジェクト作成</h1>
        <div style={{ display: "flex", marginBottom: 28 }}>
          {WIZARD_STEPS.map((s, i) => (
            <div key={i} style={{ flex: 1, textAlign: "center" }}>
              <div style={{
                width: 30, height: 30, borderRadius: "50%", margin: "0 auto 6px",
                background: i < wizardStep ? "#16a34a" : i === wizardStep ? "#4f46e5" : "#2d3148",
                color: i <= wizardStep ? "#fff" : "#64748b",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: "0.8rem", fontWeight: 700,
              }}>
                {i < wizardStep ? "✓" : i + 1}
              </div>
              <div style={{ fontSize: "0.7rem", color: i === wizardStep ? "#818cf8" : "#475569" }}>{s}</div>
            </div>
          ))}
        </div>
      </div>

      {wizardStep === 0 && (
        <div className="card">
          <h2 style={{ marginBottom: 16 }}>要件を入力してください</h2>
          <div className="form-group">
            <label>プロジェクト名</label>
            <input value={projectName} onChange={e => setProjectName(e.target.value)} placeholder="例: ユーザー認証システム" />
          </div>
          <div className="form-group">
            <label>要件・構想（自由記述）</label>
            <textarea rows={7} value={initialReq} onChange={e => setInitialReq(e.target.value)}
              placeholder="JWTトークンを使ったログイン機能を作りたい。パスワードリセット機能も必要。" />
          </div>
          <button className="btn btn-primary" style={{ width: "100%" }}
            onClick={startBrainstorm} disabled={!projectName.trim() || !initialReq.trim()}>
            壁打ちを開始する →
          </button>
        </div>
      )}

      {wizardStep === 1 && (
        <div className="card">
          <div className="section-label" style={{ marginBottom: 12 }}>壁打ち中 — 「{projectName}」</div>
          <div className="chat-wrap">
            <div className="chat-messages" style={{ height: 360 }}>
              {messages.map((m, i) => (
                <div key={i} className={`chat-msg chat-msg-${m.role}`}>{m.content}</div>
              ))}
              {chatLoading && streamSteps.length === 0 && (
                <div className="chat-msg chat-msg-assistant"><span className="spinner" /></div>
              )}
              {chatLoading && streamSteps.length > 0 && (
                <div className="chat-msg chat-msg-assistant" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {streamSteps.map((s, i) => (
                    <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, opacity: s.status === "done" ? 0.5 : 1 }}>
                      {s.status === "running" ? <span className="spinner" style={{ width: 14, height: 14 }} /> : <span>✅</span>}
                      <span style={{ fontSize: "0.85rem" }}>{s.label}</span>
                    </div>
                  ))}
                </div>
              )}
              <div ref={msgEndRef} />
            </div>
            <div className="chat-input-row">
              <textarea value={input} onChange={e => setInput(e.target.value)}
                placeholder="回答・補足を入力…"
                onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat() } }} />
              <button className="btn btn-primary" onClick={sendChat} disabled={chatLoading || !input.trim()}>送信</button>
            </div>
          </div>
        </div>
      )}

      {wizardStep === 2 && (
        <div className="card">
          <h2 style={{ marginBottom: 4 }}>タスク分解結果</h2>
          <p style={{ color: "#64748b", fontSize: "0.85rem", marginBottom: 16 }}>
            確認して承認すると、Dify / Railway / Vercel の自動セットアップが始まります。
          </p>
          <div className="task-preview-list">
            {tasks.map((t, i) => (
              <div key={i} className="task-preview-item">
                <strong>#{t.priority || i + 1} {t.title}</strong>
                <p>{t.description}</p>
              </div>
            ))}
          </div>
          <div style={{ display: "flex", gap: 12, marginTop: 20 }}>
            <button className="btn btn-secondary" onClick={() => setWizardStep(1)}>← 戻る</button>
            <button className="btn btn-success" style={{ flex: 1 }} onClick={launchPipeline} disabled={launching}>
              {launching ? <><span className="spinner" /> 起動中…</> : "🚀 承認して自動実行開始"}
            </button>
          </div>
        </div>
      )}

      {wizardStep === 3 && (
        <div className="card" style={{ textAlign: "center", padding: 48 }}>
          <div style={{ fontSize: "2.5rem", marginBottom: 16 }}>🚀</div>
          <h2>パイプラインを起動しています…</h2>
          <p style={{ color: "#64748b", marginTop: 8 }}>自動実行画面に移動します。</p>
          <div style={{ marginTop: 20 }}><span className="spinner" /></div>
        </div>
      )}
    </div>
  )
}