-- ==============================================================================
-- Universal Media Downloader - Neon Serverless Postgres Telemetry Schema
-- ==============================================================================
-- This schema tracks anonymous device installations and breakdown across
-- Desktop PCs, Laptops, Android devices, hardware specs, regional demographics,
-- and optional identified friends / beta-testers (via referral tags or filenames).
--
-- Privacy Guarantee:
-- No personal information, IP addresses, downloaded URLs, filenames, or user
-- credentials are ever collected or stored. Only anonymous random install UUIDs,
-- hardware capabilities, regional locales, and voluntary friend/referral tags
-- are recorded.
-- ==============================================================================

-- 1. Device installations table
CREATE TABLE IF NOT EXISTS device_installs (
    install_id UUID PRIMARY KEY,
    device_type VARCHAR(32) NOT NULL DEFAULT 'Unknown', -- 'Desktop PC', 'Laptop', 'Android', 'macOS', 'Linux Desktop', etc.
    os_name VARCHAR(64) NOT NULL DEFAULT 'Unknown',     -- e.g. 'Windows 11', 'Android 15', 'Ubuntu 24.04', 'macOS Sonoma'
    device_model VARCHAR(128) DEFAULT NULL,             -- e.g. 'Lenovo Legion', 'Samsung SM-S928B', 'Custom PC'
    app_version VARCHAR(32) NOT NULL DEFAULT '0.0.0',   -- e.g. '3.4.0'
    locale VARCHAR(32) DEFAULT NULL,                    -- e.g. 'en_US', 'ar_EG', 'fr_FR'
    timezone VARCHAR(64) DEFAULT NULL,                  -- e.g. 'America/New_York', 'Africa/Cairo', 'UTC+02:00'
    cpu_cores INT DEFAULT NULL,                         -- e.g. 4, 8, 16
    cpu_arch VARCHAR(32) DEFAULT NULL,                  -- e.g. 'x86_64', 'arm64-v8a', 'arm64'
    total_ram_gb NUMERIC(5, 1) DEFAULT NULL,            -- e.g. 8.0, 16.0, 32.0
    screen_res VARCHAR(32) DEFAULT NULL,                -- e.g. '1920x1080', '2560x1440', '1080x2340'
    connection_type VARCHAR(32) DEFAULT NULL,           -- e.g. 'Wi-Fi', 'Ethernet', 'Cellular'
    friend_tag VARCHAR(64) DEFAULT NULL,                -- e.g. 'ahmed', 'sara', 'beta-tester-1'
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    heartbeat_count INT NOT NULL DEFAULT 1
);

-- Backward compatibility for existing tables
ALTER TABLE device_installs ADD COLUMN IF NOT EXISTS locale VARCHAR(32) DEFAULT NULL;
ALTER TABLE device_installs ADD COLUMN IF NOT EXISTS timezone VARCHAR(64) DEFAULT NULL;
ALTER TABLE device_installs ADD COLUMN IF NOT EXISTS cpu_cores INT DEFAULT NULL;
ALTER TABLE device_installs ADD COLUMN IF NOT EXISTS cpu_arch VARCHAR(32) DEFAULT NULL;
ALTER TABLE device_installs ADD COLUMN IF NOT EXISTS total_ram_gb NUMERIC(5, 1) DEFAULT NULL;
ALTER TABLE device_installs ADD COLUMN IF NOT EXISTS screen_res VARCHAR(32) DEFAULT NULL;
ALTER TABLE device_installs ADD COLUMN IF NOT EXISTS connection_type VARCHAR(32) DEFAULT NULL;
ALTER TABLE device_installs ADD COLUMN IF NOT EXISTS friend_tag VARCHAR(64) DEFAULT NULL;

-- Indexes for fast analytics queries
CREATE INDEX IF NOT EXISTS idx_device_installs_device_type ON device_installs (device_type);
CREATE INDEX IF NOT EXISTS idx_device_installs_last_seen ON device_installs (last_seen_at);
CREATE INDEX IF NOT EXISTS idx_device_installs_app_version ON device_installs (app_version);
CREATE INDEX IF NOT EXISTS idx_device_installs_os_name ON device_installs (os_name);
CREATE INDEX IF NOT EXISTS idx_device_installs_locale ON device_installs (locale);
CREATE INDEX IF NOT EXISTS idx_device_installs_friend_tag ON device_installs (friend_tag);

-- 2. Atomic Upsert Heartbeat Function (Supports friend/referral tag)
CREATE OR REPLACE FUNCTION record_device_heartbeat(
    p_install_id UUID,
    p_device_type VARCHAR,
    p_os_name VARCHAR,
    p_device_model VARCHAR,
    p_app_version VARCHAR,
    p_locale VARCHAR DEFAULT NULL,
    p_timezone VARCHAR DEFAULT NULL,
    p_cpu_cores INT DEFAULT NULL,
    p_cpu_arch VARCHAR DEFAULT NULL,
    p_total_ram_gb NUMERIC DEFAULT NULL,
    p_screen_res VARCHAR DEFAULT NULL,
    p_connection_type VARCHAR DEFAULT NULL,
    p_friend_tag VARCHAR DEFAULT NULL
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
        locale,
        timezone,
        cpu_cores,
        cpu_arch,
        total_ram_gb,
        screen_res,
        connection_type,
        friend_tag,
        first_seen_at,
        last_seen_at,
        heartbeat_count
    ) VALUES (
        p_install_id,
        COALESCE(NULLIF(p_device_type, ''), 'Unknown'),
        COALESCE(NULLIF(p_os_name, ''), 'Unknown'),
        NULLIF(p_device_model, ''),
        COALESCE(NULLIF(p_app_version, ''), '0.0.0'),
        NULLIF(p_locale, ''),
        NULLIF(p_timezone, ''),
        NULLIF(p_cpu_cores, 0),
        NULLIF(p_cpu_arch, ''),
        NULLIF(p_total_ram_gb, 0),
        NULLIF(p_screen_res, ''),
        NULLIF(p_connection_type, ''),
        NULLIF(LOWER(TRIM(p_friend_tag)), ''),
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
        device_model = COALESCE(EXCLUDED.device_model, device_installs.device_model),
        locale = COALESCE(EXCLUDED.locale, device_installs.locale),
        timezone = COALESCE(EXCLUDED.timezone, device_installs.timezone),
        cpu_cores = COALESCE(EXCLUDED.cpu_cores, device_installs.cpu_cores),
        cpu_arch = COALESCE(EXCLUDED.cpu_arch, device_installs.cpu_arch),
        total_ram_gb = COALESCE(EXCLUDED.total_ram_gb, device_installs.total_ram_gb),
        screen_res = COALESCE(EXCLUDED.screen_res, device_installs.screen_res),
        connection_type = COALESCE(EXCLUDED.connection_type, device_installs.connection_type),
        friend_tag = COALESCE(NULLIF(EXCLUDED.friend_tag, ''), device_installs.friend_tag)
    RETURNING (xmax = 0) INTO v_is_new;

    RETURN jsonb_build_object(
        'status', 'ok',
        'is_new', v_is_new,
        'server_time', NOW()
    );
END;
$$;

-- 3. Analytics Aggregation Views for Maintainer Dashboard
CREATE OR REPLACE VIEW v_device_stats AS
SELECT
    COUNT(*) AS total_unique_devices,
    COUNT(*) FILTER (WHERE device_type = 'Desktop PC') AS desktop_pcs,
    COUNT(*) FILTER (WHERE device_type = 'Laptop') AS laptops,
    COUNT(*) FILTER (WHERE device_type = 'Android') AS android_devices,
    COUNT(*) FILTER (WHERE device_type NOT IN ('Desktop PC', 'Laptop', 'Android')) AS other_devices,
    COUNT(*) FILTER (WHERE friend_tag IS NOT NULL AND friend_tag <> '') AS identified_friends_count,
    COUNT(*) FILTER (WHERE last_seen_at >= NOW() - INTERVAL '7 days') AS active_last_7_days,
    COUNT(*) FILTER (WHERE last_seen_at >= NOW() - INTERVAL '30 days') AS active_last_30_days,
    ROUND(AVG(total_ram_gb), 1) AS avg_ram_gb,
    ROUND(AVG(cpu_cores), 1) AS avg_cpu_cores
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

CREATE OR REPLACE VIEW v_friend_installs AS
SELECT
    friend_tag,
    device_type,
    os_name,
    device_model,
    locale,
    timezone,
    first_seen_at,
    last_seen_at,
    heartbeat_count
FROM device_installs
WHERE friend_tag IS NOT NULL AND friend_tag <> ''
ORDER BY last_seen_at DESC;

CREATE OR REPLACE VIEW v_geo_demographics AS
SELECT
    COALESCE(locale, 'Unknown') AS locale,
    COALESCE(timezone, 'Unknown') AS timezone,
    COUNT(*) AS count,
    ROUND(COUNT(*) * 100.0 / NULLIF((SELECT COUNT(*) FROM device_installs), 0), 2) AS percentage
FROM device_installs
GROUP BY locale, timezone
ORDER BY count DESC;

CREATE OR REPLACE VIEW v_hardware_specs AS
SELECT
    COALESCE(cpu_arch, 'Unknown') AS cpu_arch,
    COALESCE(screen_res, 'Unknown') AS screen_res,
    COALESCE(connection_type, 'Unknown') AS connection_type,
    COUNT(*) AS count,
    ROUND(COUNT(*) * 100.0 / NULLIF((SELECT COUNT(*) FROM device_installs), 0), 2) AS percentage
FROM device_installs
GROUP BY cpu_arch, screen_res, connection_type
ORDER BY count DESC;

CREATE OR REPLACE VIEW v_version_breakdown AS
SELECT
    app_version,
    COUNT(*) AS install_count,
    ROUND(COUNT(*) * 100.0 / NULLIF((SELECT COUNT(*) FROM device_installs), 0), 2) AS percentage
FROM device_installs
GROUP BY app_version
ORDER BY install_count DESC;
