-- Supabase Schema for Shared Memory System
-- Run this in Supabase SQL Editor (supabase.com → project → SQL Editor)

-- Table 1: shared_memory (key-value knowledge base)
CREATE TABLE shared_memory (
    id BIGSERIAL PRIMARY KEY,
    category TEXT NOT NULL,          -- 'decision', 'fact', 'preference', 'context'
    key TEXT NOT NULL,               -- e.g. 'ltv_cac_ratio', 'preferred_model'
    value TEXT NOT NULL,             -- the actual content
    source TEXT NOT NULL,            -- 'claude_code' or 'ark'
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(category, key)
);
CREATE INDEX idx_shared_memory_category ON shared_memory(category);

-- Table 2: conversation_log (Ark logs summaries for Claude Code)
CREATE TABLE conversation_log (
    id BIGSERIAL PRIMARY KEY,
    channel TEXT,
    thread_ts TEXT,
    user_name TEXT,
    summary TEXT NOT NULL,
    key_points JSONB DEFAULT '[]',
    action_items JSONB DEFAULT '[]',
    model_used TEXT,                 -- 'haiku' or 'sonnet'
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_conversation_log_created ON conversation_log(created_at DESC);

-- Table 3: task_log (both systems log completed work)
CREATE TABLE task_log (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,            -- 'claude_code' or 'ark'
    task_name TEXT NOT NULL,
    description TEXT,
    outcome TEXT,
    files_created JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_task_log_created ON task_log(created_at DESC);

-- Enable Row Level Security (required by Supabase, but we allow all for service use)
ALTER TABLE shared_memory ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE task_log ENABLE ROW LEVEL SECURITY;

-- Table 4: bi_cache (Supabase-backed BI data cache, survives deploys)
CREATE TABLE bi_cache (
    id BIGSERIAL PRIMARY KEY,
    metric_type TEXT NOT NULL,       -- 'shopify', 'meta_ads', 'skio'
    timeframe TEXT NOT NULL,         -- 'today', 'yesterday', 'last_7d', etc.
    data TEXT NOT NULL,              -- the full formatted metrics response
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(metric_type, timeframe)
);
CREATE INDEX idx_bi_cache_lookup ON bi_cache(metric_type, timeframe);

ALTER TABLE bi_cache ENABLE ROW LEVEL SECURITY;

-- Policies: allow all operations with anon key (our internal tools only)
CREATE POLICY "Allow all on shared_memory" ON shared_memory FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all on conversation_log" ON conversation_log FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all on task_log" ON task_log FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all on bi_cache" ON bi_cache FOR ALL USING (true) WITH CHECK (true);
