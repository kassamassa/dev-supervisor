-- Phase 2-A: 動的パイプライン用テーブル
-- Supabase SQL Editor で実行してください

-- pipeline_sessions: パイプライン実行セッション
CREATE TABLE IF NOT EXISTS public.pipeline_sessions (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id      uuid,
  project_name    text NOT NULL,
  requirements    text,
  status          text NOT NULL DEFAULT 'running',  -- running / blocked / completed
  current_step    text,
  blocker_type    text,
  blocker_message text,
  context         jsonb DEFAULT '{}',
  created_at      timestamptz DEFAULT now(),
  updated_at      timestamptz DEFAULT now()
);

-- pipeline_steps: 各ステップの状態
CREATE TABLE IF NOT EXISTS public.pipeline_steps (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id   uuid NOT NULL REFERENCES public.pipeline_sessions(id) ON DELETE CASCADE,
  step_key     text NOT NULL,
  step_name    text NOT NULL,
  order_index  int  NOT NULL DEFAULT 0,
  status       text NOT NULL DEFAULT 'pending',  -- pending / running / done / blocked
  result       text,
  started_at   timestamptz,
  finished_at  timestamptz,
  created_at   timestamptz DEFAULT now()
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_pipeline_steps_session ON public.pipeline_steps(session_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_sessions_project ON public.pipeline_sessions(project_id);

-- RLS 無効化（開発フェーズ）
ALTER TABLE public.pipeline_sessions DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.pipeline_steps     DISABLE ROW LEVEL SECURITY;

-- updated_at 自動更新トリガー
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_pipeline_sessions_updated ON public.pipeline_sessions;
CREATE TRIGGER trg_pipeline_sessions_updated
  BEFORE UPDATE ON public.pipeline_sessions
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();
