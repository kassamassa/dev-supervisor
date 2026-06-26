"""
Dify ②タスク実行ワークフロー バグ修正スクリプト

問題: ブランチ作成ノードのBody templateが間違っており
  - ref: "refs/heads/task/{task_id}" (UUIDをブランチ名に使用・余分な{}付き)
  - sha: "sha_value}" (末尾に余分な"}"付き)

修正方針:
  Dify コンソールAPIでワークフローを更新するか
  Python側でブランチ作成を代替実行する

このスクリプトは「Pythonブリッジ」として動作する:
  1. Dify workflow を streaming で実行
  2. file_selection LLM出力をキャプチャ
  3. ブランチ作成は Python から正しく実行
  4. Dify の コード生成LLM に必要な情報を整形して再実行
  5. 生成コードを GitHub Push
  6. Supabase 更新
"""

import httpx
import json
import re
import base64
import os
import sys

DIFY_API_KEY = os.getenv("DIFY_TASK_EXEC_KEY", "")
DIFY_BASE = "https://api.dify.ai/v1"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_OWNER = "kassamassa"
GITHUB_REPO = "Develop"
SUPABASE_URL = "https://thfthbblfsjhyqcinyms.supabase.co/rest/v1"
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

supa_headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}
gh_headers = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\s_]+", "-", text.strip())
    return text[:40].strip("-")


def step(msg: str) -> None:
    print(f"  [OK] {msg}")


def fail(msg: str) -> None:
    print(f"  [NG] {msg}")


def run_workflow_streaming(task_id: str, project_id: str) -> dict:
    """
    Dify ワークフローをストリーミングで実行し、
    ブランチ作成まで到達した時点での中間データを取得する
    """
    print("[Phase 1] Dify ワークフロー実行（ファイル選定まで）")

    captured = {
        "required_files": [],
        "task_data": None,
        "file_map": {},
        "main_sha": None,
    }

    payload = {
        "inputs": {"task_id": task_id, "project_id": project_id},
        "response_mode": "streaming",
        "user": "dev-supervisor",
    }

    with httpx.Client(timeout=60) as client:
        with client.stream(
            "POST",
            f"{DIFY_BASE}/workflows/run",
            json=payload,
            headers={
                "Authorization": f"Bearer {DIFY_API_KEY}",
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

                data = event.get("data", {})
                node_title = data.get("title", "")
                node_status = data.get("status")
                outputs = data.get("outputs", {})
                event_type = event.get("event")

                if event_type == "node_finished" and node_status == "succeeded":
                    if node_title == "タスク仕様取得":
                        body = outputs.get("body", "[]")
                        tasks = json.loads(body)
                        if tasks:
                            captured["task_data"] = tasks[0]
                            step(f"タスク取得: {tasks[0]['title']}")

                    elif node_title == "ファイルマップ取得":
                        body = outputs.get("body", "[]")
                        projects = json.loads(body)
                        if projects:
                            captured["file_map"] = projects[0].get("file_map") or {}
                        step(f"ファイルマップ取得: {len(captured['file_map'])}件")

                    elif node_title == "必要ファイル選定":
                        text = outputs.get("text", "[]")
                        text = re.sub(r"```(?:json)?\n?", "", text).strip().rstrip("`").strip()
                        match = re.search(r"\{.*?\"required_files\".*?\}", text, re.DOTALL)
                        if match:
                            parsed = json.loads(match.group())
                            captured["required_files"] = parsed.get("required_files", [])
                        step(f"必要ファイル選定: {captured['required_files']}")

                    elif "SHA" in node_title or "sha" in node_title.lower():
                        sha = outputs.get("sha") or outputs.get("body", "")
                        if sha and len(sha) == 40:
                            captured["main_sha"] = sha
                            step(f"SHA取得: {sha[:8]}...")

                elif event_type in ("workflow_finished",):
                    status = data.get("status")
                    if status == "failed":
                        print(f"  ⚠️  ワークフローが失敗しましたが中間データを使用します")
                    break

    return captured


def get_github_file_content(path: str, branch: str = "main") -> str | None:
    r = httpx.get(
        f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}",
        params={"ref": branch},
        headers=gh_headers,
    )
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return base64.b64decode(r.json()["content"]).decode("utf-8")


def create_branch(branch_name: str, sha: str) -> bool:
    r = httpx.post(
        f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/git/refs",
        json={"ref": f"refs/heads/{branch_name}", "sha": sha},
        headers=gh_headers,
    )
    if r.status_code == 422:
        # branch already exists - OK
        return True
    if r.status_code == 201:
        return True
    print(f"    Branch creation error: {r.status_code} {r.text}")
    return False


def push_file_to_github(path: str, content: str, branch: str, commit_msg: str) -> bool:
    b64 = base64.b64encode(content.encode("utf-8")).decode("utf-8")
    # get existing sha if file exists
    sha = None
    r = httpx.get(
        f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}",
        params={"ref": branch},
        headers=gh_headers,
    )
    if r.status_code == 200:
        sha = r.json()["sha"]

    payload = {"message": commit_msg, "content": b64, "branch": branch}
    if sha:
        payload["sha"] = sha

    r = httpx.put(
        f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}",
        json=payload,
        headers=gh_headers,
    )
    if r.status_code in (200, 201):
        return True
    print(f"    Push error: {r.status_code} {r.text[:200]}")
    return False


def generate_code_via_dify(task: dict, file_contents: dict) -> list[dict]:
    """
    Dify ワークフローの コード生成 LLM をシミュレートするため
    実際にはAnthropicを直接呼ぶかDifyのLLMを活用する

    現状: Anthropic APIキーが未設定のため
    タスク情報から構造化されたスケルトンコードを生成する
    """
    task_title = task.get("title", "")
    task_desc = task.get("description", "")
    priority = task.get("priority", 1)

    # スケルトンコードを生成（LLMの代替）
    # ユーザーがAnthropicキーを設定すれば自動的にLLMが使われる
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    if anthropic_key and len(anthropic_key) > 30:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=anthropic_key)
            context = "\n".join(f"=== {p} ===\n{c}" for p, c in file_contents.items()) if file_contents else "（既存ファイルなし）"
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=8192,
                system="あなたはシニアソフトウェアエンジニアです。JSONのみを返してください。",
                messages=[{"role": "user", "content": f"""
タスク: {task_title}
説明: {task_desc}

既存ファイル:
{context}

以下のJSON形式のみで回答（マークダウン不要）:
{{"files": [{{"path": "パス", "content": "内容", "description": "説明"}}], "summary": "要約"}}
"""}],
            )
            text = response.content[0].text
            text = re.sub(r"```(?:json)?\n?", "", text).strip().rstrip("`").strip()
            data = json.loads(text)
            return data.get("files", [])
        except Exception as e:
            print(f"    LLM error: {e}")

    # フォールバック: スケルトン生成
    print("  ⚠️  ANTHROPIC_API_KEY未設定 - スケルトンコードを生成します")
    # タスクタイトルからファイルパスを推定
    slug = slugify(task_title)
    return [
        {
            "path": f"tasks/task_{priority:03d}_{slug}/implementation.md",
            "content": f"""# {task_title}

## 概要
{task_desc}

## 実装手順
1. TODO: 実装内容を記載
2. TODO: テスト方法を記載

## 備考
- priority: {priority}
- status: in_progress
""",
            "description": f"タスク{priority:03d}の実装仕様",
        }
    ]


def update_supabase(task_id: str, project_id: str, branch_name: str, new_files: list[dict]) -> None:
    # タスクのbranch_nameとstatusを更新
    r = httpx.patch(
        f"{SUPABASE_URL}/tasks?id=eq.{task_id}",
        json={"branch_name": branch_name, "status": "in_progress"},
        headers=supa_headers,
    )
    if r.status_code not in (200, 201, 204):
        print(f"    Supabase task update error: {r.status_code} {r.text}")
        return
    step(f"タスクステータス更新 → in_progress, branch: {branch_name}")

    # file_mapを更新（projectsテーブル）
    # 既存のfile_mapを取得
    r = httpx.get(
        f"{SUPABASE_URL}/projects?id=eq.{project_id}&select=id,file_map",
        headers=supa_headers,
    )
    rows = r.json()
    existing_map = rows[0].get("file_map") or {} if rows else {}
    for f in new_files:
        existing_map[f["path"]] = f.get("description", "")

    if rows:
        r = httpx.patch(
            f"{SUPABASE_URL}/projects?id=eq.{project_id}",
            json={"file_map": existing_map},
            headers=supa_headers,
        )
    else:
        r = httpx.post(
            f"{SUPABASE_URL}/projects",
            json={"id": project_id, "file_map": existing_map, "status": "active"},
            headers=supa_headers,
        )

    if r.status_code not in (200, 201, 204):
        print(f"    Supabase project update error: {r.status_code} {r.text}")
    else:
        step(f"ファイルマップ更新: {len(existing_map)}件")


def run(task_id: str, project_id: str) -> dict:
    print("=" * 60)
    print("[2] Task Execution Workflow (Python Bridge)")
    print(f"  task_id:    {task_id}")
    print(f"  project_id: {project_id}")
    print("=" * 60)

    # Phase 1: Dify でファイル選定（LLM）
    captured = run_workflow_streaming(task_id, project_id)

    task = captured.get("task_data")
    if not task:
        # fallback: Supabase から直接取得
        r = httpx.get(
            f"{SUPABASE_URL}/tasks?id=eq.{task_id}&select=*",
            headers=supa_headers,
        )
        rows = r.json()
        task = rows[0] if rows else {}

    if not task:
        raise ValueError(f"Task {task_id} not found")

    main_sha = captured.get("main_sha")
    if not main_sha:
        r = httpx.get(
            "https://api.github.com/repos/kassamassa/Develop/git/refs/heads/main",
            headers=gh_headers,
        )
        main_sha = r.json()["object"]["sha"]
        step(f"SHA取得 (fallback): {main_sha[:8]}...")

    print()
    print("[Phase 2] ブランチ作成 (Python)")
    priority = task.get("priority") or 0
    branch_name = f"task/{priority:03d}-{slugify(task['title'])}"
    ok = create_branch(branch_name, main_sha)
    if ok:
        step(f"ブランチ作成: {branch_name}")
    else:
        fail("ブランチ作成失敗")
        return {"status": "failed", "error": "branch creation failed"}

    print()
    print("[Phase 3] ファイル取得")
    required_files = captured.get("required_files", [])
    file_contents = {}
    for path in required_files:
        content = get_github_file_content(path)
        if content:
            file_contents[path] = content
    step(f"ファイル取得: {len(file_contents)}件")

    print()
    print("[Phase 4] コード生成")
    generated_files = generate_code_via_dify(task, file_contents)
    step(f"コード生成: {len(generated_files)}ファイル")

    print()
    print("[Phase 5] GitHub Push")
    for f in generated_files:
        ok = push_file_to_github(
            path=f["path"],
            content=f["content"],
            branch=branch_name,
            commit_msg=f"feat: {task['title']} - {f['path']}",
        )
        if ok:
            step(f"Push: {f['path']}")
        else:
            fail(f"Push失敗: {f['path']}")

    print()
    print("[Phase 6] Supabase 更新")
    update_supabase(task_id, project_id, branch_name, generated_files)

    result = {
        "status": "success",
        "task_id": task_id,
        "task_title": task["title"],
        "branch": branch_name,
        "files_generated": [f["path"] for f in generated_files],
    }

    print()
    print("=" * 60)
    print("[DONE]")
    print(f"   Branch: {branch_name}")
    print(f"   Files generated: {len(generated_files)}")
    print(f"   GitHub: https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/tree/{branch_name}")
    print("=" * 60)

    return result


if __name__ == "__main__":
    TASK_ID = sys.argv[1] if len(sys.argv) > 1 else "04169c2f-0f88-4d76-b258-ae6af61b03b4"
    PROJECT_ID = sys.argv[2] if len(sys.argv) > 2 else "789de90d-7d02-4e0c-8ff7-b8d17f3cb9dc"
    result = run(TASK_ID, PROJECT_ID)
    print(json.dumps(result, ensure_ascii=False, indent=2))
