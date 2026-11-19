# Installs the sample applications into the streaming user's profile without
# elevation. The agent runs this in a PowerShell window at the start of a session.
#
# The streaming user is not an administrator, so neither vendor installer can run.
# GnuCash is unpacked from its Inno Setup installer with innoextract, and LibreOffice
# with an MSI administrative install, which only copies files.
[CmdletBinding()]
param(
    [ValidateSet('GnuCash', 'LibreOffice')]
    [string[]]$Apps = @('GnuCash', 'LibreOffice'),
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'SampleApps')
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
# The window's lower edge sits behind the taskbar, so the agent reads the last lines only if they start at the top.
Clear-Host
# Printed word for word on every run that includes GnuCash, so customers know the sample uses it. The tests pin the text.
if ($Apps -contains 'GnuCash') {
    Write-Host 'This demo uses GnuCash, licensed under GPL-2.0, downloaded directly from the official GnuCash project at install time into your AWS account; AWS does not distribute, host, or modify GnuCash. License and source: https://www.gnucash.org'
}

# Versions are pinned so every run gets the same bits. The hashes match the
# publishers' own checksums, except innoextract, which publishes only a GPG signature.
# Its hash is of the zip whose signature verified against the publisher's key 28555A66D7E1DEC9.
$artifacts = @{
    GnuCash = @{
        Url    = 'https://github.com/Gnucash/gnucash/releases/download/5.17/gnucash-5.17.setup.exe'
        Sha256 = 'A3E8049755E536F647640762A483EBE1B6C79CC50CC81A746FA64A404E98D271'
        File   = 'gnucash-5.17.setup.exe'
    }
    InnoExtract = @{
        Url    = 'https://github.com/dscharrer/innoextract/releases/download/1.9/innoextract-1.9-windows.zip'
        Sha256 = '6989342C9B026A00A72A38F23B62A8E6A22CC5DE69805CF47D68AC2FEC993065'
        File   = 'innoextract-1.9-windows.zip'
    }
    LibreOffice = @{
        Url    = 'https://download.documentfoundation.org/libreoffice/stable/26.8.1/win/x86_64/LibreOffice_26.8.1_Win_x86-64.msi'
        # stable/ holds only current releases. Once a newer one ships, this release moves to the
        # archive under its full version number, with the same bytes and hash.
        FallbackUrl = 'https://downloadarchive.documentfoundation.org/libreoffice/old/26.8.1.1/win/x86_64/LibreOffice_26.8.1.1_Win_x86-64.msi'
        Sha256 = 'C6298B10CFA1748BCBEDAD94C62CE771E240E5021BFD6D7A967CD571B04B5312'
        File   = 'LibreOffice_26.8.1_Win_x86-64.msi'
    }
}

$downloads = Join-Path $env:TEMP 'sample-setup'
$log = Join-Path $env:TEMP 'sample-setup.log'
New-Item -ItemType Directory -Force $downloads, $InstallRoot | Out-Null

function Write-Step($message) {
    $line = "$(Get-Date -Format 'HH:mm:ss') $message"
    Write-Host $line
    $line | Out-File $log -Append -Encoding UTF8
}

function Test-Artifact($name) {
    $path = Join-Path $downloads $artifacts[$name].File
    (Test-Path $path) -and (Get-FileHash $path -Algorithm SHA256).Hash -eq $artifacts[$name].Sha256
}

# Invoke-WebRequest stalled at 0 bytes on the LibreOffice MSI in testing, so curl.exe (built
# into Windows Server 2025) aborts and retries. The speed limit alone missed a transfer that sat
# at 0 bytes for 10 minutes, so each attempt is capped too.
# The LibreOffice URL redirects to a mirror picked per request, and one ran at 1 MB/s, so a first
# try drops any mirror under 2 MB/s after 15 seconds and the retry lands on another.
$fastMirror = @('--retry', '4', '--speed-limit', '2000000', '--speed-time', '15', '--max-time', '240')
$anyMirror = @('--retry', '2', '--speed-limit', '1024', '--speed-time', '60', '--max-time', '900')

function Start-Curl($a, [string[]]$limits, [string]$url) {
    if (-not $url) { $url = $a.Url }
    $p = Start-Process curl.exe -NoNewWindow -PassThru -ArgumentList (@(
        '-fsSL', '--retry-delay', '2', '--connect-timeout', '20') + $limits + @(
        '-o', "`"$(Join-Path $downloads $a.File)`"", $url))
    # Without the cached handle, ExitCode reads as empty after the process exits.
    $null = $p.Handle
    $p
}

function Start-Download($name) {
    if (Test-Artifact $name) { return $null }
    $a = $artifacts[$name]
    Write-Step "Downloading $($a.File)"
    Start-Curl $a $fastMirror
}

function Get-Artifact($name) {
    $a = $artifacts[$name]
    $path = Join-Path $downloads $a.File
    $p = if ($pending.ContainsKey($name)) { $pending[$name] } else { Start-Download $name }
    if ($p) {
        $p.WaitForExit()
        if ($p.ExitCode -ne 0) {
            Write-Step "Mirrors were slow, retrying $($a.File) without the speed limit"
            $p = Start-Curl $a $anyMirror
            $p.WaitForExit()
        }
        if ($p.ExitCode -ne 0 -and $a.FallbackUrl) {
            Write-Step "Downloading $($a.File) from the publisher's archive"
            $p = Start-Curl $a $anyMirror $a.FallbackUrl
            $p.WaitForExit()
        }
        if ($p.ExitCode -ne 0) { throw "Download of $($a.File) failed (curl exit $($p.ExitCode))" }
        $hash = (Get-FileHash $path -Algorithm SHA256).Hash
        if ($hash -ne $a.Sha256) {
            Remove-Item $path -Force
            throw "Checksum mismatch for $($a.File): expected $($a.Sha256), got $hash"
        }
    }
    Unblock-File $path
    $path
}

function Add-Shortcuts($label, $target) {
    $shell = New-Object -ComObject WScript.Shell
    foreach ($folder in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
        $shortcut = $shell.CreateShortcut((Join-Path $folder "$label.lnk"))
        $shortcut.TargetPath = $target
        $shortcut.WorkingDirectory = Split-Path $target
        $shortcut.Save()
    }
}

# Per-user file associations, so double-clicking a sample file opens the
# unpacked application. HKCU is writable without admin.
function Register-FileTypes($progId, $target, [string[]]$extensions) {
    $classes = 'HKCU:\Software\Classes'
    $command = Join-Path $classes "$progId\shell\open\command"
    New-Item -Path $command -Force | Out-Null
    Set-Item -Path $command -Value "`"$target`" `"%1`""
    foreach ($ext in $extensions) {
        $key = Join-Path $classes $ext
        New-Item -Path $key -Force | Out-Null
        Set-Item -Path $key -Value $progId
    }
}

# GnuCash keeps GSettings in the registry on Windows, booleans as DWORDs.
function Skip-GnuCashFirstRun {
    $root = 'HKCU:\Software\GSettings\org\gnucash\GnuCash\dialogs'
    # The due-invoice reminder would pop up over a sample book that holds posted invoices.
    foreach ($entry in @(
            @('new-user', 'first-startup'),
            @('tip-of-the-day', 'show-at-startup'),
            @('totd', 'show-at-startup'),
            @('business\invoice', 'notify-when-due'))) {
        $key = Join-Path $root $entry[0]
        New-Item -Path $key -Force | Out-Null
        New-ItemProperty -Path $key -Name $entry[1] -PropertyType DWord -Value 0 -Force | Out-Null
    }
}

function Skip-LibreOfficeFirstRun {
    $profileDir = Join-Path $env:APPDATA 'LibreOffice\4\user'
    $file = Join-Path $profileDir 'registrymodifications.xcu'
    if (Test-Path $file) { return }
    New-Item -ItemType Directory -Force $profileDir | Out-Null
    @'
<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<item oor:path="/org.openoffice.Setup/Product"><prop oor:name="WhatsNew" oor:op="fuse"><value>false</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Misc"><prop oor:name="ShowTipOfTheDay" oor:op="fuse"><value>false</value></prop></item>
<item oor:path="/org.openoffice.Office.Jobs/Jobs/org.openoffice.Office.Jobs:Job['UpdateCheck']/Arguments"><prop oor:name="AutoCheckEnabled" oor:op="fuse"><value>false</value></prop></item>
</oor:items>
'@ | Set-Content -Path $file -Encoding UTF8
}

function Install-GnuCash {
    $exe = Join-Path $InstallRoot 'GnuCash\app\bin\gnucash.exe'
    if (-not (Test-Path $exe)) {
        $zip = Get-Artifact 'InnoExtract'
        $tool = Join-Path $downloads 'innoextract'
        Expand-Archive $zip $tool -Force
        $installer = Get-Artifact 'GnuCash'
        Write-Step 'Unpacking GnuCash'
        & (Join-Path $tool 'innoextract.exe') --silent --output-dir (Join-Path $InstallRoot 'GnuCash') $installer | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "innoextract exited with $LASTEXITCODE" }
        if (-not (Test-Path $exe)) { throw "GnuCash unpacked but $exe is missing" }
    }
    Skip-GnuCashFirstRun
    Add-Shortcuts 'GnuCash' $exe
    Register-FileTypes 'SampleApps.GnuCash' $exe @('.gnucash')
    $exe
}

function Install-LibreOffice {
    $target = Join-Path $InstallRoot 'LibreOffice'
    $exe = $libreOfficeExe
    if (-not (Test-Path $exe)) {
        $msi = Get-Artifact 'LibreOffice'
        Write-Step 'Unpacking LibreOffice (about 2 minutes)'
        $p = Start-Process msiexec.exe -Wait -PassThru -ArgumentList @(
            '/a', "`"$msi`"", '/qn', "TARGETDIR=`"$target`""
        )
        if ($p.ExitCode -ne 0) { throw "msiexec /a exited with $($p.ExitCode)" }
        if (-not (Test-Path $exe)) { throw "LibreOffice unpacked but $exe is missing" }
    }
    Skip-LibreOfficeFirstRun
    Add-Shortcuts 'LibreOffice Calc' $exe
    Register-FileTypes 'SampleApps.Calc' $exe @('.xlsx', '.xls', '.csv', '.ods')
    $exe
}

# The LibreOffice MSI is the slowest download, so it runs while GnuCash is fetched and unpacked.
$libreOfficeExe = Join-Path $InstallRoot 'LibreOffice\program\scalc.exe'
$pending = @{}
if ($Apps -contains 'LibreOffice' -and -not (Test-Path $libreOfficeExe)) {
    # If this fails, Install-LibreOffice retries the download and reports the error.
    try { $pending['LibreOffice'] = Start-Download 'LibreOffice' } catch { }
}

$failed = $false
foreach ($app in $Apps) {
    try {
        $path = & "Install-$app"
        Write-Step "READY $app $path"
    } catch {
        $failed = $true
        Write-Step "FAILED $app $($_.Exception.Message)"
    }
}

if ($failed) {
    Write-Step "Setup incomplete. Log: $log"
    exit 1
}
Remove-Item $downloads -Recurse -Force -ErrorAction SilentlyContinue
Write-Step 'Setup complete'
