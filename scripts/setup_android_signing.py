#!/usr/bin/env python3
"""
Interactive Android Release Keystore Generator & GitHub Actions Signing Helper.

Creates a production 4096-bit RSA Android signing keystore (valid for 10,000 days),
writes gitignored android/keystore.properties for local builds, and optionally pushes
the 4 required signing secrets directly to GitHub Actions via `gh secret set`.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
ANDROID_DIR = ROOT_DIR / "android"
DEFAULT_KEYSTORE = ANDROID_DIR / "release-keystore.jks"
DEFAULT_PROPS = ANDROID_DIR / "keystore.properties"
APP_CONFIG_FILE = ROOT_DIR / "app_config.json"


def load_repo_slug() -> str:
    if APP_CONFIG_FILE.exists():
        try:
            cfg = json.loads(APP_CONFIG_FILE.read_text(encoding="utf-8"))
            owner = cfg.get("github_owner")
            repo = cfg.get("github_repo")
            if owner and repo:
                return f"{owner}/{repo}"
        except Exception:
            pass
    return "Antony-Gh/Universal-Donwloader"


def find_keytool() -> str:
    found = shutil.which("keytool")
    if found:
        return found
    raise RuntimeError(
        "JDK 'keytool' was not found on PATH. Install JDK 17+ (e.g. Microsoft OpenJDK 17 or Temurin 17)."
    )


def prompt_password(label: str, min_len: int = 6) -> str:
    while True:
        pw = getpass.getpass(f"{label} (min {min_len} chars): ").strip()
        if len(pw) < min_len:
            print(f"  Password must be at least {min_len} characters.")
            continue
        confirm = getpass.getpass(f"Confirm {label}: ").strip()
        if pw != confirm:
            print("  Passwords did not match. Try again.")
            continue
        return pw


def generate_keystore(
    keystore_path: Path,
    alias: str,
    store_password: str,
    key_password: str,
    dname: str,
    validity_days: int = 10000,
) -> None:
    keytool = find_keytool()
    keystore_path.parent.mkdir(parents=True, exist_ok=True)
    if keystore_path.exists():
        raise FileExistsError(
            f"Keystore already exists at {keystore_path}. "
            "Use --from-existing to reuse it, or pass a different --keystore path."
        )

    cmd = [
        keytool,
        "-genkeypair",
        "-v",
        "-keystore", str(keystore_path),
        "-storetype", "PKCS12",
        "-keyalg", "RSA",
        "-keysize", "4096",
        "-validity", str(validity_days),
        "-alias", alias,
        "-storepass", store_password,
        "-keypass", key_password,
        "-dname", dname,
    ]
    proc = subprocess.run(cmd, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"keytool failed with exit code {proc.returncode}")


def print_certificate_fingerprint(keystore_path: Path, alias: str, store_password: str) -> None:
    keytool = find_keytool()
    proc = subprocess.run(
        [
            keytool,
            "-list",
            "-v",
            "-keystore", str(keystore_path),
            "-alias", alias,
            "-storepass", store_password,
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        for line in proc.stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith(("SHA1:", "SHA256:", "Valid from:", "Owner:")):
                print(f"  {stripped}")


def write_keystore_properties(props_path: Path, keystore_path: Path, alias: str, store_password: str, key_password: str) -> None:
    try:
        rel_store = keystore_path.resolve().relative_to(ANDROID_DIR.resolve()).as_posix()
    except ValueError:
        rel_store = keystore_path.resolve().as_posix()

    content = (
        "# Auto-generated local Android release signing config (GITIGNORED - DO NOT COMMIT)\n"
        f"storeFile={rel_store}\n"
        f"storePassword={store_password}\n"
        f"keyAlias={alias}\n"
        f"keyPassword={key_password}\n"
    )
    props_path.write_text(content, encoding="utf-8")


def upload_github_secrets(repo_slug: str, b64_keystore: str, store_password: str, alias: str, key_password: str) -> bool:
    if not shutil.which("gh"):
        print("  [!] GitHub CLI ('gh') is not installed. Skipping automatic secret upload.")
        return False

    auth = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    if auth.returncode != 0:
        print("  [!] GitHub CLI is not authenticated. Run 'gh auth login' first or paste secrets manually.")
        return False

    secrets = {
        "ANDROID_KEYSTORE_BASE64": b64_keystore,
        "ANDROID_KEYSTORE_PASSWORD": store_password,
        "ANDROID_KEY_ALIAS": alias,
        "ANDROID_KEY_PASSWORD": key_password,
    }
    for name, value in secrets.items():
        proc = subprocess.run(
            ["gh", "secret", "set", name, "--repo", repo_slug],
            input=value,
            text=True,
            capture_output=True,
        )
        if proc.returncode != 0:
            print(f"  [✗] Failed to set {name}: {proc.stderr.strip()}")
            return False
        print(f"  [✓] Uploaded GitHub secret: {name}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Set up Android release signing keystore & GitHub Actions secrets")
    parser.add_argument("--keystore", type=Path, default=DEFAULT_KEYSTORE, help="Path for release .jks keystore")
    parser.add_argument("--alias", default="universal-downloader", help="Key alias inside the keystore")
    parser.add_argument("--cn", default="Universal Media Downloader", help="Certificate Common Name (CN)")
    parser.add_argument("--org", default="Antony-Gh", help="Certificate Organization (O)")
    parser.add_argument("--country", default="US", help="2-letter Country Code (C)")
    parser.add_argument("--from-existing", action="store_true", help="Configure signing from an existing keystore file")
    parser.add_argument("--upload-gh-secrets", action="store_true", help="Upload the 4 signing secrets to GitHub via gh CLI")
    parser.add_argument(
        "--export-secrets-file",
        action="store_true",
        help="Write Base64 + secret values to gitignored android-signing-secrets.txt for manual copy-paste into GitHub",
    )
    args = parser.parse_args()

    repo_slug = load_repo_slug()
    print("=" * 68)
    print("  Universal Media Downloader — Android Release Signing Setup")
    print("=" * 68)

    try:
        find_keytool()
    except RuntimeError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    if args.from_existing:
        if not args.keystore.exists():
            print(f"[ERROR] Existing keystore not found: {args.keystore}", file=sys.stderr)
            return 1
        store_password = getpass.getpass("Existing keystore password: ").strip()
        key_password = getpass.getpass("Existing key password (Enter if same as keystore): ").strip() or store_password
    else:
        print(f"\nKeystore path : {args.keystore}")
        print(f"Key alias     : {args.alias}")
        print("IMPORTANT: Back up the generated .jks file and password in a safe place!")
        print("If you lose this key, users cannot update over previously signed APKs.\n")

        store_password = prompt_password("Keystore password")
        same_pw = input("Use the same password for the key alias? [Y/n]: ").strip().lower()
        key_password = store_password if same_pw in ("", "y", "yes") else prompt_password("Key password")

        dname = f"CN={args.cn}, O={args.org}, C={args.country}"
        print("\nGenerating 4096-bit RSA Android signing keystore...")
        try:
            generate_keystore(args.keystore, args.alias, store_password, key_password, dname)
        except Exception as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1
        print(f"[✓] Created release keystore: {args.keystore}")

    print("\nCertificate Fingerprint:")
    print_certificate_fingerprint(args.keystore, args.alias, store_password)

    write_keystore_properties(DEFAULT_PROPS, args.keystore, args.alias, store_password, key_password)
    print(f"\n[✓] Wrote local Gradle config: {DEFAULT_PROPS} (gitignored)")

    b64_keystore = base64.b64encode(args.keystore.read_bytes()).decode("ascii")

    uploaded = False
    if args.upload_gh_secrets:
        print(f"\nUploading signing secrets to GitHub repository ({repo_slug})...")
        uploaded = upload_github_secrets(repo_slug, b64_keystore, store_password, args.alias, key_password)

    if args.export_secrets_file:
        out_txt = ROOT_DIR / "android-signing-secrets.txt"
        out_txt.write_text(
            f"# GitHub Repository Secrets for https://github.com/{repo_slug}/settings/secrets/actions\n"
            f"# DELETE THIS FILE after pasting the secrets into GitHub!\n\n"
            f"ANDROID_KEY_ALIAS={args.alias}\n"
            f"ANDROID_KEYSTORE_PASSWORD={store_password}\n"
            f"ANDROID_KEY_PASSWORD={key_password}\n"
            f"ANDROID_KEYSTORE_BASE64={b64_keystore}\n",
            encoding="utf-8",
        )
        print(f"[✓] Exported secrets to gitignored file: {out_txt}")
        print("    Remember to DELETE android-signing-secrets.txt after adding them to GitHub!")

    if not uploaded:
        print(f"\nNext step — add these 4 secrets to GitHub Actions:")
        print(f"  https://github.com/{repo_slug}/settings/secrets/actions\n")
        print("  1. ANDROID_KEYSTORE_BASE64    (Base64 of android/release-keystore.jks)")
        print("  2. ANDROID_KEYSTORE_PASSWORD  (your keystore password)")
        print(f"  3. ANDROID_KEY_ALIAS          ({args.alias})")
        print("  4. ANDROID_KEY_PASSWORD       (your key password)")
        print("\nTip: Re-run with --upload-gh-secrets (if 'gh' is logged in) or --export-secrets-file.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
