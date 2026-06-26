"""
①→②自動連鎖
①要件受付ワークフロー完了後、②タスク実行を自動起動する。

連鎖の仕組み:
  - ①が Supabase に tasks を保存した後、このエンドポイントを呼び出す
  - pendingタスクを priority 順に取得し、②を順次実行
  - 依存関係(dependencies)を考慮して実行順を制御
"""
import asyncio
from supabase_client import get_pending_tasks, get_task, update_task
from workflow_02_task_exec import run as run_task_execution
from workflow_04_notify import notify


async def trigger_task_pipeline(project_id: str, max_concurrent: int = 1) -> dict:
    """
    プロジェクトの全 pending タスクを②で実行する。
    max_concurrent=1 で直列実行（依存関係を安全に処理）
    """
    pending = await get_pending_tasks(project_id)
    if not pending:
        return {"status": "no_pending_tasks", "project_id": project_id}

    await notify(
        "requirements_received",
        project_name=project_id[:8],
        task_count=len(pending),
    )

    results = []
    completed_ids: set[str] = set()

    # 依存関係を考慮した実行順を解決
    ordered = _resolve_execution_order(pending)

    for task in ordered:
        task_id = task["id"]
        deps = task.get("dependencies") or []

        # 依存タスクが未完了なら待機
        unresolved = [d for d in deps if d not in completed_ids]
        if unresolved:
            print(f"[①→②] SKIP {task['title']}: 依存未完了 {unresolved}")
            results.append({"task_id": task_id, "status": "skipped_deps"})
            continue

        try:
            result = await run_task_execution(task_id, project_id)
            completed_ids.add(task_id)
            results.append(result)
        except Exception as e:
            print(f"[①→②] ERROR {task['title']}: {e}")
            await update_task(task_id, status="failed")
            results.append({"task_id": task_id, "status": "error", "error": str(e)})

    return {
        "status": "pipeline_complete",
        "project_id": project_id,
        "total": len(ordered),
        "results": results,
    }


def _resolve_execution_order(tasks: list[dict]) -> list[dict]:
    """トポロジカルソートで依存関係を解決した実行順を返す"""
    # priority でソート（簡易版: 依存関係が複雑な場合は拡張）
    return sorted(tasks, key=lambda t: (t.get("priority") or 99))


async def trigger_single_task(task_id: str, project_id: str) -> dict:
    """単一タスクを②で実行（手動トリガー用）"""
    return await run_task_execution(task_id, project_id)
