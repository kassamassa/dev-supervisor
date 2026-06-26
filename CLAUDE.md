# dev-supervisor — AI開発監督システム

## アーキテクチャ概要

```
ユーザー（壮輝）
  ↓ 要件を自然言語で入力
frontend/  (React + Vite → Vercel)
  ↓ POST /brainstorm, /pipeline/start, /pipeline/resume
backend/   (FastAPI → Railway)
  ↓ Dify LLM でコード生成 / GitHub API でリポジトリ管理
kassamassa/Develop  (生成コードのCI/CDターゲット)
  ↓ GitHub Actions → テスト → dev-supervisor /test-result webhook
backend/   (③検証 → PR作成 or 修正ループ)
```

## リポジトリ構成

```
dev-supervisor/
├── backend/              FastAPI バックエンド（Railway にデプロイ）
│   ├── main.py           全エンドポイント定義
│   ├── config.py         環境変数・定数
│   ├── pipeline_executor.py  動的パイプライン（11ステップ）
│   ├── supabase_client.py    Supabase REST helpers
│   ├── workflow_01_chain.py  ①→② 自動連鎖
│   ├── workflow_02_task_exec.py  ② タスク実行（Dify コード生成）
│   ├── workflow_03_verify.py     ③ 検証（GitHub Actions webhook）
│   ├── workflow_04_notify.py     ④ 通知
│   ├── requirements.txt
│   ├── Procfile          uvicorn main:app --host 0.0.0.0 --port $PORT
│   └── railway.json
├── frontend/             React + Vite フロントエンド（Vercel にデプロイ）
│   ├── src/pages/
│   │   ├── Dashboard.jsx     プロジェクト一覧
│   │   ├── NewProject.jsx    壁打ちウィザード（4ステップ）
│   │   ├── ProjectDetail.jsx カンバンボード + チャット
│   │   └── PipelineView.jsx  パイプライン進捗（リアルタイム）
│   └── src/supabase.js   Supabase クライアント + RAILWAY_URL
├── dify/                 Dify ワークフロー DSL（YMLファイル）
│   ├── dify_codegen_only.yml         コード生成専用 WF
│   ├── dify_workflow_02_task_execution.yml  ② タスク実行 WF
│   └── dify_workflow_04_notify.yml   ④ 通知 WF
├── supabase/             DB スキーマ定義
│   └── supabase_tables_phase2a.sql   pipeline_sessions / pipeline_steps
├── .github/workflows/
│   └── ci.yml            生成コードのCI（kassamassa/Develop にも配置済み）
├── .env.example          必要な環境変数一覧
└── CLAUDE.md             ← このファイル

```

## 稼働中サービス

| レイヤー | URL | 状態 |
|---------|-----|------|
| フロントエンド | https://dev-supervisor-ui.vercel.app | ✅ 稼働中 |
| バックエンド | https://dev-supervisor-production.up.railway.app | ✅ 稼働中 |
| データベース | Supabase (thfthbblfsjhyqcinyms) | ✅ 6テーブル |
| 生成コードCI | kassamassa/Develop (.github/workflows/ci.yml) | ✅ 稼働中 |

## 主要エンドポイント

| メソッド | パス | 役割 |
|---------|------|------|
| POST | /brainstorm | 壁打ち（Dify LLM） |
| POST | /brainstorm/stream | 壁打ち SSE 版（進捗リアルタイム） |
| POST | /pipeline/start | 動的パイプライン開始（11ステップ） |
| POST | /pipeline/resume | ブロッカー解除後の続行 |
| GET  | /pipeline/session/{id} | セッション + ステップ状態取得 |
| POST | /run-task | ② タスク実行（コード生成 → GitHub Push） |
| POST | /trigger-pipeline | ①→② 自動連鎖 |
| POST | /github-webhook | GitHub Actions webhook 受信 |
| POST | /test-result | テスト結果受信 |
| POST | /notify | 通知送信 |

## 動的パイプライン（11ステップ）

```
requirements_analysis → dify_dsl_generate → dify_check_key [BLOCKER]
  → dify_import → dify_publish [BLOCKER]
  → github_create → railway_check [BLOCKER]
  → railway_deploy → vercel_check [BLOCKER]
  → vercel_deploy → complete
```

BLOCKERステップでは UI の BlockerCard にトークン入力欄が表示される。
/pipeline/resume に user_data を渡すと次ステップへ続行。

## LLM バックエンド

brainstorm は **Dify LLM ノード経由**（Anthropic を直接呼ばない）。
- 使用キー: `DIFY_CODEGEN_KEY`（Railway 環境変数）
- エンドポイント: `POST /v1/workflows/run`

## Supabase テーブル

| テーブル | 用途 |
|---------|------|
| projects | プロジェクト管理 |
| tasks | タスク管理（カンバン） |
| executions | タスク実行ログ |
| deployments | デプロイ履歴 |
| pipeline_sessions | 動的パイプラインセッション |
| pipeline_steps | ステップ単位の進捗 |

RLS は開発フェーズで無効化中。Phase 3 で有効化予定。

## 環境変数（Railway）

`.env.example` を参照。最低限必要なもの:
- `SUPABASE_KEY`
- `GITHUB_TOKEN`
- `DIFY_TASK_EXEC_KEY`
- `DIFY_CODEGEN_KEY` ← brainstorm に必須

## ロードマップ

| フェーズ | 内容 | 状態 |
|---------|------|------|
| Phase 1 | Supabase + Dify 4WF + FastAPI + GitHub Actions | ✅ 完了 |
| Phase 2-C | React ダッシュボード + 壁打ち UI | ✅ 完了 |
| Phase 2-A | 動的パイプライン（ブロッカー検出・resume） | ✅ 完了 |
| Phase 2-B | Dify 公開ボタン → API 自動化 | ⏳ 次 |
| Phase 2-D | Railway/Vercel ブロッカーゼロ化 | ⏳ 未着手 |
| Phase 3 | RLS・セキュリティ・マルチユーザー | ⏳ 未着手 |
