import { useEffect, useRef, useState } from "react"
import { useParams, useNavigate } from "react-router-dom"
import { supabase, RAILWAY_URL } from "../supabase"

const STATUS_ICON = {
  pending: { icon: "○", color: "#475569" },
  running: { icon: "⟳", color: "#60a5fa" },
  done:    { icon: "✓", color: "#4ade80" },
  blocked: { icon: "!", color: "#fb923c" },
}

function StepItem({ step }) {
  const s = STATUS_ICON[step.status] || STATUS_ICON.pending
  return (
    <div style={{
      display: "flex", alignItems: "flex-start", gap: 12, padding: "12px 0",
      borderBottom: "1px solid #1e2235",
      opacity: step.status === "pending" ? 0.45 : 1,
    }}>
      <div style={{
        width: 28, height: 28, borderRadius: "50%", flexShrink: 0,
        display: "flex", alignItems: "center", justifyContent: "center",
        background: step.status === "done" ? "#14532d" :
                    step.status === "running" ? "#1e3a5f" :
                    step.status === "blocked" ? "#431407" : "#1e2235",
        color: s.color, fontWeight: 700, fontSize: "0.85rem",
        animation: step.status === "running" ? "spin 1s linear infinite" : "none",
      }}>
        {s.icon}
      </div>
      <div style={{ flex: 1 }}>
        <div style={{
          fontWeight: 500, fontSize: "0.875rem",
          color: step.status === "done" ? "#94a3b8" : "#e2e8f0",
        }}>
          {step.step_name}
        </div>
        {step.result && step.status !== "pending" && (
          <div style={{ fontSize: "0.78rem", color: "#64748b", marginTop: 3, whiteSpace: "pre-wrap" }}>
            {step.result.slice(0, 200)}{step.result.length > 200 ? "…" : ""}
          </div>
        )}
      </div>
      {step.status === "done" && (
        <div style={{ fontSize: "0.7rem", color: "#4ade80", flexShrink: 0 }}>完了</div>
      )}
    </div>
  )
}

function BlockerCard({ blockerInfo, sessionId, onResumed }) {
  const [inputVal, setInputVal] = useState("")
  const [loading, setLoading] = useState(false)
  const [confirmed, setConfirmed] = useState(false)

  async function handleResume() {
    setLoading(true)
    const userData = {}
    if (blockerInfo?.input_key && inputVal.trim()) {
      userData[blockerInfo.input_key] = inputVal.trim()
    }
    try {
      const r = await fetch(`${RAILWAY_URL}/pipeline/resume`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, user_data: userData }),
      })
      if (r.ok) {
        setConfirmed(true)
        setTimeout(() => { onResumed(); setConfirmed(false) }, 1200)
      }
    } catch {}
    setLoading(false)
  }

  if (confirmed) {
    return (
      <div style={{
        background: "#14532d33", border: "1px solid #4ade8066",
        borderRadius: 12, padding: 20, textAlign: "center"
      }}>
        <div style={{ color: "#4ade80", fontSize: "1.1rem" }}>✓ 確認できました。続けます…</div>
      </div>
    )
  }

  return (
    <div style={{
      background: "#1c0a00", border: "1px solid #fb923c66",
      borderRadius: 12, padding: 20, marginBottom: 16
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
        <span style={{ fontSize: "1.3rem" }}>⚠️</span>
        <span style={{ fontWeight: 700, color: "#fb923c", fontSize: "1rem" }}>手動対応が必要です</span>
      </div>
      <div style={{ fontWeight: 600, color: "#fed7aa", marginBottom: 8, fontSize: "0.95rem" }}>
        {blockerInfo?.title}
      </div>
      <div style={{ color: "#fde68a", fontSize: "0.875rem", lineHeight: 1.7, marginBottom: 16 }}>
        {blockerInfo?.description}
      </div>
      {blockerInfo?.input_label && (
        <div style={{ marginBottom: 16 }}>
          <label style={{ display: "block", fontSize: "0.78rem", color: "#94a3b8", marginBottom: 6 }}>
            {blockerInfo.input_label}
          </label>
          <input
            type="password"
            value={inputVal}
            onChange={e => setInputVal(e.target.value)}
            placeholder={blockerInfo.input_label}
            style={{ background: "#0f1117", border: "1px solid #fb923c66" }}
          />
        </div>
      )}
      <button
        className="btn"
        style={{
          width: "100%", background: "#ea580c", color: "#fff",
          opacity: (loading || (blockerInfo?.input_key && !inputVal.trim())) ? 0.5 : 1,
        }}
        onClick={handleResume}
        disabled={loading || (blockerInfo?.input_key && !inputVal.trim())}
      >
        {loading ? "確認中…" : "✅ 完了しました"}
      </button>
    </div>
  )
}

export default function PipelineView() {
  const { sessionId } = useParams()
  const nav = useNavigate()
  const [session, setSession] = useState(null)
  const [steps, setSteps] = useState([])
  const [blockerInfo, setBlockerInfo] = useState(null)
  const [loading, setLoading] = useState(true)
  const bottomRef = useRef(null)

  async function fetchSession() {
    try {
      const r = await fetch(`${RAILWAY_URL}/pipeline/session/${sessionId}`)
      if (r.ok) {
        const data = await r.json()
        setSession(data.session)
        setSteps(data.steps || [])
        setBlockerInfo(data.blocker_info)
      }
    } catch {}
    setLoading(false)
  }

  useEffect(() => { fetchSession() }, [sessionId])

  // Supabase Realtime
  useEffect(() => {
    const ch = supabase
      .channel(`pipeline-${sessionId}`)
      .on("postgres_changes", {
        event: "*", schema: "public", table: "pipeline_steps",
        filter: `session_id=eq.${sessionId}`
      }, () => fetchSession())
      .on("postgres_changes", {
        event: "*", schema: "public", table: "pipeline_sessions",
        filter: `id=eq.${sessionId}`
      }, () => fetchSession())
      .subscribe()
    return () => supabase.removeChannel(ch)
  }, [sessionId])

  // ポーリング（Realtime フォールバック）
  useEffect(() => {
    if (session?.status === "completed") return
    const timer = setInterval(fetchSession, 3000)
    return () => clearInterval(timer)
  }, [session?.status, sessionId])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [steps.length])

  if (loading) return <div className="loading"><span className="spinner" /></div>
  if (!session) return <div className="loading">セッションが見つかりません</div>

  const doneCount = steps.filter(s => s.status === "done").length
  const progress = steps.length > 0 ? Math.round((doneCount / steps.length) * 100) : 0

  return (
    <div style={{ maxWidth: 680, margin: "0 auto" }}>
      <div style={{ marginBottom: 20 }}>
        <div style={{ fontSize: "0.8rem", color: "#64748b", marginBottom: 4 }}>
          動的パイプライン実行中
        </div>
        <h1 style={{ marginBottom: 12 }}>{session.project_name}</h1>

        {/* プログレスバー */}
        <div style={{ background: "#1e2235", borderRadius: 999, height: 8, marginBottom: 8 }}>
          <div style={{
            background: session.status === "completed" ? "#4ade80" :
                        session.status === "blocked" ? "#fb923c" : "#818cf8",
            width: `${progress}%`, height: "100%", borderRadius: 999,
            transition: "width 0.6s ease",
          }} />
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ fontSize: "0.78rem", color: "#64748b" }}>
            {doneCount} / {steps.length} ステップ完了
          </div>
          <div style={{ fontSize: "0.78rem" }}>
            {session.status === "running" && (
              <span style={{ color: "#818cf8" }}>⟳ 実行中...</span>
            )}
            {session.status === "blocked" && (
              <span style={{ color: "#fb923c" }}>⚠ 手動対応待ち</span>
            )}
            {session.status === "completed" && (
              <span style={{ color: "#4ade80" }}>✓ 完了!</span>
            )}
          </div>
        </div>
      </div>

      {/* ブロッカーカード（ステップリストより上に表示） */}
      {session.status === "blocked" && blockerInfo && (
        <BlockerCard
          blockerInfo={blockerInfo}
          sessionId={sessionId}
          onResumed={fetchSession}
        />
      )}

      {/* ステップリスト */}
      <div className="card" style={{ marginBottom: 16 }}>
        {steps.map(step => (
          <StepItem key={step.id} step={step} />
        ))}
        {steps.length === 0 && (
          <div style={{ color: "#64748b", textAlign: "center", padding: 20 }}>
            ステップを読み込み中...
          </div>
        )}
      </div>

      {/* 完了 */}
      {session.status === "completed" && (
        <div className="card" style={{
          textAlign: "center", padding: 32,
          background: "#14532d22", border: "1px solid #4ade8055"
        }}>
          <div style={{ fontSize: "2.5rem", marginBottom: 12 }}>🎉</div>
          <div style={{ fontWeight: 700, fontSize: "1.2rem", color: "#4ade80", marginBottom: 12 }}>
            セットアップ完了！
          </div>
          <div style={{ color: "#86efac", fontSize: "0.875rem", whiteSpace: "pre-wrap", textAlign: "left", lineHeight: 1.8 }}>
            {steps.find(s => s.step_key === "complete")?.result || ""}
          </div>
          <button
            className="btn btn-primary"
            style={{ marginTop: 20 }}
            onClick={() => nav("/")}
          >
            ダッシュボードへ →
          </button>
        </div>
      )}

      <div ref={bottomRef} />

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  )
}
