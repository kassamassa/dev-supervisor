"""
dev-supervisor バックエンド API
エンドポイント:
  POST /run-task          ②タスク実行（Dify or 手動から呼び出し）
  POST /trigger-pipeline  ①→②自動連鎖（①完了後に呼び出し）
  POST /github-webhook    ③検証（GitHub Actions webhook受信）
  POST /notify            ④通知（他ワークフローから呼び出し）
  GET  /health
"""
import sys
import io
import hmac
import hashlib
import os
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from workflow_02_task_exec import run as run_task
from workflow_03_verify import handle_github_actions_webhook, process_test_result
from workflow_01_chain import trigger_task_pipeline, trigger_single_task
from workflow_04_notify import notify

app = FastAPI(title="dev-supervisor API", version="0.5.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")


# ─────────────── リクエストモデル ───────────────

class TaskRequest(BaseModel):
    task_id: str
    project_id: str


class PipelineRequest(BaseModel):
    project_id: str


class ManualTestResult(BaseModel):
    """テスト結果を手動で渡す（GitHub Actionsがない場合のテスト用）"""
    task_id: str
    project_id: str
    branch_name: str
    conclusion: str          # "success" | "failure"
    error_log: str = ""


class NotifyRequest(BaseModel):
    notify_type: str
    params: dict = {}


class BrainstormRequest(BaseModel):
    message: str
    history: list = []  # [{role: "user"|"assistant", content: str}]
    project_id: str = ""  # 既存プロジェクトへの追加の場合


class CreateProjectRequest(BaseModel):
    name: str
    requirements: str
    tasks: list  # [{title, description, priority}]


class PipelineStartRequest(BaseModel):
    project_name: str
    requirements: str
    project_id: str = ""


class PipelineResumeRequest(BaseModel):
    session_id: str
    user_data: dict = {}  # ユーザーが入力したトークン等


# ─────────────── ② タスク実行 ───────────────

@app.post("/run-task")
async def api_run_task(req: TaskRequest, background: BackgroundTasks):
    """②タスク実行ワークフロー（同期実行）"""
    try:
        result = await run_task(req.task_id, req.project_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────── ①→② 自動連鎖 ───────────────

@app.post("/trigger-pipeline")
async def api_trigger_pipeline(req: PipelineRequest):
    """①完了後に呼び出す: 全pendingタスクを順次②で実行"""
    try:
        result = await trigger_task_pipeline(req.project_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────── ③ 検証ワークフロー ───────────────

@app.post("/github-webhook")
async def api_github_webhook(request: Request):
    """GitHub Actions の workflow_run webhook を受信"""
    body = await request.body()

    # 署名検証（GITHUB_WEBHOOK_SECRETが設定されている場合）
    if GITHUB_WEBHOOK_SECRET:
        sig_header = request.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(
            GITHUB_WEBHOOK_SECRET.encode(), body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig_header, expected):
            raise HTTPException(status_code=401, detail="Invalid signature")

    event_type = request.headers.get("X-GitHub-Event", "")
    if event_type not in ("workflow_run", "check_run", "check_suite"):
        return {"status": "skipped", "event": event_type}

    import json
    payload = json.loads(body)
    result = await handle_github_actions_webhook(payload)
    return result


@app.post("/test-result")
async def api_test_result(req: ManualTestResult):
    """テスト結果を手動で渡すエンドポイント（テスト・開発用）"""
    from supabase_client import get_task
    task = await get_task(req.task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {req.task_id} not found")
    result = await process_test_result(
        task=task,
        task_id=req.task_id,
        project_id=req.project_id,
        branch_name=req.branch_name,
        conclusion=req.conclusion,
        error_log=req.error_log,
    )
    return result


# ─────────────── ④ 通知 ───────────────

@app.post("/notify")
async def api_notify(req: NotifyRequest):
    """④通知ワークフロー（他ワークフローから呼び出し）"""
    msg = await notify(req.notify_type, **req.params)
    return {"status": "sent", "message": msg}


# ─────────────── 壁打ち ───────────────

BRAINSTORM_SYSTEM_PROMPT = """あなたはAI開発監督システムのアシスタントです。
ユーザーから開発要件を受け取り、以下を行います:
1. 要件が曖昧な場合は具体的な質問を1〜3個する
2. 要件が明確になったらタスク分解を行い、JSON形式で返す

タスク分解が完了した場合は必ず以下のJSON形式を含めてください:
<tasks>
[
  {"title": "タスク名", "description": "詳細説明", "priority": 1},
  ...
]
</tasks>

タスク分解前の質問フェーズではJSONを含めず、自然な日本語で質問してください。
優先度は1(高)〜5(低)で設定してください。"""



async def _call_dify_brainstorm(message: str, history: list) -> str:
    """dify_brainstorm ワークフローを呼び出して回答テキストを返す"""
    import httpx
    from config import DIFY_BRAINSTORM_KEY, DIFY_BASE

    if not DIFY_BRAINSTORM_KEY:
        raise HTTPException(
            status_code=503,
            detail="DIFY_BRAINSTORM_KEY が未設定です。dify/dify_brainstorm.yml を Dify にインポートして Railway 環境変数に設定してください。"
        )

    # 会話履歴を文字列化して history 変数に渡す
    history_text = ""
    for m in history:
        role = "ユーザー" if m["role"] == "user" else "アシスタント"
        history_text += f"{role}: {m['content']}\n"

    resp = httpx.post(
        f"{DIFY_BASE}/workflows/run",
        json={
            "inputs": {
                "message": message,
                "history": history_text,
            },
            "response_mode": "blocking",
            "user": "brainstorm",
        },
        headers={"Authorization": f"Bearer {DIFY_BRAINSTORM_KEY}", "Content-Type": "application/json"},
        timeout=90,
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Dify error {resp.status_code}: {resp.text[:200]}")

    data = resp.json().get("data", {})
    outputs = data.get("outputs", {})
    return outputs.get("text") or outputs.get("answer") or str(outputs)


@app.post("/brainstorm")
async def api_brainstorm(req: BrainstormRequest):
    """壁打ちエンドポイント（非SSE版・後方互換）— Dify LLM ノードで実行"""
    import re, json as _json

    try:
        reply = await _call_dify_brainstorm(req.message, req.history)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    tasks_match = re.search(r'<tasks>(.*?)</tasks>', reply, re.DOTALL)
    tasks = []
    if tasks_match:
        try:
            tasks = _json.loads(tasks_match.group(1).strip())
        except Exception:
            pass
    return {"reply": reply, "tasks": tasks, "has_tasks": len(tasks) > 0}


@app.post("/brainstorm/stream")
async def api_brainstorm_stream(req: BrainstormRequest):
    """壁打ち SSE ストリーミング版: 進捗ステップをリアルタイム配信"""
    import re, json as _json, asyncio

    async def generate():
        def sse(event: str, data: dict) -> str:
            return f"event: {event}\ndata: {_json.dumps(data, ensure_ascii=False)}\n\n"

        yield sse("step", {"status": "running", "label": "接続中..."})
        await asyncio.sleep(0.3)
        yield sse("step", {"status": "running", "label": "⏳ 要件を分析中..."})
        await asyncio.sleep(0.5)
        yield sse("step", {"status": "running", "label": "⏳ 曖昧な点を確認中..."})
        await asyncio.sleep(0.4)

        reply = ""
        error = None

        try:
            yield sse("step", {"status": "running", "label": "⏳ タスクを分解中..."})
            reply = await _call_dify_brainstorm(req.message, req.history)
        except Exception as e:
            error = str(e)

        if error:
            yield sse("error", {"message": error})
            return

        # タスク分解 JSON 検出
        tasks_match = re.search(r'<tasks>(.*?)</tasks>', reply, re.DOTALL)
        tasks = []
        if tasks_match:
            try:
                tasks = _json.loads(tasks_match.group(1).strip())
            except Exception:
                pass

        yield sse("step", {"status": "done", "label": "✅ 完了"})
        await asyncio.sleep(0.2)
        yield sse("result", {
            "reply": reply,
            "tasks": tasks,
            "has_tasks": len(tasks) > 0,
        })

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/create-project")
async def api_create_project(req: CreateProjectRequest):
    """新規プロジェクトとタスクをSupabaseに作成して実行開始"""
    import uuid
    from supabase_client import supa_post, supa_patch
    from workflow_01_chain import trigger_task_pipeline

    # プロジェクト作成
    project_id = str(uuid.uuid4())
    project_data = {
        "id": project_id,
        "name": req.name,
        "requirmentts": req.requirements,
        "status": "active",
        "file_map": {},
    }
    await supa_post("projects", project_data)

    # タスク作成
    task_ids = []
    for i, t in enumerate(req.tasks):
        task_id = str(uuid.uuid4())
        task_ids.append(task_id)
        await supa_post("tasks", {
            "id": task_id,
            "project_id": project_id,
            "title": t.get("title", ""),
            "description": t.get("description", ""),
            "priority": t.get("priority", i + 1),
            "status": "pending",
            "dependencies": [],
        })

    # パイプライン起動
    try:
        await trigger_task_pipeline(project_id)
    except Exception:
        pass  # 非同期実行失敗は無視、プロジェクト作成は成功扱い

    return {
        "status": "created",
        "project_id": project_id,
        "task_count": len(task_ids),
    }


# ─────────────── Phase 2-A 動的パイプライン ───────────────

@app.post("/pipeline/start")
async def api_pipeline_start(req: PipelineStartRequest, background: BackgroundTasks):
    """動的パイプライン開始: セッション作成 → バックグラウンドで実行"""
    from pipeline_executor import create_pipeline_session, run_pipeline
    from supabase_client import supa_post
    import uuid

    project_id = req.project_id or str(uuid.uuid4())

    if not req.project_id:
        await supa_post("projects", {
            "id": project_id,
            "name": req.project_name,
            "requirmentts": req.requirements,
            "status": "active",
            "file_map": {},
        })

    result = await create_pipeline_session(project_id, req.requirements, req.project_name)
    background.add_task(run_pipeline, result["session_id"])
    return result


@app.post("/pipeline/resume")
async def api_pipeline_resume(req: PipelineResumeRequest, background: BackgroundTasks):
    """ブロッカー解除後にパイプラインを再開"""
    from pipeline_executor import run_pipeline, get_session
    session = await get_session(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    background.add_task(run_pipeline, req.session_id, req.user_data)
    return {"status": "resuming", "session_id": req.session_id}


@app.get("/pipeline/session/{session_id}")
async def api_pipeline_session(session_id: str):
    """セッション + ステップ状態を取得"""
    from pipeline_executor import get_session, get_steps, BLOCKER_MESSAGES
    session = await get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    steps = await get_steps(session_id)
    blocker_info = None
    if session.get("blocker_type"):
        blocker_info = BLOCKER_MESSAGES.get(session["blocker_type"])
    return {"session": session, "steps": steps, "blocker_info": blocker_info}


# ─────────────── ヘルスチェック ───────────────

@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": "0.7.0",
        "endpoints": [
            "/run-task", "/trigger-pipeline", "/github-webhook",
            "/test-result", "/notify", "/brainstorm", "/brainstorm/stream",
            "/create-project", "/pipeline/start", "/pipeline/resume",
            "/pipeline/session/{id}",
        ],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8002, reload=True)
