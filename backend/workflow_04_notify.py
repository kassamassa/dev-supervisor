"""
④通知ワークフロー（共通モジュール）
①②③から呼び出される。種別に応じてメッセージを整形しDifyチャットへ出力。
"""
import httpx
from config import DIFY_BASE, DIFY_TASK_EXEC_KEY


NOTIFY_TEMPLATES = {
    "task_started": (
        "🚀 **タスク開始**\n"
        "- タスク: {task_title}\n"
        "- ブランチ: `{branch}`\n"
        "- ステータス: in_progress"
    ),
    "task_completed": (
        "✅ **タスク完了**\n"
        "- タスク: {task_title}\n"
        "- ブランチ: `{branch}`\n"
        "- 生成ファイル: {files}\n"
        "- 概要: {summary}"
    ),
    "test_passed": (
        "🟢 **テスト通過**\n"
        "- タスク: {task_title}\n"
        "- ブランチ: `{branch}`\n"
        "- PRを作成しました → #{pr_number}"
    ),
    "test_failed": (
        "🔴 **テスト失敗**\n"
        "- タスク: {task_title}\n"
        "- ブランチ: `{branch}`\n"
        "- 修正試行: {attempt}/{max_attempts}回目\n"
        "- エラー概要: {error_summary}"
    ),
    "escalation": (
        "🆘 **エスカレーション（要確認）**\n"
        "- タスク: {task_title}\n"
        "- ブランチ: `{branch}`\n"
        "- 自動修正上限({max_attempts}回)に達しました\n"
        "- エラーログ:\n```\n{error_log}\n```\n"
        "→ 手動確認をお願いします"
    ),
    "requirements_received": (
        "📋 **要件受付完了**\n"
        "- プロジェクト: {project_name}\n"
        "- タスク数: {task_count}件\n"
        "- ステータス: ②タスク実行ワークフローを開始します"
    ),
    "pr_merged": (
        "🎉 **PRマージ完了**\n"
        "- タスク: {task_title}\n"
        "- PR: #{pr_number}\n"
        "- mainブランチへのマージが完了しました"
    ),
}


def format_message(notify_type: str, **kwargs) -> str:
    template = NOTIFY_TEMPLATES.get(notify_type, "通知: {notify_type}")
    try:
        return template.format(notify_type=notify_type, **kwargs)
    except KeyError as e:
        return f"[通知] {notify_type}: {kwargs} (KeyError: {e})"


async def send_to_dify_chat(message: str, user_id: str = "dev-supervisor") -> None:
    """Difyのワークフロー出力としてメッセージを送信"""
    # ④通知ワークフローはDify workflow として実行
    # ここではコンソール出力 + Dify API経由で通知
    print(f"\n[④通知] {message}\n")

    # Dify ④ workflow が構築されたら以下を有効化:
    # payload = {
    #     "inputs": {"message": message, "notify_type": notify_type},
    #     "response_mode": "blocking",
    #     "user": user_id,
    # }
    # async with httpx.AsyncClient(timeout=30) as c:
    #     await c.post(f"{DIFY_BASE}/workflows/run",
    #                  json=payload,
    #                  headers={"Authorization": f"Bearer {DIFY_NOTIFY_KEY}"})


async def notify(notify_type: str, user_id: str = "dev-supervisor", **kwargs) -> str:
    """通知を送信して整形済みメッセージを返す"""
    msg = format_message(notify_type, **kwargs)
    await send_to_dify_chat(msg, user_id)
    return msg
