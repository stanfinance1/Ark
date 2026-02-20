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

-- Table 5: tool_registry (all tools across all systems, auto-updated on use)
CREATE TABLE tool_registry (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,           -- tool function name
    system TEXT NOT NULL,                -- 'ark', 'claude_code', 'concierge'
    group_name TEXT,                     -- logical grouping: 'core', 'web', 'bi', etc.
    description TEXT NOT NULL,           -- what the tool does
    file_path TEXT,                      -- source file where defined
    enabled BOOLEAN DEFAULT true,
    use_count BIGINT DEFAULT 0,          -- auto-incremented on each use
    last_used_at TIMESTAMPTZ,            -- auto-updated on each use
    last_used_by TEXT,                   -- who triggered it (user/channel)
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_tool_registry_system ON tool_registry(system);
CREATE INDEX idx_tool_registry_group ON tool_registry(group_name);

ALTER TABLE tool_registry ENABLE ROW LEVEL SECURITY;

-- Table 6: tool_usage_log (append-only log of every tool invocation)
CREATE TABLE tool_usage_log (
    id BIGSERIAL PRIMARY KEY,
    tool_name TEXT NOT NULL REFERENCES tool_registry(name),
    system TEXT NOT NULL,                -- 'ark', 'claude_code', 'concierge'
    invoked_by TEXT,                     -- user or channel
    success BOOLEAN DEFAULT true,
    duration_ms INTEGER,                 -- execution time
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_tool_usage_log_tool ON tool_usage_log(tool_name);
CREATE INDEX idx_tool_usage_log_created ON tool_usage_log(created_at DESC);

ALTER TABLE tool_usage_log ENABLE ROW LEVEL SECURITY;

-- Auto-update trigger: when a row is inserted into tool_usage_log,
-- bump use_count and last_used_at on the corresponding tool_registry row.
CREATE OR REPLACE FUNCTION fn_update_tool_stats()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE tool_registry
    SET use_count = use_count + 1,
        last_used_at = NEW.created_at,
        last_used_by = NEW.invoked_by,
        updated_at = NOW()
    WHERE name = NEW.tool_name;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_tool_usage_stats
AFTER INSERT ON tool_usage_log
FOR EACH ROW
EXECUTE FUNCTION fn_update_tool_stats();

-- Table 7: daily_metrics (permanent historical daily data for instant BI lookups)
CREATE TABLE daily_metrics (
    id          BIGSERIAL PRIMARY KEY,
    date        DATE NOT NULL,               -- Pacific calendar day (YYYY-MM-DD)
    source      TEXT NOT NULL,               -- 'shopify_dtc' | 'shopify_wholesale' | 'meta_ads'
    data        JSONB NOT NULL,              -- metric payload (shape varies by source)
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(date, source)
);
CREATE INDEX idx_daily_metrics_lookup ON daily_metrics(date, source);
CREATE INDEX idx_daily_metrics_source ON daily_metrics(source, date DESC);

ALTER TABLE daily_metrics ENABLE ROW LEVEL SECURITY;

-- Policies: allow all operations with anon key (our internal tools only)
CREATE POLICY "Allow all on shared_memory" ON shared_memory FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all on conversation_log" ON conversation_log FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all on task_log" ON task_log FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all on bi_cache" ON bi_cache FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all on tool_registry" ON tool_registry FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all on tool_usage_log" ON tool_usage_log FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all on daily_metrics" ON daily_metrics FOR ALL USING (true) WITH CHECK (true);
