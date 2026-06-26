"""
②タスク実行ワークフロー
- Supabaseからタスク仕様・ファイルマップ取得
- Claude APIで必要ファイル選定・コード生成
- GitHub APIでブランチ作成・コードPush
- Supabaseのfile_map・task.branch_name更新
"""
import os
import re
import json
import base64
import httpx
import anthropic
from typing import Optional

SUPABASE_URL = "https://thfthbblfsjhyqcinyms.supabase.co/rest/v1"
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_OWNER = "kassamassa"
GITHUB_REPO = "Develop"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

supabase_headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}

github_headers = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\s_]+", "-", text.strip())
    return text[:40].strip("-")


async def get_task(task_id: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{SUPABASE_URL}/tasks",
            params={"id": f"eq.{task_id}", "select": "*"},
            headers=supabase_headers,
        )
        r.raise_for_status()
        rows = r.json()
        if not rows:
            raise ValueError(f"Task {task_id} not found")
        return rows[0]


async def get_project(project_id: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{SUPABASE_URL}/projects",
            params={"id": f"eq.{project_id}", "select": "*"},
            headers=supabase_headers,
        )
        r.raise_for_status()
        rows = r.json()
        if not rows:
            return {"id": project_id, "file_map": {}, "repo_url": f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"}
        return rows[0]


async def get_main_sha() -> str:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/git/refs/heads/main",
            headers=github_headers,
        )
        r.raise_for_status()
        return r.json()["object"]["sha"]


async def create_branch(branch_name: str, sha: str) -> None:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/git/refs",
            json={"ref": f"refs/heads/{branch_name}", "sha": sha},
            headers=github_headers,
        )
        if r.status_code == 422:
            # branch already exists
            return
        r.raise_for_status()


async def get_github_file(path: str, branch: str = "main") -> Optional[str]:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}",
            params={"ref": branch},
            headers=github_headers,
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        data = r.json()
        return base64.b64decode(data["content"]).decode("utf-8")


async def push_file(path: str, content: str, branch: str, message: str) -> None:
    b64 = base64.b64encode(content.encode("utf-8")).decode("utf-8")
    # check if file exists (to get sha for update)
    sha = None
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}",
            params={"ref": branch},
            headers=github_headers,
        )
        if r.status_code == 200:
            sha = r.json()["sha"]

        payload = {
            "message": message,
            "content": b64,
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha

        r = await client.put(
            f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}",
            json=payload,
            headers=github_headers,
        )
        r.raise_for_status()


async def select_required_files(task: dict, file_map: dict) -> list[str]:
    """Claudeにタスクに必要なファイルを選ばせる"""
    if not file_map:
        return []

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    file_list = "\n".join(f"- {path}: {desc}" for path, desc in file_map.items())
    prompt = f"""以下のタスクを実装するために必要なファイルを選んでください。

【タスク】
タイトル: {task['title']}
説明: {task.get('description', '')}

【存在するファイル一覧】
{file_list}

必要なファイルのパスのみをJSON配列で返してください。例: ["src/main.py", "src/utils.py"]
不要なファイルは含めないでください。ファイルが不要な場合は空配列 [] を返してください。"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system="あなたはソフトウェア開発の専門家です。タスクに必要なファイルを選定してください。",
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text
    match = re.search(r"\[.*?\]", text, re.DOTALL)
    if match:
        return json.loads(match.group())
    return []


async def generate_code(task: dict, file_contents: dict) -> list[dict]:
    """Claudeにコードを生成させる。戻り値: [{path, content, description}]"""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    context_parts = []
    for path, content in file_contents.items():
        context_parts.append(f"=== {path} ===\n{content}\n")
    context = "\n".join(context_parts) if context_parts else "（既存ファイルなし）"

    prompt = f"""以下のタスクを実装してください。

【タスク】
タイトル: {task['title']}
説明: {task.get('description', 'なし')}
優先度: {task.get('priority', '未設定')}

【既存ファイル】
{context}

以下のJSON形式で回答してください:
{{
  "files": [
    {{
      "path": "ファイルパス（例: src/auth/register.py）",
      "content": "ファイルの完全な内容",
      "description": "このファイルの役割の一行説明"
    }}
  ],
  "summary": "実装内容の要約"
}}

JSONのみを出力してください。マークダウンのコードブロックは使わないでください。"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        system="あなたはシニアソフトウェアエンジニアです。高品質なコードを生成してください。",
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text

    # Markdownコードブロック除去
    text = re.sub(r"```(?:json)?\n?", "", text).strip()
    text = re.sub(r"```\s*$", "", text).strip()

    try:
        data = json.loads(text)
        return data.get("files", []), data.get("summary", "")
    except json.JSONDecodeError:
        # フォールバック: 内容をそのままREADMEに保存
        return [{"path": "TASK_OUTPUT.md", "content": text, "description": "タスク実行結果"}], ""


async def update_task(task_id: str, branch_name: str, status: str = "in_progress") -> None:
    async with httpx.AsyncClient() as client:
        r = await client.patch(
            f"{SUPABASE_URL}/tasks",
            params={"id": f"eq.{task_id}"},
            json={"branch_name": branch_name, "status": status},
            headers=supabase_headers,
        )
        r.raise_for_status()


async def update_project_file_map(project_id: str, new_files: list[dict]) -> None:
    async with httpx.AsyncClient() as client:
        # 現在のfile_mapを取得
        r = await client.get(
            f"{SUPABASE_URL}/projects",
            params={"id": f"eq.{project_id}", "select": "file_map"},
            headers=supabase_headers,
        )
        r.raise_for_status()
        rows = r.json()
        current_map = rows[0].get("file_map") or {} if rows else {}

        for f in new_files:
            current_map[f["path"]] = f.get("description", "")

        if rows:
            r = await client.patch(
                f"{SUPABASE_URL}/projects",
                params={"id": f"eq.{project_id}"},
                json={"file_map": current_map},
                headers=supabase_headers,
            )
        else:
            r = await client.post(
                f"{SUPABASE_URL}/projects",
                json={"id": project_id, "file_map": current_map, "status": "active"},
                headers=supabase_headers,
            )
        r.raise_for_status()


async def run_task_execution(task_id: str, project_id: str) -> dict:
    """メインワークフロー実行"""
    print(f"[②ワークフロー開始] task_id={task_id}, project_id={project_id}")

    # 1. タスク仕様取得
    task = await get_task(task_id)
    print(f"  ✅ タスク取得: {task['title']}")

    # 2. ファイルマップ取得
    project = await get_project(project_id)
    file_map = project.get("file_map") or {}
    print(f"  ✅ ファイルマップ取得: {len(file_map)}件")

    # 3. 必要ファイル選定
    selected_paths = await select_required_files(task, file_map)
    print(f"  ✅ 必要ファイル選定: {selected_paths}")

    # 4. ファイル取得
    file_contents = {}
    for path in selected_paths:
        content = await get_github_file(path)
        if content:
            file_contents[path] = content
    print(f"  ✅ ファイル取得: {len(file_contents)}件")

    # 5. ブランチ作成
    priority_str = str(task.get("priority") or "000").zfill(3)
    branch_name = f"task/{priority_str}-{slugify(task['title'])}"
    main_sha = await get_main_sha()
    await create_branch(branch_name, main_sha)
    print(f"  ✅ ブランチ作成: {branch_name}")

    # 6. コード生成
    generated_files, summary = await generate_code(task, file_contents)
    print(f"  ✅ コード生成: {len(generated_files)}ファイル")

    # 7. GitHub Push
    for f in generated_files:
        await push_file(
            path=f["path"],
            content=f["content"],
            branch=branch_name,
            message=f"feat: {task['title']} - {f['path']}",
        )
        print(f"  ✅ Push: {f['path']}")

    # 8. ファイルマップ更新
    await update_project_file_map(project_id, generated_files)
    print(f"  ✅ ファイルマップ更新")

    # 9. タスクのbranch_nameとstatusを更新
    await update_task(task_id, branch_name, status="in_progress")
    print(f"  ✅ タスクステータス更新 → in_progress")

    return {
        "status": "success",
        "task_id": task_id,
        "task_title": task["title"],
        "branch": branch_name,
        "files_generated": [f["path"] for f in generated_files],
        "summary": summary,
    }
