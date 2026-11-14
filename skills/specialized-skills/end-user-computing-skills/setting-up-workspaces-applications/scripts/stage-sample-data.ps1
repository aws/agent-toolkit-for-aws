# Copies a workflow's input files from the Home Folder to the paths its prompt uses,
# opens each of them on screen, then opens the book in the unpacked GnuCash. Run it after
# setup-sample.ps1.
[CmdletBinding()]
param(
    [string]$Source = (Join-Path $env:USERPROFILE 'My Files\Home Folder'),
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'SampleApps'),
    # Which app shows the purchase order.
    [ValidateSet('Edge', 'LibreOffice')]
    [string]$PdfViewer = 'Edge'
)

$ErrorActionPreference = 'Stop'
# The window's lower edge sits behind the taskbar, so the agent reads the last lines only if they start at the top.
Clear-Host

# Closes the app's windows first, so a browser does not offer to restore pages next time.
function Close-App($name) {
    Get-Process $name -ErrorAction SilentlyContinue |
        Where-Object MainWindowHandle -ne 0 | ForEach-Object { [void]$_.CloseMainWindow() }
    for ($i = 0; $i -lt 10 -and (Get-Process $name -ErrorAction SilentlyContinue | Where-Object MainWindowHandle -ne 0); $i++) {
        Start-Sleep -Seconds 1
    }
    Get-Process $name -ErrorAction SilentlyContinue | Stop-Process -Force
}
$book = Join-Path $env:USERPROFILE 'Documents\Wendlecote.gnucash'
$orders = Join-Path $env:USERPROFILE 'purchase_orders'
$gnucash = Join-Path $InstallRoot 'GnuCash\app\bin\gnucash.exe'

if (-not (Test-Path $gnucash)) { throw "GnuCash is not unpacked yet. Run setup-sample.ps1 first." }
$bookSource = Join-Path $Source 'Wendlecote.gnucash'
if (-not (Test-Path $bookSource)) { throw "Wendlecote.gnucash is not in $Source" }

# A running GnuCash holds a lock on the book, and a copy over it would be lost. The other
# apps are closed so each workflow starts on a clean desktop, with the taskbar icons where
# the workflow skill expects them.
foreach ($app in 'gnucash', 'msedge', 'notepad', 'soffice', 'soffice.bin') { Close-App $app }
Start-Sleep -Seconds 2
Remove-Item "$book.LCK", "$book.LNK" -Force -ErrorAction SilentlyContinue
Copy-Item $bookSource $book -Force
Write-Host "STAGED $book"

New-Item -ItemType Directory -Force $orders | Out-Null
$staged = @()
# The sample's purchase order is an HTML page, which Edge shows like a printed document.
foreach ($order in Get-ChildItem $Source -File | Where-Object { $_.Extension -in '.html', '.pdf' }) {
    Copy-Item $order.FullName $orders -Force
    $staged += Join-Path $orders $order.Name
    Write-Host "STAGED $(Join-Path $orders $order.Name)"
}
$csvs = @()
foreach ($csv in Get-ChildItem $Source -Filter *.csv) {
    Copy-Item $csv.FullName $env:USERPROFILE -Force
    $csvs += Join-Path $env:USERPROFILE $csv.Name
    Write-Host "STAGED $(Join-Path $env:USERPROFILE $csv.Name)"
}
Remove-Item (Join-Path $env:USERPROFILE 'refund_decisions.txt') -Force -ErrorAction SilentlyContinue

# Every input file is opened on screen, so the agent reads it there instead of launching an
# app itself. Edge shows several first-run pages in every new session when launched without
# these switches, and the policy that hides them needs admin rights.
foreach ($path in $staged) {
    if ($PdfViewer -eq 'Edge') {
        Start-Process msedge -ArgumentList '--no-first-run', '--disable-features=WelcomePage', "`"$path`""
    } else {
        Start-Process (Join-Path $InstallRoot 'LibreOffice\program\soffice.exe') -ArgumentList '--nologo', '--view', "`"$path`""
    }
    Write-Host "OPENED $path"
}
foreach ($path in $csvs) {
    Start-Process notepad -ArgumentList "`"$path`""
    Write-Host "OPENED $path"
}

Start-Process $gnucash -ArgumentList "`"$book`""
Start-Sleep -Seconds 20
Write-Host 'Book open'
# Closes this PowerShell window, so GnuCash is in front and the taskbar matches what the
# workflow skill expects. A failure above stops the script first, leaving the error on screen.
Stop-Process -Id $PID
