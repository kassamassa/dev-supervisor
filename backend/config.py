"""共通設定・定数"""
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

SUPABASE_URL  = "https://thfthbblfsjhyqcinyms.supabase.co/rest/v1"
SUPABASE_KEY  = os.getenv("SUPABASE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRoZnRoYmJsZnNqaHlxY2lueW1zIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODIzMTc1NzAsImV4cCI6MjA5Nzg5MzU3MH0"
    ".OTPCMrfgHFDNOvAfw19TKx4ejJudU5zHYDPjEUD5wFs")
GITHUB_TOKEN  = os.getenv("GITHUB_TOKEN",  "{{GITHUB_TOKEN}}")
GITHUB_OWNER  = "kassamassa"
GITHUB_REPO   = "Develop"
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DIFY_BASE     = "https://api.dify.ai/v1"
DIFY_TASK_EXEC_KEY  = os.getenv("DIFY_TASK_EXEC_KEY", "app-1lAkYPmfjz18MgOke1pjpVRv")
# コード生成専用ワークフロー (dify_codegen_only.yml をインポートした後に設定)
DIFY_CODEGEN_KEY    = os.getenv("DIFY_CODEGEN_KEY", "")
# 壁打ち専用ワークフロー (dify_brainstorm.yml をインポートした後に設定)
DIFY_BRAINSTORM_KEY = os.getenv("DIFY_BRAINSTORM_KEY", "")

SUPA_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}
GH_HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

MAX_FIX_ATTEMPTS = 5  # 自動修正上限回数
