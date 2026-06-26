"""
Dify管理APIを使ってワークフローDSLをインポートするスクリプト
使用方法: python import_to_dify.py
"""
import os
import sys
import httpx

DIFY_API_KEY = "app-1lAkYPmfjz18MgOke1pjpVRv"
DIFY_BASE = "https://api.dify.ai/v1"
DSL_FILE = "dify_workflow_02_task_execution.yml"


def import_dsl():
    dsl_path = os.path.join(os.path.dirname(__file__), DSL_FILE)
    with open(dsl_path, "r", encoding="utf-8") as f:
        dsl_content = f.read()

    # Dify Import DSL API
    r = httpx.post(
        f"{DIFY_BASE}/apps/imports",
        headers={
            "Authorization": f"Bearer {DIFY_API_KEY}",
        },
        data={
            "mode": "yaml-content",
        },
        files={
            "data": ("workflow.yml", dsl_content.encode("utf-8"), "application/x-yaml"),
        },
        timeout=60,
    )
    print(f"Status: {r.status_code}")
    print(r.text)


if __name__ == "__main__":
    import_dsl()
