# dev-supervisor — 汎用AI開発監督システム

要件を自然言語で入力すると、**設計 → コード生成 → GitHub → Railway → Vercel** までを自動実行するAI開発監督システム。詰まった箇所では手動対応を依頼し、完了確認を取りながら続きを進める。

## デモ

| 画面 | URL |
|------|-----|
| フロントエンド | https://dev-supervisor-ui.vercel.app |
| バックエンドAPI | https://dev-supervisor-production.up.railway.app/health |

---

## システム構成

```
ユーザー（要件を自然言語で入力）
  ↓
frontend/          React + Vite（Vercel）
  ↓ /brainstorm → /pipeline/start → /pipeline/resume
backend/           FastAPI（Railway）
  ↓ Dify LLM でコード生成 / GitHub API でリポジトリ管理
kassamassa/Develop （生成コードのCIターゲット）
  ↓ GitHub Actions → テスト → /test-result webhook
backend/           検証 → PR作成 or 修正ループ
```

## リポジトリ構成

```
dev-supervisor/
├── backend/                    FastAPI バックエンド（Railway）
│   ├── main.py                 全エンドポイント
│   ├── pipeline_executor.py    動的パイプライン（11ステップ）
│   ├── config.py               環境変数・定数
│   ├── supabase_client.py      Supabase REST helpers
│   ├── workflow_01_chain.py    ①→② 自動連鎖
│   ├── workflow_02_task_exec.py ② タスク実行（Dify コード生成）
│   ├── workflow_03_verify.py   ③ 検証（GitHub Actions webhook）
│   ├── workflow_04_notify.py   ④ 通知
│   └── requirements.txt
├── frontend/                   React + Vite（Vercel）
│   └── src/pages/
│       ├── Dashboard.jsx       プロジェクト一覧
│       ├── NewProject.jsx      壁打ちウィザード（4ステップ）
│       ├── ProjectDetail.jsx   カンバンボード + チャット
│       └── PipelineView.jsx    パイプライン進捗（リアルタイム）
├── dify/                       Dify ワークフロー DSL（YML）
│   ├── dify_codegen_only.yml   コード生成専用ワークフロー
│   ├── dify_workflow_02_*.yml  タスク実行ワークフロー
│   └── dify_workflow_04_*.yml  通知ワークフロー
├── supabase/
│   └── supabase_tables_phase2a.sql  テーブル定義
├── .github/workflows/ci.yml   生成コードのCI設定
├── .env.example               必要な環境変数一覧
└── CLAUDE.md                  アーキテクチャ詳細
```

---

## セットアップ

### 1. 環境変数

`.env.example` を参考に Railway と Vercel に環境変数を設定する。

**Railway（バックエンド）に必要なもの：**

| 変数名 | 内容 |
|--------|------|
| `SUPABASE_KEY` | Supabase anon key |
| `GITHUB_TOKEN` | Personal Access Token（repo スコープ） |
| `DIFY_TASK_EXEC_KEY` | ②タスク実行ワークフローの API キー |
| `DIFY_CODEGEN_KEY` | コード生成・壁打ちワークフローの API キー |

**Vercel（フロントエンド）に必要なもの：**

| 変数名 | 内容 |
|--------|------|
| `VITE_SUPABASE_URL` | `https://<project>.supabase.co` |
| `VITE_SUPABASE_ANON_KEY` | Supabase anon key |
| `VITE_RAILWAY_URL` | Railway のデプロイ URL |

### 2. Supabase テーブル作成

`supabase/supabase_tables_phase2a.sql` を Supabase SQL Editor で実行する。

### 3. Dify ワークフロー インポート

`dify/` 配下の YML を Dify コンソール → スタジオ → インポートで読み込む。  
インポート後、各ワークフローの API キーを Railway 環境変数に設定する。

### 4. バックエンド デプロイ

```bash
cd backend
railway up --service dev-supervisor
```

### 5. フロントエンド デプロイ

```bash
cd frontend
npx vercel --prod
```

---

## 動的パイプライン（11ステップ）

```
requirements_analysis    自動：要件分析・設計提示
dify_dsl_generate        自動：Dify DSL 生成
dify_check_key           ブロッカー：Dify API キー確認
dify_import              自動：Dify ワークフロー インポート
dify_publish             ブロッカー：Dify 公開ボタン押下依頼
github_create            自動：GitHub リポジトリ作成
railway_check            ブロッカー：Railway Token 確認
railway_deploy           自動：Railway デプロイ
vercel_check             ブロッカー：Vercel Token 確認
vercel_deploy            自動：Vercel デプロイ
complete                 完了通知
```

ブロッカーステップでは UI の BlockerCard にトークン入力欄が表示される。  
入力して「続行」を押すと `/pipeline/resume` が呼ばれ次ステップへ進む。

---

## API エンドポイント

| メソッド | パス | 役割 |
|---------|------|------|
| POST | `/brainstorm` | 壁打ち（Dify LLM） |
| POST | `/brainstorm/stream` | 壁打ち SSE 版（進捗リアルタイム） |
| POST | `/pipeline/start` | 動的パイプライン開始 |
| POST | `/pipeline/resume` | ブロッカー解除後の続行 |
| GET  | `/pipeline/session/{id}` | セッション + ステップ状態取得 |
| POST | `/run-task` | タスク実行（コード生成 → GitHub Push） |
| POST | `/trigger-pipeline` | ①→② 自動連鎖 |
| POST | `/github-webhook` | GitHub Actions webhook 受信 |
| POST | `/test-result` | テスト結果受信 |
| POST | `/notify` | 通知送信 |
| GET  | `/health` | ヘルスチェック |

---

## ロードマップ

| フェーズ | 内容 | 状態 |
|---------|------|------|
| Phase 1 | Supabase + Dify 4WF + FastAPI + GitHub Actions | ✅ 完了 |
| Phase 2-C | React ダッシュボード + 壁打ち UI（Vercel） | ✅ 完了 |
| Phase 2-A | 動的パイプライン（ブロッカー検出・resume） | ✅ 完了 |
| Phase 2-B | Dify 公開ボタン → API 自動化 | ⏳ 次 |
| Phase 2-D | Railway/Vercel ブロッカーゼロ化（完全自動デプロイ） | ⏳ 未着手 |
| Phase 3 | RLS・セキュリティ強化・マルチユーザー対応 | ⏳ 未着手 |

---

## 技術スタック

| レイヤー | 技術 |
|---------|------|
| フロントエンド | React + Vite、Supabase Realtime、React Router v7 |
| バックエンド | FastAPI、uvicorn、httpx |
| データベース | Supabase（PostgreSQL） |
| LLM | Dify（claude-sonnet-4-6） |
| CI/CD | GitHub Actions → `kassamassa/Develop` |
| インフラ | Railway（backend）、Vercel（frontend） |
