"""Supabase CRUD ヘルパー"""
import httpx
from config import SUPABASE_URL, SUPA_HEADERS


async def supa_post(table: str, data: dict) -> dict:
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{SUPABASE_URL}/{table}", json=data, headers=SUPA_HEADERS)
        r.raise_for_status()
        rows = r.json()
        return rows[0] if rows else data


async def supa_patch(table: str, id_val: str, data: dict) -> dict:
    async with httpx.AsyncClient() as c:
        r = await c.patch(f"{SUPABASE_URL}/{table}?id=eq.{id_val}", json=data, headers=SUPA_HEADERS)
        r.raise_for_status()
        rows = r.json()
        return rows[0] if rows else data


async def get_task(task_id: str) -> dict | None:
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{SUPABASE_URL}/tasks?id=eq.{task_id}&select=*", headers=SUPA_HEADERS)
        r.raise_for_status()
        rows = r.json()
        return rows[0] if rows else None


async def get_project(project_id: str) -> dict | None:
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{SUPABASE_URL}/projects?id=eq.{project_id}&select=*", headers=SUPA_HEADERS)
        r.raise_for_status()
        rows = r.json()
        return rows[0] if rows else None


async def get_pending_tasks(project_id: str) -> list[dict]:
    async with httpx.AsyncClient() as c:
        r = await c.get(
            f"{SUPABASE_URL}/tasks?project_id=eq.{project_id}&status=eq.pending&select=*&order=priority",
            headers=SUPA_HEADERS,
        )
        r.raise_for_status()
        return r.json()


async def update_task(task_id: str, **fields) -> dict | None:
    async with httpx.AsyncClient() as c:
        r = await c.patch(
            f"{SUPABASE_URL}/tasks?id=eq.{task_id}",
            json=fields,
            headers=SUPA_HEADERS,
        )
        r.raise_for_status()
        rows = r.json()
        return rows[0] if rows else None


async def insert_execution(task_id: str, attempt: int, result: str, error_log: str = "") -> None:
    async with httpx.AsyncClient() as c:
        r = await c.post(
            f"{SUPABASE_URL}/executions",
            json={"task_id": task_id, "attempt": attempt, "result": result, "error_log": error_log},
            headers=SUPA_HEADERS,
        )
        r.raise_for_status()


async def update_project_file_map(project_id: str, new_files: list[dict]) -> None:
    async with httpx.AsyncClient() as c:
        r = await c.get(
            f"{SUPABASE_URL}/projects?id=eq.{project_id}&select=file_map",
            headers=SUPA_HEADERS,
        )
        rows = r.json()
        current = rows[0].get("file_map") or {} if rows else {}
        for f in new_files:
            current[f["path"]] = f.get("description", "")
        method = c.patch if rows else c.post
        url = f"{SUPABASE_URL}/projects?id=eq.{project_id}" if rows else f"{SUPABASE_URL}/projects"
        payload = {"file_map": current} if rows else {"id": project_id, "file_map": current, "status": "active"}
        await method(url, json=payload, headers=SUPA_HEADERS)


async def insert_deployment(project_id: str, environment: str, version: str, status: str) -> None:
    async with httpx.AsyncClient() as c:
        r = await c.post(
            f"{SUPABASE_URL}/deployments",
            json={"project_id": project_id, "environment": environment, "version": version, "status": status},
            headers=SUPA_HEADERS,
        )
        r.raise_for_status()
