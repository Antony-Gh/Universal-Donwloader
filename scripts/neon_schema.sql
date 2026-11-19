-- ==============================================================================
-- Universal Media Downloader - Neon Serverless Postgres Telemetry Schema
-- ==============================================================================
-- This schema tracks anonymous device installations and breakdown across
-- Desktop PCs, Laptops, Android phones/tablets, and operating systems.
--
-- Privacy Guarantee:
-- No personal information, IP addresses, downloaded URLs, filenames, or user
-- credentials are ever collected or stored. Only anonymous random install UUIDs
-- and hardware form factors (e.g., Desktop PC vs. Laptop vs. Android) are recorded.
-- ==============================================================================

-- 1. Device installations table
CREATE TABLE IF NOT EXISTS device_installs (
    install_id UUID PRIMARY KEY,
    device_type VARCHAR(32) NOT NULL DEFAULT 'Unknown', -- 'Desktop PC', 'Laptop', 'Android', 'macOS', 'Linux Desktop', etc.
    os_name VARCHAR(64) NOT NULL DEFAULT 'Unknown',     -- e.g. 'Windows 11', 'Android 15', 'Ubuntu 24.04', 'macOS Sonoma'
    device_model VARCHAR(128) DEFAULT NULL,             -- e.g. 'Lenovo Legion', 'Samsung SM-S928B', 'Custom PC'
    app_version VARCHAR(32) NOT NULL DEFAULT '0.0.0',   -- e.g. '3.4.0'
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    heartbeat_count INT NOT NULL DEFAULT 1
);

-- Indexes for lightning-fast analytics queries on large installs
CREATE INDEX IF NOT EXISTS idx_device_installs_device_type ON device_installs (device_type);
CREATE INDEX IF NOT EXISTS idx_device_installs_last_seen ON device_installs (last_seen_at);
CREATE INDEX IF NOT EXISTS idx_device_installs_app_version ON device_installs (app_version);
CREATE INDEX IF NOT EXISTS idx_device_installs_os_name ON device_installs (os_name);

-- 2. Atomic Upsert Heartbeat Function (Callable directly over Neon HTTP API)
CREATE OR REPLACE FUNCTION record_device_heartbeat(
    p_install_id UUID,
    p_device_type VARCHAR,
    p_os_name VARCHAR,
    p_device_model VARCHAR,
    p_app_version VARCHAR
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_is_new BOOLEAN := FALSE;
BEGIN
    INSERT INTO device_installs (
        install_id,
        device_type,
        os_name,
        device_model,
        app_version,
        first_seen_at,
        last_seen_at,
        heartbeat_count
    ) VALUES (
        p_install_id,
        COALESCE(NULLIF(p_device_type, ''), 'Unknown'),
        COALESCE(NULLIF(p_os_name, ''), 'Unknown'),
        NULLIF(p_device_model, ''),
        COALESCE(NULLIF(p_app_version, ''), '0.0.0'),
        NOW(),
        NOW(),
        1
    )
    ON CONFLICT (install_id) DO UPDATE SET
        last_seen_at = NOW(),
        heartbeat_count = device_installs.heartbeat_count + 1,
        app_version = EXCLUDED.app_version,
        os_name = EXCLUDED.os_name,
        device_type = CASE 
            WHEN EXCLUDED.device_type <> 'Unknown' THEN EXCLUDED.device_type 
            ELSE device_installs.device_type 
        END,
        device_model = COALESCE(EXCLUDED.device_model, device_installs.device_model)
    RETURNING (xmax = 0) INTO v_is_new;

    RETURN jsonb_build_object(
        'status', 'ok',
        'is_new', v_is_new,
        'server_time', NOW()
    );
END;
$$;

-- 3. Analytics Aggregation Views for Owner Dashboard
CREATE OR REPLACE VIEW v_device_stats AS
SELECT
    COUNT(*) AS total_unique_devices,
    COUNT(*) FILTER (WHERE device_type = 'Desktop PC') AS desktop_pcs,
    COUNT(*) FILTER (WHERE device_type = 'Laptop') AS laptops,
    COUNT(*) FILTER (WHERE device_type = 'Android') AS android_devices,
    COUNT(*) FILTER (WHERE device_type NOT IN ('Desktop PC', 'Laptop', 'Android')) AS other_devices,
    COUNT(*) FILTER (WHERE last_seen_at >= NOW() - INTERVAL '7 days') AS active_last_7_days,
    COUNT(*) FILTER (WHERE last_seen_at >= NOW() - INTERVAL '30 days') AS active_last_30_days
FROM device_installs;

CREATE OR REPLACE VIEW v_device_breakdown AS
SELECT
    device_type,
    os_name,
    COUNT(*) AS install_count,
    ROUND(COUNT(*) * 100.0 / NULLIF((SELECT COUNT(*) FROM device_installs), 0), 2) AS percentage,
    COUNT(*) FILTER (WHERE last_seen_at >= NOW() - INTERVAL '30 days') AS active_30d
FROM device_installs
GROUP BY device_type, os_name
ORDER BY install_count DESC;

CREATE OR REPLACE VIEW v_version_breakdown AS
SELECT
    app_version,
    COUNT(*) AS install_count,
    ROUND(COUNT(*) * 100.0 / NULLIF((SELECT COUNT(*) FROM device_installs), 0), 2) AS percentage
FROM device_installs
GROUP BY app_version
ORDER BY install_count DESC;
