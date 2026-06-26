"""全ワークフロー動作確認スクリプト"""
import asyncio
import json
import sys

sys.path.insert(0, ".")


async def test_chain():
    from supabase_client import get_pending_tasks
    from workflow_01_chain import trigger_single_task

    tasks = await get_pending_tasks("789de90d-7d02-4e0c-8ff7-b8d17f3cb9dc")
    print(f"Pending tasks: {len(tasks)}")
    for t in tasks[:5]:
        print(f"  [{t.get('priority','?')}] {t['title']}")

    if not tasks:
        print("No pending tasks")
        return

    # priority最小のタスクを1件実行
    target = tasks[0]
    print(f"\n[①→②] {target['title']}")
    result = await trigger_single_task(target["id"], "789de90d-7d02-4e0c-8ff7-b8d17f3cb9dc")
    print(json.dumps({k: result[k] for k in ["status", "task_title", "branch"] if k in result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(test_chain())
