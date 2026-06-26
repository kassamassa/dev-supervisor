"""LLM呼び出し — Dify専用コード生成WF → Difyフルキャプチャ → Anthropic → スケルトン"""
import re
import json
import httpx
from config import ANTHROPIC_KEY, DIFY_BASE, DIFY_TASK_EXEC_KEY, DIFY_CODEGEN_KEY


def _slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\s_]+", "-", text.strip())
    return text[:40].strip("-")


def _parse_json_from_text(text: str) -> dict | None:
    text = re.sub(r"```(?:json)?\n?", "", text).strip().rstrip("`").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return None


def _call_dify_codegen(task: dict, file_map: dict) -> tuple[list[dict], str] | None:
    """
    コード生成専用Dify workflow (dify_codegen_only.yml) を呼び出す。
    DIFY_CODEGEN_KEY が設定されている場合のみ使用。
    """
    if not DIFY_CODEGEN_KEY or len(DIFY_CODEGEN_KEY) < 10:
        return None

    file_map_text = "\n".join(f"- {p}: {d}" for p, d in file_map.items()) if file_map else "(ファイルなし)"
    try:
        payload = {
            "inputs": {
                "task_title": task.get("title", ""),
                "task_description": task.get("description", ""),
                "task_priority": str(task.get("priority") or "1"),
                "file_map_text": file_map_text,
            },
            "response_mode": "blocking",
            "user": "dev-supervisor",
        }
        with httpx.Client(timeout=120) as client:
            resp = client.post(
                f"{DIFY_BASE}/workflows/run",
                json=payload,
                headers={
                    "Authorization": f"Bearer {DIFY_CODEGEN_KEY}",
                    "Content-Type": "application/json",
                },
            )
        if resp.status_code != 200:
            return None
        data = resp.json()
        if data.get("data", {}).get("status") != "succeeded":
            return None
        generated_code = data["data"].get("outputs", {}).get("generated_code", "")
        if not generated_code:
            return None
        parsed = _parse_json_from_text(generated_code)
        if parsed:
            return parsed.get("files", []), parsed.get("summary", "Dify codegen")
    except Exception as e:
        print(f"[llm_client] DIFY_CODEGEN error: {e}")
    return None


def _call_dify_codegen_streaming(task: dict, file_map: dict) -> tuple[list[dict], str] | None:
    """
    コード生成専用Dify workflow をストリーミングで呼び出して コード生成ノード出力をキャプチャ。
    """
    if not DIFY_CODEGEN_KEY or len(DIFY_CODEGEN_KEY) < 10:
        return None

    file_map_text = "\n".join(f"- {p}: {d}" for p, d in file_map.items()) if file_map else "(ファイルなし)"
    try:
        payload = {
            "inputs": {
                "task_title": task.get("title", ""),
                "task_description": task.get("description", ""),
                "task_priority": str(task.get("priority") or "1"),
                "file_map_text": file_map_text,
            },
            "response_mode": "streaming",
            "user": "dev-supervisor",
        }
        with httpx.Client(timeout=120) as client:
            with client.stream(
                "POST", f"{DIFY_BASE}/workflows/run",
                json=payload,
                headers={
                    "Authorization": f"Bearer {DIFY_CODEGEN_KEY}",
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
                    if data.get("title") == "コード生成":
                        text = data.get("outputs", {}).get("text", "")
                        parsed = _parse_json_from_text(text)
                        if parsed:
                            return parsed.get("files", []), parsed.get("summary", "Dify LLM生成")
    except Exception as e:
        print(f"[llm_client] DIFY_CODEGEN streaming error: {e}")
    return None


async def select_required_files(task: dict, file_map: dict) -> list[str]:
    """タスクに必要なファイルをLLMで選定（Anthropic → 空リスト）"""
    if not file_map:
        return []

    if ANTHROPIC_KEY and len(ANTHROPIC_KEY) > 30:
        file_list = "\n".join(f"- {p}: {d}" for p, d in file_map.items())
        prompt = (
            f"タスク: {task.get('title', '')}\n"
            f"説明: {task.get('description', '')}\n\n"
            f"ファイル一覧:\n{file_list}\n\n"
            "必要なファイルのパスのみJSON配列で返してください。例: [\"src/main.py\"]\n"
            "不要な場合は []"
        )
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
            resp = client.messages.create(
                model="claude-sonnet-4-6", max_tokens=512,
                system="ファイル選定の専門家。JSON配列のみ返す。",
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text
            text = re.sub(r"```(?:json)?\n?", "", text).strip().rstrip("`")
            m = re.search(r"\[.*?\]", text, re.DOTALL)
            if m:
                return json.loads(m.group())
        except Exception:
            pass

    return []


async def generate_code(task: dict, file_contents: dict) -> tuple[list[dict], str]:
    """
    コード生成の優先順位:
    1. Dify コード生成専用WF (DIFY_CODEGEN_KEY が設定されている場合)
    2. Anthropic 直接呼び出し (ANTHROPIC_API_KEY が設定されている場合)
    3. スケルトン（最終手段）
    """
    file_map = {p: "" for p in file_contents.keys()}

    # 1. Dify コード生成専用ワークフロー (blocking)
    result = _call_dify_codegen(task, file_map)
    if result:
        files, summary = result
        if files:
            print(f"[llm_client] Dify codegen WF: {len(files)}ファイル生成")
            return files, summary

    # 1b. Dify コード生成専用ワークフロー (streaming capture)
    result = _call_dify_codegen_streaming(task, file_map)
    if result:
        files, summary = result
        if files:
            print(f"[llm_client] Dify codegen streaming: {len(files)}ファイル生成")
            return files, summary

    # 2. Anthropic 直接呼び出し
    if ANTHROPIC_KEY and len(ANTHROPIC_KEY) > 30:
        context = "\n".join(f"=== {p} ===\n{c}" for p, c in file_contents.items()) or "(既存ファイルなし)"
        prompt = (
            f"タスク: {task.get('title', '')}\n"
            f"説明: {task.get('description', '')}\n"
            f"優先度: {task.get('priority', 1)}\n\n"
            f"既存ファイル:\n{context}\n\n"
            '以下のJSON形式のみで回答（マークダウン不使用）:\n'
            '{"files":[{"path":"パス","content":"内容","description":"説明"}],"summary":"要約"}'
        )
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
            resp = client.messages.create(
                model="claude-sonnet-4-6", max_tokens=8192,
                system="シニアソフトウェアエンジニア。JSONのみ返す。",
                messages=[{"role": "user", "content": prompt}],
            )
            data = _parse_json_from_text(resp.content[0].text)
            if data:
                files = data.get("files", [])
                if files:
                    print(f"[llm_client] Anthropic: {len(files)}ファイル生成")
                    return files, data.get("summary", "")
        except Exception as e:
            print(f"[llm_client] Anthropic error: {e}")

    # 3. スケルトン（最終手段）
    print("[llm_client] スケルトンフォールバック")
    priority = task.get("priority") or 1
    slug = _slugify(task.get("title", "task"))
    skeleton_path = f"tasks/task_{priority:03d}_{slug}/spec.md"
    content = (
        f"# {task.get('title', '')}\n\n"
        f"## 説明\n{task.get('description', '')}\n\n"
        f"## 優先度\n{priority}\n\n"
        f"## ステータス\nin_progress\n\n"
        f"## TODO\n- [ ] 実装\n- [ ] テスト\n"
    )
    return [{"path": skeleton_path, "content": content, "description": "タスク仕様書（スケルトン）"}], "スケルトン生成"


async def analyze_test_error(error_log: str, task: dict, file_contents: dict) -> tuple[list[dict], str]:
    """テストエラーを解析してコード修正案を生成（Anthropic → 空）"""
    if ANTHROPIC_KEY and len(ANTHROPIC_KEY) > 30:
        context = "\n".join(f"=== {p} ===\n{c}" for p, c in file_contents.items()) or "(ファイルなし)"
        prompt = (
            f"テストが失敗しました。エラーを修正してください。\n\n"
            f"タスク: {task.get('title', '')}\n"
            f"エラーログ:\n{error_log}\n\n"
            f"既存コード:\n{context}\n\n"
            '修正後のファイルをJSON形式のみで返してください:\n'
            '{"files":[{"path":"パス","content":"修正内容","description":"説明"}],"summary":"修正内容"}'
        )
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
            resp = client.messages.create(
                model="claude-sonnet-4-6", max_tokens=8192,
                system="バグ修正の専門家。JSONのみ返す。",
                messages=[{"role": "user", "content": prompt}],
            )
            data = _parse_json_from_text(resp.content[0].text)
            if data:
                return data.get("files", []), data.get("summary", "")
        except Exception:
            pass

    return [], f"エラー解析: {error_log[:200]}"
