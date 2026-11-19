# Windows Code Signing & SmartScreen Reputation Guide

This guide explains how code signing works for Universal Media Downloader, how Microsoft SmartScreen reputation is established, and how to eliminate the *"Windows protected your PC — Unknown publisher"* blue dialog.

---

## 1. Why Does SmartScreen Appear?

When users download `UniversalDownloader.exe` or `UniversalDownloader-Setup-x64.msi` via web browsers, Windows marks the file with a **Mark of the Web (MOTW)** zone identifier.

When executed, Windows Defender SmartScreen checks:

1. **Digital Signature**: Is the binary signed with a recognized Authenticode digital certificate?
   - **Unsigned binary**: Always triggers the scary *"Unknown publisher"* warning screen.
   - **Self-signed binary**: Triggers the warning unless the user has manually trusted the root certificate.
   - **Public CA Certificate (Standard OV / EV / Azure Trusted Signing / SignPath)**: Validates publisher identity and builds reputation.
2. **Reputation Score**: SmartScreen uses algorithmic telemetry. Once enough Windows users download and run a signed binary from a recognized certificate without security alerts, SmartScreen automatically silences the prompt worldwide for all subsequent users.

---

## 2. Recommended Signing Solutions for Open-Source

### Option A: Free Open-Source Signing with SignPath.io (Recommended)

Microsoft and the .NET Foundation partner with **[SignPath.io](https://about.signpath.io/)** to provide **free, automated code signing certificates** for open-source GitHub projects.

1. Sign up at [about.signpath.io/open-source](https://about.signpath.io/open-source).
2. Connect this repository (`Antony-Gh/Universal-Donwloader`).
3. Add the official `signpath/github-action` step to `.github/workflows/release.yml`. Every release binary will be signed automatically by a trusted CA.

### Option B: Microsoft Azure Trusted Signing

Microsoft's cloud-native code signing service costs ~$10/month and provides immediate SmartScreen trust without physical hardware tokens (HSM).

- Integrated with Azure Identity and GitHub Actions (`azure/trusted-signing-action`).

### Option C: Traditional Standard OV or EV Certificate (.PFX)

If you possess a standard code signing `.pfx` certificate:

1. Encode the `.pfx` file as Base64:

   ```powershell
   [Convert]::ToBase64String([IO.File]::ReadAllBytes("certificate.pfx"))
   ```

2. In GitHub repository **Settings -> Secrets and variables -> Actions**, add:
   - `WINDOWS_SIGNING_PFX`: The base64-encoded string.
   - `WINDOWS_SIGNING_PASSWORD`: Your private key password.

---

## 3. Local Signing with `sign_windows_binary.ps1`

We bundle an automated PowerShell script in `scripts/sign_windows_binary.ps1` that works with standard Windows SDK `signtool.exe`.

### A. Create a Self-Signed Certificate for Local Testing

```powershell
.\scripts\sign_windows_binary.ps1 -CreateSelfSigned
```

This generates a SHA256 Code Signing certificate in `Cert:\CurrentUser\My`.

### B. Sign an Executable or MSI

```powershell
# Using an explicit PFX file
.\scripts\sign_windows_binary.ps1 -FilePath "releases\UniversalDownloader.exe" -PfxPath "cert.pfx" -PfxPassword "Secret123"

# Using a certificate already in the Windows Certificate Store
.\scripts\sign_windows_binary.ps1 -FilePath "releases\UniversalDownloader-Setup-x64.msi" -Thumbprint "ABC123456789DEF..."
```

### C. Verify an Existing Signature

```powershell
.\scripts\sign_windows_binary.ps1 -FilePath "releases\UniversalDownloader.exe" -VerifyOnly
```

---

## 4. Summary of Authenticode Parameters

The script automatically applies recommended Microsoft security parameters:

- **Hashing**: SHA-256 (`/fd SHA256`)
- **Timestamping**: RFC 3161 with SHA-256 digest (`/tr http://timestamp.digicert.com /td SHA256`)
- **Description & URL**: Embedded application metadata (`/d "Universal Media Downloader" /du "https://github.com/Antony-Gh/Universal-Donwloader"`)
