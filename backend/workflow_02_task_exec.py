"""
②タスク実行ワークフロー（リファクタリング版）
- Supabaseから直接タスク取得（Difyの URL生成バグを回避）
- Dify streaming で必要ファイル選定LLMをキャプチャ
- GitHub ブランチ作成・コード生成・Push
- Supabase tasks/projects 更新
- ④通知ワークフロー呼び出し
"""
import re
import json
import httpx
from config import DIFY_BASE, DIFY_TASK_EXEC_KEY, MAX_FIX_ATTEMPTS
from supabase_client import (
    get_task, get_project, update_task, update_project_file_map, insert_execution
)
from github_client import get_main_sha, create_branch, get_file, push_file
from llm_client import select_required_files, generate_code
from workflow_04_notify import notify


def _slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\s_]+", "-", text.strip())
    return text[:40].strip("-")


def _capture_dify_outputs(task_id: str, project_id: str) -> tuple[list[str], list[dict], str]:
    """
    Dify streaming から必要ファイル選定・コード生成の両LLM出力をキャプチャ。
    ブランチ作成ノードで失敗しても、それ以前のLLM出力は取得できる。

    Returns:
        (selected_files, generated_files, summary)
    """
    selected_files: list[str] = []
    generated_files: list[dict] = []
    summary: str = ""
    try:
        payload = {
            "inputs": {"task_id": task_id, "project_id": project_id},
            "response_mode": "streaming",
            "user": "dev-supervisor",
        }
        with httpx.Client(timeout=120) as client:
            with client.stream(
                "POST", f"{DIFY_BASE}/workflows/run",
                json=payload,
                headers={
                    "Authorization": f"Bearer {DIFY_TASK_EXEC_KEY}",
                    "Content-Type": "application/json",
                },
            ) as resp:
                for line in resp.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    try:
                        event = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue
                    if event.get("event") != "node_finished":
                        continue
                    data = event.get("data", {})
                    if data.get("status") != "succeeded":
                        continue
                    title = data.get("title", "")
                    outputs = data.get("outputs", {})
                    text = outputs.get("text", "")
                    text_clean = re.sub(r"```(?:json)?\n?", "", text).strip().rstrip("`").strip()

                    # 必要ファイル選定ノード
                    if title == "必要ファイル選定":
                        m = re.search(r"\{.*?\"required_files\".*?\}", text_clean, re.DOTALL)
                        if m:
                            try:
                                parsed = json.loads(m.group())
                                selected_files = parsed.get("required_files", [])
                            except json.JSONDecodeError:
                                pass

                    # コード生成ノード
                    elif title == "コード生成":
                        # {"files":[...], "summary":"..."} 形式を期待
                        m = re.search(r"\{.*\}", text_clean, re.DOTALL)
                        if m:
                            try:
                                parsed = json.loads(m.group())
                                generated_files = parsed.get("files", [])
                                summary = parsed.get("summary", "")
                            except json.JSONDecodeError:
                                pass
                        # ブランチ作成の前にコード生成が終わればここで取れる
                        # (Difyワークフローのノード順が コード生成→ブランチ作成 の場合)
    except Exception as e:
        print(f"[Dify capture] error: {e}")
    return selected_files, generated_files, summary


def _capture_dify_file_selection(task_id: str, project_id: str) -> list[str]:
    """後方互換のためのラッパー"""
    selected, _, _ = _capture_dify_outputs(task_id, project_id)
    return selected


async def run(task_id: str, project_id: str) -> dict:
    """②タスク実行ワークフロー メイン"""
    log = print  # simple logging

    log(f"[②] START task={task_id[:8]}... project={project_id[:8]}...")

    # 1. タスク・プロジェクト情報取得（Supabaseから直接）
    task = await get_task(task_id)
    if not task:
        raise ValueError(f"Task {task_id} not found")
    project = await get_project(project_id) or {}
    file_map = project.get("file_map") or {}
    log(f"[②] タスク取得: {task['title']} (priority={task.get('priority')})")

    # 2. Dify streaming で 必要ファイル選定 + コード生成 を同時キャプチャ
    log("[②] Dify LLM ストリーミング開始...")
    dify_selected, dify_generated, dify_summary = _capture_dify_outputs(task_id, project_id)
    log(f"[②] Dify キャプチャ: selected={dify_selected}, generated_files={len(dify_generated)}")

    # 必要ファイル選定（Dify → フォールバック）
    selected_paths = dify_selected or await select_required_files(task, file_map)
    log(f"[②] 必要ファイル: {selected_paths}")

    # 3. 選定ファイルの内容取得
    file_contents = {}
    for path in selected_paths:
        content = await get_file(path)
        if content:
            file_contents[path] = content

    # 4. ブランチ作成（Python直接 — Difyのブランチ作成ノードは422エラーのためバイパス）
    priority = task.get("priority") or 0
    branch_name = f"task/{priority:03d}-{_slugify(task['title'])}"
    main_sha = await get_main_sha()
    await create_branch(branch_name, main_sha)
    log(f"[②] ブランチ作成: {branch_name}")

    # 5. コード生成（Dify LLMキャプチャ優先 → Python generate_code フォールバック）
    if dify_generated:
        generated_files = dify_generated
        summary = dify_summary
        log(f"[②] コード生成: Dify LLMから {len(generated_files)}ファイル取得")
    else:
        generated_files, summary = await generate_code(task, file_contents)
        log(f"[②] コード生成: フォールバック {len(generated_files)}ファイル")
    log(f"[②] コード生成完了: {len(generated_files)}ファイル")

    # 6. GitHub Push
    for f in generated_files:
        await push_file(
            path=f["path"],
            content=f["content"],
            branch=branch_name,
            message=f"feat: {task['title']} - {f['path']}",
        )
    log(f"[②] GitHub Push 完了")

    # 7. Supabase 更新
    await update_task(task_id, branch_name=branch_name, status="in_progress")
    await update_project_file_map(project_id, generated_files)
    await insert_execution(task_id, attempt=1, result="code_generated",
                           error_log=f"branch={branch_name}")

    # 8. ④通知
    await notify(
        "task_started",
        task_title=task["title"],
        branch=branch_name,
    )

    result = {
        "status": "success",
        "task_id": task_id,
        "task_title": task["title"],
        "branch": branch_name,
        "files_generated": [f["path"] for f in generated_files],
        "summary": summary,
    }
    log(f"[②] DONE: branch={branch_name}")
    return result
