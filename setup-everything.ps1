<#
    Setup Everything - one-shot installer for Windows
    ==================================================

    Downloads, unpacks, and arranges everything needed to run a private
    server and its save editor, then launches both.

    BEFORE YOU RUN THIS, put these two files in the same folder as this
    script (normally C:\lunar):

        resource_dump_android.7z      the game assets, from #resources
        20240404193219.bin.e          the master data, from #resources

    Then right-click this file and choose "Run with PowerShell", or from a
    terminal:

        cd C:\lunar
        powershell -ExecutionPolicy Bypass -File .\setup-everything.ps1

    What it does NOT do: patch the game app. That runs in Google Colab in
    your browser, and the script prints the exact settings to paste in at
    the end.
#>

[CmdletBinding()]
param(
    # Use this address instead of auto-detecting.
    [string]$ServerIP,

    # Accept every default without asking.
    [switch]$Yes
)

$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'   # makes downloads far faster

$Root       = $PSScriptRoot
$TearDir    = Join-Path $Root 'lunar-tear'
$BaseDir    = Join-Path $Root 'lunar-base'
$AssetArchive = Join-Path $Root 'resource_dump_android.7z'

$GrpcPort = 8003
$CdnPort  = 8080
$AuthPort = 3000
$BasePort = 8888

# ---------------------------------------------------------------- output --

function Say($msg)  { Write-Host "[-] $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "[+] $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "[!] $msg" -ForegroundColor Yellow }
function Fail($msg) { Write-Host "[x] $msg" -ForegroundColor Red }

function Step($n, $of, $title) {
    Write-Host ""
    Write-Host "  ---- Step $n of $of : $title " -ForegroundColor White
    Write-Host ""
}

function Banner {
    Write-Host ""
    Write-Host "  =====================================================" -ForegroundColor DarkCyan
    Write-Host "            PRIVATE SERVER - FULL SETUP" -ForegroundColor White
    Write-Host "     server + save editor, downloaded and arranged" -ForegroundColor Gray
    Write-Host "  =====================================================" -ForegroundColor DarkCyan
    Write-Host ""
}

function AskYesNo($question, $defaultYes = $true) {
    if ($Yes) { Say "$question -> yes"; return $true }
    $hint = if ($defaultYes) { "[Y/n]" } else { "[y/N]" }
    $answer = (Read-Host "    $question $hint").Trim().ToLower()
    if ($answer -eq '') { return $defaultYes }
    return $answer -in @('y', 'yes')
}

function Die($msg) {
    Write-Host ""
    Fail $msg
    Write-Host ""
    Read-Host "Press Enter to close"
    exit 1
}

# ------------------------------------------------------------- utilities --

function Find-SevenZip {
    # 7-Zip rarely puts itself on PATH, so check the usual install spots.
    $candidates = @(
        "$env:ProgramFiles\7-Zip\7z.exe",
        "${env:ProgramFiles(x86)}\7-Zip\7z.exe",
        "$env:LOCALAPPDATA\Programs\7-Zip\7z.exe"
    )
    foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
    $onPath = Get-Command 7z.exe -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
    return $null
}

function Find-Python {
    # The py launcher is what python.org installs; prefer it. A bare
    # "python" may be the Microsoft Store stub, which only opens the Store.
    foreach ($cmd in @('py -3', 'python')) {
        $exe, $arg = $cmd.Split(' ', 2)
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        try {
            $check = if ($arg) { & $exe $arg '-c' 'import sys;print(sys.version_info>=(3,10))' }
                     else      { & $exe '-c' 'import sys;print(sys.version_info>=(3,10))' }
            if ($check -match 'True') { return $cmd }
        } catch { }
    }
    return $null
}

function Get-LocalIP {
    # Private addresses only: 192.168.x, 10.x, 172.16-31.x. Excludes
    # Tailscale (100.x), loopback, and virtual adapters from emulators.
    $candidates = Get-NetIPAddress -AddressFamily IPv4 |
        Where-Object {
            $_.IPAddress -match '^(192\.168\.|10\.|172\.(1[6-9]|2[0-9]|3[01])\.)' -and
            $_.InterfaceAlias -notmatch 'Loopback|BlueStacks|VirtualBox|VMware|Hyper-V|Nox|LDPlayer|MEmu|Tailscale'
        } |
        Sort-Object -Property InterfaceMetric

    if ($candidates) { return $candidates[0].IPAddress }
    return $null
}

function Get-LatestAsset($repo, $pattern) {
    $api = "https://api.github.com/repos/$repo/releases/latest"
    try {
        $release = Invoke-RestMethod -Uri $api -Headers @{ 'User-Agent' = 'setup-script' }
    } catch {
        return $null
    }
    $asset = $release.assets | Where-Object { $_.name -like $pattern } | Select-Object -First 1
    if (-not $asset) { return $null }
    return [pscustomobject]@{
        Name    = $asset.name
        Url     = $asset.browser_download_url
        Version = $release.tag_name
    }
}

function Download($url, $destination, $label) {
    Say "Downloading $label ..."
    try {
        Invoke-WebRequest -Uri $url -OutFile $destination -UseBasicParsing
    } catch {
        Die "Could not download $label. Check your internet connection.`n    $($_.Exception.Message)"
    }
    $mb = [math]::Round((Get-Item $destination).Length / 1MB, 1)
    Ok "$label downloaded ($mb MB)"
}

function Add-PlatformFolders($revisionsRoot) {
    # Each revision's contents must sit inside an "android" subfolder. The
    # archive does not include that level, so add it -- skipping "android"
    # itself so it cannot be moved into itself.
    $folders = Get-ChildItem $revisionsRoot -Directory
    $i = 0
    foreach ($folder in $folders) {
        $i++
        if ($folders.Count -gt 10 -and ($i % 50 -eq 0)) {
            Say "  arranged $i of $($folders.Count) revisions ..."
        }
        $android = Join-Path $folder.FullName 'android'
        if (-not (Test-Path $android)) {
            New-Item -ItemType Directory -Path $android -Force | Out-Null
        }
        Get-ChildItem $folder.FullName -Force |
            Where-Object { $_.Name -ne 'android' } |
            ForEach-Object { Move-Item $_.FullName $android -Force }
    }
}

# =========================================================== START HERE ====

Banner
Say "Working folder: $Root"

# --------------------------------------------------- Step 1: check inputs --

Step 1 8 "Checking what you have"

$masterData = Get-ChildItem $Root -Filter '*.bin.e' -File | Select-Object -First 1

if (-not (Test-Path $AssetArchive)) {
    Die @"
Missing: resource_dump_android.7z

Put it in $Root and run this again.
Get it from the #resources channel: https://discord.com/invite/MZAf5aVkJG
"@
}
Ok "Found resource_dump_android.7z ($([math]::Round((Get-Item $AssetArchive).Length/1GB,1)) GB)"

if (-not $masterData) {
    Die @"
Missing: the master data file (something ending in .bin.e)

Put it in $Root and run this again.
The link is in #resources and points to MEGA -- download it in your browser.
"@
}
Ok "Found master data: $($masterData.Name)"

$sevenZip = Find-SevenZip
if (-not $sevenZip) {
    Die @"
7-Zip is not installed, and it is needed to unpack the game assets.

Install it from https://www.7-zip.org then run this again.
"@
}
Ok "Found 7-Zip"

$python = Find-Python
if (-not $python) {
    Warn "No Python 3.10 or newer found."
    Warn "The server will still work, but the save editor needs it."
    Write-Host ""
    Write-Host "    Install from https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "    Tick 'Add python.exe to PATH' during install." -ForegroundColor Yellow
    Write-Host "    Do NOT use the Microsoft Store version." -ForegroundColor Yellow
    Write-Host ""
    if (-not (AskYesNo "Carry on without the save editor?" $false)) {
        Die "Install Python, then run this again."
    }
} else {
    Ok "Found Python ($python)"
}

$freeGB = [math]::Round((Get-PSDrive -Name $Root.Substring(0,1)).Free / 1GB, 1)
Say "Free space on drive $($Root.Substring(0,1)): $freeGB GB"
# The assets unpack to ~48 GB, and the archive stays on disk while it does.
if ($freeGB -lt 55) {
    Die "Not enough free space: $freeGB GB. The assets unpack to about 48 GB, so you need roughly 65 GB free."
}
if ($freeGB -lt 65) {
    Warn "Only $freeGB GB free. The assets need about 48 GB unpacked, plus room for the archive."
    if (-not (AskYesNo "Continue anyway?" $false)) { Die "Free up some space and run this again." }
}

# ------------------------------------------------------ Step 2: questions --

Step 2 8 "A few questions"

if (-not $ServerIP) {
    $detected = Get-LocalIP
    if ($detected) {
        Ok "Detected this PC's local address: $detected"
        if (-not (AskYesNo "Use $detected ?" $true)) {
            $ServerIP = (Read-Host "    Enter the address to use").Trim()
        } else {
            $ServerIP = $detected
        }
    } else {
        Warn "Could not detect a local address automatically."
        Write-Host "    Run 'ipconfig' in another window and look for IPv4 Address." -ForegroundColor Gray
        $ServerIP = (Read-Host "    Enter this PC's local address").Trim()
    }
}

if ($ServerIP -notmatch '^\d{1,3}(\.\d{1,3}){3}$') {
    Die "'$ServerIP' does not look like an IP address."
}
if ($ServerIP -match '^(127\.|100\.)') {
    Warn "$ServerIP is not a normal local network address."
    Warn "127.x means 'this machine only'; 100.x is usually Tailscale."
    if (-not (AskYesNo "Use it anyway?" $false)) { Die "Re-run and enter a 192.168.x.x style address." }
}
Ok "Using $ServerIP"


# ------------------------------------------------------ Step 3: downloads --

Step 3 8 "Downloading the server and save editor"

if (Test-Path (Join-Path $TearDir 'wizard.exe')) {
    Ok "Server already present, skipping download"
} else {
    $tear = Get-LatestAsset 'Walter-Sparrow/lunar-tear' '*windows-amd64.zip'
    if (-not $tear) { Die "Could not find a Windows server release on GitHub." }
    $zip = Join-Path $Root $tear.Name
    if (-not (Test-Path $zip)) { Download $tear.Url $zip "server $($tear.Version)" }

    Say "Unpacking the server ..."
    $tmp = Join-Path $Root '_tear_tmp'
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
    Expand-Archive -Path $zip -DestinationPath $tmp -Force

    # Release archives may or may not have a single top-level folder.
    $inner = Get-ChildItem $tmp -Directory
    $source = if ($inner.Count -eq 1) { $inner[0].FullName } else { $tmp }
    New-Item -ItemType Directory -Path $TearDir -Force | Out-Null
    Get-ChildItem $source -Force | ForEach-Object { Move-Item $_.FullName $TearDir -Force }
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
    Ok "Server unpacked to lunar-tear\"
}

if ($python) {
    if (Test-Path (Join-Path $BaseDir 'start-lunar-base.bat')) {
        Ok "Save editor already present, skipping download"
    } else {
        $base = Get-LatestAsset 'NMeliksah/lunar-base' '*windows-amd64.zip'
        if (-not $base) {
            Warn "Could not find a Windows save-editor release; skipping it."
        } else {
            $zip = Join-Path $Root $base.Name
            if (-not (Test-Path $zip)) { Download $base.Url $zip "save editor $($base.Version)" }

            Say "Unpacking the save editor ..."
            $tmp = Join-Path $Root '_base_tmp'
            Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
            Expand-Archive -Path $zip -DestinationPath $tmp -Force
            $inner = Get-ChildItem $tmp -Directory
            $source = if ($inner.Count -eq 1) { $inner[0].FullName } else { $tmp }
            New-Item -ItemType Directory -Path $BaseDir -Force | Out-Null
            Get-ChildItem $source -Force | ForEach-Object { Move-Item $_.FullName $BaseDir -Force }
            Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
            Ok "Save editor unpacked to lunar-base\"
        }
    }
}

# -------------------------------------------------------- Step 4: assets ---

Step 4 8 "Unpacking the game assets"

$revisionsTarget = Join-Path $TearDir 'assets\revisions'
$alreadyDone = (Test-Path (Join-Path $revisionsTarget '0\android\assetbundle'))

if ($alreadyDone) {
    Ok "Assets already in place, skipping"
} else {
    $extractTo = Join-Path $Root '_assets_tmp'
    Remove-Item $extractTo -Recurse -Force -ErrorAction SilentlyContinue

    # Folder 0 holds the entire ~48 GB game; folders 1-817 are two-file
    # manifests. There is no partial extraction worth doing.
    Say "Unpacking the assets. This takes 20-60 minutes -- leave it running."
    & $sevenZip x $AssetArchive "-o$extractTo" -y | Out-Null
    if ($LASTEXITCODE -ne 0) { Die "7-Zip failed while unpacking the assets." }
    Ok "Assets unpacked"

    $extracted = Join-Path $extractTo 'revisions'
    if (-not (Test-Path $extracted)) {
        Die "Expected a 'revisions' folder inside the archive but did not find one."
    }

    Step 5 8 "Arranging the assets"

    New-Item -ItemType Directory -Path (Join-Path $TearDir 'assets\release') -Force | Out-Null
    New-Item -ItemType Directory -Path $revisionsTarget -Force | Out-Null

    Say "Moving revisions into place ..."
    Get-ChildItem $extracted -Directory | ForEach-Object {
        Move-Item $_.FullName (Join-Path $revisionsTarget $_.Name) -Force
    }

    Say "Adding the 'android' platform folder each revision needs ..."
    Say "  (folder 0 is the large one; the rest are two files each)"
    Add-PlatformFolders $revisionsTarget

    Remove-Item $extractTo -Recurse -Force -ErrorAction SilentlyContinue
    Ok "Assets arranged"
}

# --------------------------------------------------- Step 6: master data ---

Step 6 8 "Putting the master data in place"

$releaseDir = Join-Path $TearDir 'assets\release'
New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null
Copy-Item $masterData.FullName (Join-Path $releaseDir $masterData.Name) -Force
Ok "Copied $($masterData.Name) into assets\release\"

# Verify the layout before handing over to the wizard.
$check = Join-Path $revisionsTarget '0\android'
if (-not (Test-Path (Join-Path $check 'assetbundle'))) {
    Warn "Expected assetbundle at $check but did not find it."
    Warn "The server will start, but the game will not be able to download assets."
} else {
    Ok "Asset layout verified"
}

# --------------------------------------------------------- Step 7: server --

Step 7 8 "Starting the server"

Write-Host "  The server has its own setup questions that must be answered by hand." -ForegroundColor White
Write-Host "  A new window is about to open. Answer like this:" -ForegroundColor White
Write-Host ""
Write-Host "     'Where is the game running?'" -ForegroundColor Yellow
Write-Host "         choose  Phone / Tablet on the same network" -ForegroundColor Green
Write-Host "         (yes, even for BlueStacks -- the emulator option sets an" -ForegroundColor Gray
Write-Host "          address that only works in Android Studio's emulator)" -ForegroundColor Gray
Write-Host ""
Write-Host "     'How is your phone connected?'" -ForegroundColor Yellow
Write-Host "         choose  Something else / I'll type the IP" -ForegroundColor Green
Write-Host "         then enter:  $ServerIP" -ForegroundColor Green
Write-Host ""
Write-Host "     Ports: press Enter to accept the defaults" -ForegroundColor Yellow
Write-Host ""
Write-Host "     'Launch the server?'" -ForegroundColor Yellow
Write-Host "         choose  Yes, start" -ForegroundColor Green
Write-Host ""
Write-Host "  Use the arrow keys to move, Enter to choose." -ForegroundColor Gray
Write-Host "  LEAVE THAT WINDOW OPEN afterwards -- closing it stops the server." -ForegroundColor White
Write-Host ""

if (-not $Yes) { Read-Host "  Press Enter to open the server window" }

Start-Process -FilePath 'cmd.exe' `
    -ArgumentList '/k', 'title Game Server - keep this open && wizard.exe' `
    -WorkingDirectory $TearDir

Say "Waiting for the server to create your save file ..."
$gameDb = Join-Path $TearDir 'db\game.db'
$waited = 0
while (-not (Test-Path $gameDb) -and $waited -lt 600) {
    Start-Sleep -Seconds 3
    $waited += 3
    if ($waited % 30 -eq 0) { Say "  still waiting ... ($waited seconds)" }
}

if (Test-Path $gameDb) {
    Ok "Server is up and the save file exists"
} else {
    Warn "Did not see a save file after 10 minutes."
    Warn "Check the server window for errors, then carry on here."
    if (-not $Yes) { Read-Host "  Press Enter to continue anyway" }
}

# ---------------------------------------------------- Step 8: save editor --

Step 8 8 "Starting the save editor"

if ($python -and (Test-Path (Join-Path $BaseDir 'start-lunar-base.bat'))) {
    Write-Host "  Another window will open and install the save editor." -ForegroundColor White
    Write-Host "  First run decodes the game data, which takes a few minutes." -ForegroundColor Gray
    Write-Host "  LEAVE THAT WINDOW OPEN too." -ForegroundColor White
    Write-Host ""
    if (-not $Yes) { Read-Host "  Press Enter to open the save editor window" }

    Start-Process -FilePath 'cmd.exe' `
        -ArgumentList '/k', "title Save Editor - keep this open && start-lunar-base.bat --yes --port $BasePort" `
        -WorkingDirectory $BaseDir

    Ok "Save editor starting -- it will be at http://127.0.0.1:$BasePort"
} else {
    Warn "Skipping the save editor (Python missing, or it was not downloaded)."
}

# ------------------------------------------------------------- what next --

Write-Host ""
Write-Host "  =====================================================" -ForegroundColor DarkCyan
Write-Host "                    ALMOST THERE" -ForegroundColor White
Write-Host "  =====================================================" -ForegroundColor DarkCyan
Write-Host ""
Write-Host "  One step left, and it happens in your browser: the game app" -ForegroundColor White
Write-Host "  has to be told where your server is." -ForegroundColor White
Write-Host ""
Write-Host "  1. Upload these two files to Google Drive (drive.google.com):" -ForegroundColor White
Write-Host "        - the game APK, version 3.7.1 global" -ForegroundColor Gray
Write-Host "        - $($masterData.Name)" -ForegroundColor Gray
Write-Host ""
Write-Host "  2. Get lunar_tear_patcher.ipynb from the 'android' folder of:" -ForegroundColor White
Write-Host "        https://gitlab.com/walter-sparrow-group/lunar-scripts" -ForegroundColor Gray
Write-Host ""
Write-Host "  3. Open https://colab.research.google.com and upload that file" -ForegroundColor White
Write-Host "     (File -> Upload notebook)" -ForegroundColor Gray
Write-Host ""
Write-Host "  4. In the Configuration cell, enter EXACTLY:" -ForegroundColor White
Write-Host ""
Write-Host "        apk_source        = MyDrive/<your apk filename>" -ForegroundColor Green
Write-Host "        masterdata_source = MyDrive/$($masterData.Name)" -ForegroundColor Green
Write-Host "        grpc_addr         = ${ServerIP}:$GrpcPort" -ForegroundColor Green
Write-Host "        http_addr         = ${ServerIP}:$CdnPort" -ForegroundColor Green
Write-Host "        auth_host         = ${ServerIP}:$AuthPort" -ForegroundColor Green
Write-Host ""
Write-Host "  5. Runtime -> Run all. Two files download when it finishes:" -ForegroundColor White
Write-Host "        patched.apk           install this on your phone/emulator" -ForegroundColor Gray
Write-Host "        $($masterData.Name)   replace the one in:" -ForegroundColor Gray
Write-Host "           $releaseDir" -ForegroundColor Gray
Write-Host "        then restart the server window" -ForegroundColor Gray
Write-Host ""
Write-Host "  Full instructions are in COMPLETE-GUIDE.md, section 7." -ForegroundColor DarkGray
Write-Host ""
Write-Host "  -----------------------------------------------------" -ForegroundColor DarkCyan
Write-Host "  Your addresses, for reference:" -ForegroundColor White
Write-Host "        Game server   ${ServerIP}:$GrpcPort" -ForegroundColor Gray
Write-Host "        Assets (CDN)  ${ServerIP}:$CdnPort" -ForegroundColor Gray
Write-Host "        Accounts      ${ServerIP}:$AuthPort" -ForegroundColor Gray
Write-Host "        Save editor   http://127.0.0.1:$BasePort" -ForegroundColor Gray
Write-Host ""
Write-Host "  Starting up next time:" -ForegroundColor White
Write-Host "        cd $TearDir" -ForegroundColor Gray
Write-Host "        .\wizard.exe --prefer-saved" -ForegroundColor Gray
Write-Host ""
Write-Host "        cd $BaseDir" -ForegroundColor Gray
Write-Host "        .\start-lunar-base.bat --prefer-saved" -ForegroundColor Gray
Write-Host ""

if (-not $Yes) { Read-Host "  Press Enter to close this window" }
