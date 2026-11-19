<#
.SYNOPSIS
    Automated Authenticode code signing script for Universal Media Downloader Windows binaries (.exe and .msi).

.DESCRIPTION
    Signs Windows executables and MSI installers using signtool.exe with SHA256 Authenticode
    and RFC 3161 timestamping (DigiCert / Sectigo). Also supports generating development
    self-signed certificates for testing SmartScreen and installer behaviors.

.PARAMETER FilePath
    Path to the .exe or .msi file to sign.

.PARAMETER PfxPath
    Path to a PKCS#12 (.pfx) code signing certificate file.

.PARAMETER PfxPassword
    Password for the .pfx certificate file (or use env:WINDOWS_SIGNING_PASSWORD).

.PARAMETER Thumbprint
    Certificate SHA1 thumbprint if using an installed certificate from Windows Cert Store.

.PARAMETER TimestampServer
    RFC 3161 Timestamp Authority URL. Default: http://timestamp.digicert.com

.PARAMETER CreateSelfSigned
    Creates a new self-signed Code Signing certificate in Cert:\CurrentUser\My for development.

.PARAMETER VerifyOnly
    Only verifies the Authenticode signature of the target binary.
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$FilePath,

    [string]$PfxPath,

    [string]$PfxPassword,

    [string]$Thumbprint,

    [string]$TimestampServer = "http://timestamp.digicert.com",

    [switch]$CreateSelfSigned,

    [switch]$VerifyOnly
)

function Find-SignTool {
    $found = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }

    $kitsRoots = @(
        "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe",
        "${env:ProgramFiles}\Windows Kits\10\bin\*\x64\signtool.exe",
        "${env:ProgramFiles(x86)}\Microsoft SDKs\Windows\*\bin\NETFX*\signtool.exe"
    )

    foreach ($pattern in $kitsRoots) {
        $tools = Get-ChildItem -Path $pattern -ErrorAction SilentlyContinue | Sort-Object FullName -Descending
        if ($tools) { return $tools[0].FullName }
    }
    return $null
}

if ($CreateSelfSigned) {
    Write-Host "Creating self-signed Code Signing certificate for developer testing..." -ForegroundColor Cyan
    $cert = New-SelfSignedCertificate `
        -Type CodeSigningCert `
        -Subject "CN=Universal Media Downloader Dev, O=Antony-Gh, OU=Development" `
        -CertStoreLocation "Cert:\CurrentUser\My" `
        -HashAlgorithm "SHA256" `
        -KeyLength 2048 `
        -NotAfter (Get-Date).AddYears(3)

    Write-Host "Certificate created with thumbprint: $($cert.Thumbprint)" -ForegroundColor Green
    Write-Host "To trust locally, export public key and import to 'Trusted Root Certification Authorities'."
    return
}

if (-not $FilePath) {
    Write-Error "Please provide a target file to sign: .\sign_windows_binary.ps1 -FilePath <path>"
    exit 1
}

$target = Resolve-Path $FilePath -ErrorAction SilentlyContinue
if (-not $target -or -not (Test-Path $target)) {
    Write-Error "Target file not found: $FilePath"
    exit 1
}

$signToolPath = Find-SignTool
if (-not $signToolPath) {
    Write-Error "signtool.exe not found. Please install the Windows 10/11 SDK or Visual Studio Build Tools."
    exit 1
}
Write-Host "Using SignTool: $signToolPath" -ForegroundColor DarkGray

if ($VerifyOnly) {
    Write-Host "Verifying signature of $target..." -ForegroundColor Cyan
    & $signToolPath verify /pa /v "$target"
    exit $LASTEXITCODE
}

# Resolve certificate parameters
$pfx = if ($PfxPath) { $PfxPath } else { $env:WINDOWS_SIGNING_PFX }
$pass = if ($PfxPassword) { $PfxPassword } else { $env:WINDOWS_SIGNING_PASSWORD }
$thumb = if ($Thumbprint) { $Thumbprint } else { $env:WINDOWS_SIGNING_THUMBPRINT }

$signArgs = @("sign", "/fd", "SHA256", "/d", "Universal Media Downloader", "/du", "https://github.com/Antony-Gh/Universal-Donwloader")

if ($TimestampServer) {
    $signArgs += @("/tr", $TimestampServer, "/td", "SHA256")
}

if ($pfx) {
    $signArgs += @("/f", "$pfx")
    if ($pass) {
        $signArgs += @("/p", "$pass")
    }
} elseif ($thumb) {
    $signArgs += @("/sha1", "$thumb", "/sm")
} else {
    # Auto-detect any available Code Signing certificate in current user store
    $devCert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($devCert) {
        Write-Host "Using detected Code Signing certificate: $($devCert.Subject) ($($devCert.Thumbprint))" -ForegroundColor Yellow
        $signArgs += @("/sha1", "$($devCert.Thumbprint)")
    } else {
        Write-Error "No signing certificate specified. Provide -PfxPath, -Thumbprint, or set WINDOWS_SIGNING_PFX environment variable."
        Write-Host "To create a free local certificate for testing, run:" -ForegroundColor Cyan
        Write-Host "  .\scripts\sign_windows_binary.ps1 -CreateSelfSigned"
        exit 1
    }
}

$signArgs += "$target"

Write-Host "Signing $target..." -ForegroundColor Cyan
& $signToolPath $signArgs

if ($LASTEXITCODE -eq 0) {
    Write-Host "Signature applied successfully!" -ForegroundColor Green
    Write-Host "Verifying signature..." -ForegroundColor DarkGray
    & $signToolPath verify /pa "$target"
} else {
    Write-Error "Code signing failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}
