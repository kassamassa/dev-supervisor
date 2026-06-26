"""GitHub API ヘルパー"""
import base64
import httpx
from config import GITHUB_OWNER, GITHUB_REPO, GH_HEADERS

BASE = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"


async def get_main_sha() -> str:
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{BASE}/git/refs/heads/main", headers=GH_HEADERS)
        r.raise_for_status()
        return r.json()["object"]["sha"]


async def create_branch(branch_name: str, sha: str) -> None:
    async with httpx.AsyncClient() as c:
        r = await c.post(
            f"{BASE}/git/refs",
            json={"ref": f"refs/heads/{branch_name}", "sha": sha},
            headers=GH_HEADERS,
        )
        if r.status_code == 422:
            return  # already exists
        r.raise_for_status()


async def get_file(path: str, branch: str = "main") -> str | None:
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{BASE}/contents/{path}", params={"ref": branch}, headers=GH_HEADERS)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return base64.b64decode(r.json()["content"]).decode("utf-8")


async def push_file(path: str, content: str, branch: str, message: str) -> None:
    b64 = base64.b64encode(content.encode()).decode()
    sha = None
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{BASE}/contents/{path}", params={"ref": branch}, headers=GH_HEADERS)
        if r.status_code == 200:
            sha = r.json()["sha"]
        payload = {"message": message, "content": b64, "branch": branch}
        if sha:
            payload["sha"] = sha
        r = await c.put(f"{BASE}/contents/{path}", json=payload, headers=GH_HEADERS)
        r.raise_for_status()


async def create_pull_request(title: str, branch: str, body: str = "") -> dict:
    async with httpx.AsyncClient() as c:
        r = await c.post(
            f"{BASE}/pulls",
            json={"title": title, "head": branch, "base": "main", "body": body},
            headers=GH_HEADERS,
        )
        if r.status_code == 422:
            # PR already exists - return existing
            existing = await c.get(
                f"{BASE}/pulls",
                params={"head": f"{GITHUB_OWNER}:{branch}", "state": "open"},
                headers=GH_HEADERS,
            )
            prs = existing.json()
            return prs[0] if prs else {}
        r.raise_for_status()
        return r.json()


async def get_branch_files(branch: str) -> list[str]:
    """ブランチの全ファイルパスを取得"""
    async with httpx.AsyncClient() as c:
        r = await c.get(
            f"{BASE}/git/trees/{branch}",
            params={"recursive": "1"},
            headers=GH_HEADERS,
        )
        if r.status_code != 200:
            return []
        tree = r.json().get("tree", [])
        return [item["path"] for item in tree if item["type"] == "blob"]
