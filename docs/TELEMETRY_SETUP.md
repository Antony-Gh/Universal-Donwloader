# Neon Serverless Postgres Telemetry & Analytics Setup

Universal Media Downloader includes an anonymous device telemetry system that enables the project maintainer to know:
1. **Total Unique Device Installations**
2. **Device Form Factor Breakdown**: Desktop PC vs. Laptop vs. Android
3. **Operating System Distribution**: Windows (11/10), Android, macOS, Linux
4. **App Version Adoption**: Active versions across the user base
5. **Combined GitHub Download Stats**: Release asset download counts (.exe, .msi, .apk)

---

## 🔒 Privacy Guarantee
* **Zero Personally Identifiable Information (PII)**: No IP addresses, usernames, MAC addresses, or machine names are stored.
* **Zero User Activity Logging**: No downloaded URLs, media titles, search terms, or paths are ever logged or sent.
* **Anonymous Installation UUID**: Each installation generates a cryptographically random UUIDv4 (`install_id`) stored locally in `~/.universal_downloader/device_id.json`.
* **Full Opt-Out Support**: Users can opt out anytime via:
  ```bash
  python downloader.py --no-telemetry <URL>
  # or environment variable:
  export UD_NO_TELEMETRY=1
  # or in config.json:
  { "telemetry_enabled": false }
  ```

---

## ⚡ 1-Minute Neon Setup

### 1. Create a Free Neon Account
1. Visit [neon.tech](https://neon.tech) and create a free serverless PostgreSQL database.
2. Create a project named `universal-downloader`.

### 2. Run the Schema Script
1. In the Neon Console, open the **SQL Editor**.
2. Copy and paste the contents of [`scripts/neon_schema.sql`](../scripts/neon_schema.sql).
3. Click **Run**. This creates:
   - `device_installs` table
   - `record_device_heartbeat(...)` stored function
   - `v_device_stats`, `v_device_breakdown`, and `v_version_breakdown` views.

### 3. Configure Client / Ingest Access
Neon provides an HTTP-based SQL API (`https://<project-endpoint>.neon.tech/sql`).

Set the following environment variables (or save in your `.env` file):
```env
# Your Neon HTTP endpoint or database connection string
NEON_DATABASE_URL=https://ep-rapid-sound-123456.us-east-2.aws.neon.tech/sql
# Role token or connection password (write-only ingest role recommended)
NEON_TELEMETRY_KEY=npg_your_neon_auth_token_here
```

---

## 📊 Viewing Analytics

Maintainers can view the consolidated analytics dashboard directly from the CLI:

```bash
# View combined GitHub releases download count + active device installs
python downloader.py --analytics

# View release assets download stats only from GitHub
python downloader.py --release-stats
```

Example CLI Output:
```text
================================================================================
Universal Media Downloader — Global Telemetry & Distribution Dashboard
================================================================================

📦 GITHUB RELEASE DOWNLOADS (Antony-Gh/Universal-Donwloader)
--------------------------------------------------------------------------------
Total Downloads:        14,820
  • Windows Executable (.exe / .msi):  8,450 (57.0%)
  • Android APK (.apk):                4,920 (33.2%)
  • Source & Linux Archives:           1,450 ( 9.8%)

💻 ACTIVE DEVICE INSTALLATIONS (Neon Serverless Postgres)
--------------------------------------------------------------------------------
Total Unique Installations: 3,420
Active (Past 30 Days):      2,810 (82.2%)
Active (Past 7 Days):       1,940 (56.7%)

Form Factor Breakdown:
  • Desktop PC:             1,710 (50.0%)
  • Laptop:                 1,026 (30.0%)
  • Android:                  684 (20.0%)

Top Operating Systems:
  1. Windows 11             1,620 (47.4%)
  2. Android 15               580 (17.0%)
  3. Windows 10               510 (14.9%)
  4. Ubuntu 24.04             420 (12.3%)
  5. macOS Sonoma             290 ( 8.5%)
================================================================================
```
