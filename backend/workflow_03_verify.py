"""
③検証ワークフロー
トリガー: GitHub Actions の Webhook 受信
処理:
  テスト結果判定
    → 成功: PR作成
    → 失敗 (修正可能): コード自動修正ループ（上限5回）
    → 失敗 (上限超過/重篤): エスカレーション（壮輝に通知）
"""
import re
from config import MAX_FIX_ATTEMPTS
from supabase_client import get_task, update_task, insert_execution, get_project
from github_client import get_file, push_file, create_pull_request, get_branch_files
from llm_client import analyze_test_error
from workflow_04_notify import notify


ESCALATION_ERRORS = [
    "DatabaseError", "PermissionError", "AuthenticationError",
    "SchemaError", "MigrationError", "EnvironmentError",
    "DBスキーマ", "権限", "認証エラー",
]


def _is_escalation_error(error_log: str) -> bool:
    """即時エスカレーションが必要なエラーか判定"""
    return any(kw in error_log for kw in ESCALATION_ERRORS)


async def _get_branch_file_contents(branch: str) -> dict:
    """ブランチの全ファイル内容を取得"""
    paths = await get_branch_files(branch)
    # コードファイルのみ（.md, .gitignore等は除外）
    code_paths = [
        p for p in paths
        if any(p.endswith(ext) for ext in [".py", ".js", ".ts", ".jsx", ".tsx", ".sql", ".json", ".yaml", ".yml"])
        and not p.startswith(".git")
    ]
    contents = {}
    for path in code_paths[:20]:  # コンテキスト軽量化: 最大20ファイル
        content = await get_file(path, branch=branch)
        if content:
            contents[path] = content
    return contents


async def handle_github_actions_webhook(payload: dict) -> dict:
    """
    GitHub Actions の workflow_run webhook を処理する

    payload 例:
    {
      "action": "completed",
      "workflow_run": {
        "name": "CI",
        "conclusion": "success" | "failure",
        "head_branch": "task/001-...",
        "id": 12345,
      },
      "repository": {"full_name": "kassamassa/Develop"}
    }
    """
    action = payload.get("action")
    run_data = payload.get("workflow_run", {})
    conclusion = run_data.get("conclusion")
    branch_name = run_data.get("head_branch", "")
    run_id = run_data.get("id")

    if action != "completed":
        return {"status": "skipped", "reason": "not completed"}

    # ブランチ名からtask情報を抽出
    if not branch_name.startswith("task/"):
        return {"status": "skipped", "reason": "not a task branch"}

    # Supabaseからタスク取得
    from supabase_client import SUPABASE_URL, SUPA_HEADERS
    import httpx
    async with httpx.AsyncClient() as c:
        r = await c.get(
            f"{SUPABASE_URL}/tasks?branch_name=eq.{branch_name}&select=*",
            headers=SUPA_HEADERS,
        )
        tasks = r.json()

    if not tasks:
        return {"status": "error", "reason": f"task not found for branch {branch_name}"}

    task = tasks[0]
    task_id = task["id"]
    project_id = task["project_id"]

    # テスト結果ログ取得（GitHub Actions API）
    import httpx
    from config import GH_HEADERS, GITHUB_OWNER, GITHUB_REPO
    async with httpx.AsyncClient() as c:
        r = await c.get(
            f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/runs/{run_id}/logs",
            headers=GH_HEADERS,
        )
        # ログはZIPなので、エラーメッセージは別途取得
        jobs_resp = await c.get(
            f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/runs/{run_id}/jobs",
            headers=GH_HEADERS,
        )

    jobs_data = jobs_resp.json() if jobs_resp.status_code == 200 else {}
    error_summary = _extract_error_summary(jobs_data)

    return await process_test_result(
        task=task,
        task_id=task_id,
        project_id=project_id,
        branch_name=branch_name,
        conclusion=conclusion,
        error_log=error_summary,
        run_id=str(run_id),
    )


async def process_test_result(
    task: dict,
    task_id: str,
    project_id: str,
    branch_name: str,
    conclusion: str,
    error_log: str = "",
    run_id: str = "",
) -> dict:
    """テスト結果を処理するコアロジック"""

    if conclusion == "success":
        return await _handle_success(task, task_id, branch_name)

    # 失敗の場合
    return await _handle_failure(task, task_id, project_id, branch_name, error_log)


async def _handle_success(task: dict, task_id: str, branch_name: str) -> dict:
    """テスト成功 → PR作成"""
    title = f"feat: {task['title']}"
    body = (
        f"## タスク\n{task['title']}\n\n"
        f"## 説明\n{task.get('description', '')}\n\n"
        f"## 変更内容\n自動生成コードのテストが通過しました。\n\n"
        f"---\n*dev-supervisor により自動生成*"
    )
    pr = await create_pull_request(title=title, branch=branch_name, body=body)
    pr_number = pr.get("number", "?")

    await update_task(task_id, status="review_pending")
    await insert_execution(task_id, attempt=1, result="pr_created",
                           error_log=f"pr_number={pr_number}")
    await notify(
        "test_passed",
        task_title=task["title"],
        branch=branch_name,
        pr_number=pr_number,
    )
    return {"status": "pr_created", "pr_number": pr_number, "branch": branch_name}


async def _handle_failure(
    task: dict, task_id: str, project_id: str, branch_name: str, error_log: str
) -> dict:
    """テスト失敗 → 自動修正ループ or エスカレーション"""

    # 現在の試行回数を取得
    from supabase_client import SUPABASE_URL, SUPA_HEADERS
    import httpx
    async with httpx.AsyncClient() as c:
        r = await c.get(
            f"{SUPABASE_URL}/executions?task_id=eq.{task_id}&select=attempt&order=attempt.desc&limit=1",
            headers=SUPA_HEADERS,
        )
        execs = r.json()

    current_attempt = execs[0]["attempt"] if execs else 0
    next_attempt = current_attempt + 1

    # 即時エスカレーション判定
    if _is_escalation_error(error_log):
        return await _escalate(task, task_id, branch_name, error_log, reason="重篤なエラー")

    # 修正上限チェック
    if next_attempt > MAX_FIX_ATTEMPTS:
        return await _escalate(task, task_id, branch_name, error_log, reason="修正上限超過")

    # 自動修正ループ
    await notify(
        "test_failed",
        task_title=task["title"],
        branch=branch_name,
        attempt=next_attempt,
        max_attempts=MAX_FIX_ATTEMPTS,
        error_summary=error_log[:200],
    )

    # ブランチのコードを取得して修正
    file_contents = await _get_branch_file_contents(branch_name)
    fixed_files, fix_summary = await analyze_test_error(error_log, task, file_contents)

    if not fixed_files:
        if next_attempt >= MAX_FIX_ATTEMPTS:
            return await _escalate(task, task_id, branch_name, error_log, reason="修正案生成失敗")
        await insert_execution(task_id, attempt=next_attempt, result="fix_failed", error_log=error_log)
        return {"status": "fix_failed", "attempt": next_attempt}

    # 修正コードをPush
    for f in fixed_files:
        await push_file(
            path=f["path"],
            content=f["content"],
            branch=branch_name,
            message=f"fix: {task['title']} attempt#{next_attempt} - {f['path']}",
        )

    await insert_execution(task_id, attempt=next_attempt, result="fix_pushed",
                           error_log=f"summary={fix_summary}")
    # GitHub Actionsが再実行される（push triggerにより）
    return {
        "status": "fix_pushed",
        "attempt": next_attempt,
        "branch": branch_name,
        "fixed_files": [f["path"] for f in fixed_files],
    }


async def _escalate(task: dict, task_id: str, branch_name: str,
                    error_log: str, reason: str) -> dict:
    """エスカレーション（壮輝に通知して手動確認を依頼）"""
    await update_task(task_id, status="escalated")
    await insert_execution(task_id, attempt=99, result="escalated", error_log=error_log[:2000])
    await notify(
        "escalation",
        task_title=task["title"],
        branch=branch_name,
        max_attempts=MAX_FIX_ATTEMPTS,
        error_log=error_log[:500],
    )
    return {"status": "escalated", "reason": reason, "branch": branch_name}


def _extract_error_summary(jobs_data: dict) -> str:
    """GitHub Actions jobs レスポンスからエラー概要を抽出"""
    jobs = jobs_data.get("jobs", [])
    failed_steps = []
    for job in jobs:
        if job.get("conclusion") == "failure":
            for step in job.get("steps", []):
                if step.get("conclusion") == "failure":
                    failed_steps.append(f"{job['name']} > {step['name']}")
    return "Failed: " + ", ".join(failed_steps) if failed_steps else "Unknown error"
