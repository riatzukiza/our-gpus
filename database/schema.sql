-- Ollama Discovery Platform Database Schema
-- SQLite with easy migration path to PostgreSQL

-- Enable foreign key constraints in SQLite
PRAGMA foreign_keys = ON;

-- Upload jobs tracking
CREATE TABLE IF NOT EXISTS upload_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    progress INTEGER DEFAULT 0,
    total_records INTEGER DEFAULT 0,
    processed_records INTEGER DEFAULT 0,
    error_message TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME
);

-- Discovered hosts from JSON uploads
CREATE TABLE IF NOT EXISTS hosts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    upload_job_id INTEGER NOT NULL,
    host TEXT NOT NULL,
    port INTEGER NOT NULL,
    protocol TEXT DEFAULT 'http',
    source_data TEXT, -- Original JSON data for this host
    geographic_location TEXT,
    organization TEXT,
    last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (upload_job_id) REFERENCES upload_jobs(id) ON DELETE CASCADE,
    UNIQUE(host, port, upload_job_id)
);

-- Ollama instance scan results
CREATE TABLE IF NOT EXISTS ollama_instances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    host_id INTEGER NOT NULL,
    ollama_url TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'inactive', 'error')),
    last_scanned DATETIME DEFAULT CURRENT_TIMESTAMP,
    response_time_ms INTEGER,
    
    -- Ollama-specific information
    ollama_version TEXT,
    api_version TEXT,
    gpu_capable BOOLEAN DEFAULT FALSE,
    total_vram_bytes INTEGER DEFAULT 0,
    system_info TEXT,
    error_message TEXT,
    
    -- Scan metadata
    scan_duration_ms INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (host_id) REFERENCES hosts(id) ON DELETE CASCADE,
    UNIQUE(host_id)
);

-- Available models on each instance
CREATE TABLE IF NOT EXISTS models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ollama_instance_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    tag TEXT,
    size_bytes INTEGER,
    parameter_size TEXT, -- e.g., "7B", "13B", "70B"
    family TEXT, -- e.g., "llama", "mistral", "qwen"
    architecture TEXT,
    quantization TEXT, -- e.g., "Q4_K_M", "Q8_0"
    
    -- Model metadata
    digest TEXT,
    modified_at DATETIME,
    details TEXT, -- JSON string of additional details
    
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (ollama_instance_id) REFERENCES ollama_instances(id) ON DELETE CASCADE,
    UNIQUE(ollama_instance_id, name, tag)
);

-- Currently loaded models (from /api/ps)
CREATE TABLE IF NOT EXISTS loaded_models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ollama_instance_id INTEGER NOT NULL,
    model_name TEXT NOT NULL,
    model_tag TEXT,
    vram_usage_bytes INTEGER DEFAULT 0,
    
    -- Loading metadata
    loaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME,
    
    FOREIGN KEY (ollama_instance_id) REFERENCES ollama_instances(id) ON DELETE CASCADE,
    UNIQUE(ollama_instance_id, model_name, model_tag)
);

-- Scan jobs for tracking discovery progress
CREATE TABLE IF NOT EXISTS scan_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    host_count INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    progress INTEGER DEFAULT 0,
    successful_scans INTEGER DEFAULT 0,
    failed_scans INTEGER DEFAULT 0,
    active_instances_found INTEGER DEFAULT 0,
    gpu_capable_found INTEGER DEFAULT 0,
    
    -- Configuration
    max_concurrent INTEGER DEFAULT 100,
    timeout_seconds INTEGER DEFAULT 5,
    
    -- Timing
    started_at DATETIME,
    completed_at DATETIME,
    duration_seconds INTEGER,
    
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Link scan jobs to the hosts they discover
CREATE TABLE IF NOT EXISTS scan_job_hosts (
    scan_job_id INTEGER NOT NULL,
    host_id INTEGER NOT NULL,
    
    PRIMARY KEY (scan_job_id, host_id),
    FOREIGN KEY (scan_job_id) REFERENCES scan_jobs(id) ON DELETE CASCADE,
    FOREIGN KEY (host_id) REFERENCES hosts(id) ON DELETE CASCADE
);

-- System configuration and settings
CREATE TABLE IF NOT EXISTS system_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_hosts_host_port ON hosts(host, port);
CREATE INDEX IF NOT EXISTS idx_hosts_upload_job ON hosts(upload_job_id);
CREATE INDEX IF NOT EXISTS idx_hosts_last_seen ON hosts(last_seen);

CREATE INDEX IF NOT EXISTS idx_ollama_instances_status ON ollama_instances(status);
CREATE INDEX IF NOT EXISTS idx_ollama_instances_last_scanned ON ollama_instances(last_scanned);
CREATE INDEX IF NOT EXISTS idx_ollama_instances_gpu_capable ON ollama_instances(gpu_capable);

CREATE INDEX IF NOT EXISTS idx_models_name ON models(name);
CREATE INDEX IF NOT EXISTS idx_models_family ON models(family);
CREATE INDEX IF NOT EXISTS idx_models_parameter_size ON models(parameter_size);

CREATE INDEX IF NOT EXISTS idx_loaded_models_instance ON loaded_models(ollama_instance_id);
CREATE INDEX IF NOT EXISTS idx_loaded_models_loaded_at ON loaded_models(loaded_at);

CREATE INDEX IF NOT EXISTS idx_upload_jobs_status ON upload_jobs(status);
CREATE INDEX IF NOT EXISTS idx_scan_jobs_status ON scan_jobs(status);

-- Insert default configuration
INSERT OR IGNORE INTO system_config (key, value, description) VALUES
    ('max_upload_size_gb', '10', 'Maximum file upload size in GB'),
    ('default_scan_timeout', '5', 'Default timeout for Ollama instance scanning in seconds'),
    ('max_concurrent_scans', '100', 'Maximum number of concurrent scans'),
    ('cleanup_interval_hours', '24', 'Hours between cleanup of old scan data'),
    ('database_version', '1.0.0', 'Current database schema version');

-- Create views for common queries
CREATE VIEW IF NOT EXISTS active_instances_summary AS
SELECT 
    oi.id,
    h.host,
    h.port,
    oi.ollama_url,
    oi.ollama_version,
    oi.gpu_capable,
    oi.total_vram_bytes,
    oi.last_scanned,
    COUNT(m.id) as model_count,
    COUNT(lm.id) as loaded_model_count,
    h.geographic_location,
    h.organization
FROM ollama_instances oi
JOIN hosts h ON oi.host_id = h.id
LEFT JOIN models m ON oi.id = m.ollama_instance_id
LEFT JOIN loaded_models lm ON oi.id = lm.ollama_instance_id
WHERE oi.status = 'active'
GROUP BY oi.id, h.host, h.port, oi.ollama_url, oi.ollama_version, oi.gpu_capable, oi.total_vram_bytes, oi.last_scanned, h.geographic_location, h.organization;

CREATE VIEW IF NOT EXISTS model_popularity AS
SELECT 
    m.name,
    m.family,
    m.parameter_size,
    COUNT(*) as instance_count,
    COUNT(DISTINCT h.host) as unique_hosts,
    AVG(m.size_bytes) as avg_size_bytes
FROM models m
JOIN ollama_instances oi ON m.ollama_instance_id = oi.id
JOIN hosts h ON oi.host_id = h.id
WHERE oi.status = 'active'
GROUP BY m.name, m.family, m.parameter_size
ORDER BY instance_count DESC;