"""
②タスク実行ワークフロー 動作確認スクリプト
Difyワークフローを直接APIで実行してテストする
"""
import httpx
import json
import sys

DIFY_API_KEY = "app-1lAkYPmfjz18MgOke1pjpVRv"
DIFY_BASE = "https://api.dify.ai/v1"

# テスト用タスク・プロジェクトID (Supabaseの実データ)
TEST_TASK_ID = "04169c2f-0f88-4d76-b258-ae6af61b03b4"   # 要件定義・技術スタック選定
TEST_PROJECT_ID = "789de90d-7d02-4e0c-8ff7-b8d17f3cb9dc"


def run_workflow(task_id: str, project_id: str):
    print(f"[Dify ②ワークフロー実行]")
    print(f"  task_id:    {task_id}")
    print(f"  project_id: {project_id}")
    print()

    payload = {
        "inputs": {
            "task_id": task_id,
            "project_id": project_id,
        },
        "response_mode": "blocking",
        "user": "dev-supervisor-test",
    }

    r = httpx.post(
        f"{DIFY_BASE}/workflows/run",
        json=payload,
        headers={
            "Authorization": f"Bearer {DIFY_API_KEY}",
            "Content-Type": "application/json",
        },
        timeout=300,  # コード生成は時間がかかる
    )

    print(f"HTTP Status: {r.status_code}")
    data = r.json()
    print(json.dumps(data, indent=2, ensure_ascii=False))

    if r.status_code == 200:
        status = data.get("data", {}).get("status")
        outputs = data.get("data", {}).get("outputs", {})
        print()
        print("=" * 60)
        if status == "succeeded":
            print("✅ ワークフロー成功!")
            print(f"  ブランチ: {outputs.get('branch_name')}")
            print(f"  タスク:   {outputs.get('task_title')}")
            print(f"  概要:     {outputs.get('summary')}")
        else:
            print(f"❌ ステータス: {status}")
            error = data.get("data", {}).get("error")
            if error:
                print(f"エラー: {error}")
    return data


def check_supabase_result(task_id: str):
    """ワークフロー実行後のSupabaseデータを確認"""
    SUPABASE_URL = "https://thfthbblfsjhyqcinyms.supabase.co/rest/v1"
    SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRoZnRoYmJsZnNqaHlxY2lueW1zIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODIzMTc1NzAsImV4cCI6MjA5Nzg5MzU3MH0.OTPCMrfgHFDNOvAfw19TKx4ejJudU5zHYDPjEUD5wFs"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }
    r = httpx.get(
        f"{SUPABASE_URL}/tasks?id=eq.{task_id}&select=id,title,status,branch_name",
        headers=headers,
    )
    rows = r.json()
    if rows:
        task = rows[0]
        print(f"\n[Supabase 確認]")
        print(f"  title:       {task['title']}")
        print(f"  status:      {task['status']}")
        print(f"  branch_name: {task['branch_name']}")
    return rows


if __name__ == "__main__":
    task_id = sys.argv[1] if len(sys.argv) > 1 else TEST_TASK_ID
    project_id = sys.argv[2] if len(sys.argv) > 2 else TEST_PROJECT_ID

    result = run_workflow(task_id, project_id)

    # 実行成功した場合はSupabaseも確認
    if result.get("data", {}).get("status") == "succeeded":
        check_supabase_result(task_id)
