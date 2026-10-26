param(
    [string]$ServiceUrl = 'https://self-agent.matterswarm.com',
    [ValidateSet('codex','claude','both')][string]$Client = 'codex',
    [string]$PairCode = ''
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
try {
    $origin = [Uri]$ServiceUrl
    if ($origin.Scheme -ne 'https' -or $origin.UserInfo) { throw 'An HTTPS service URL is required.' }
    $pythonCommand = $null
    $pythonPrefix = @()
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        $testVersion = & $launcher.Source -3 -c 'import sys;print(int(sys.version_info >= (3,11)))' 2>$null
        if ($LASTEXITCODE -eq 0 -and "$testVersion".Trim() -eq '1') { $pythonCommand = $launcher.Source; $pythonPrefix = @('-3') }
    }
    if (-not $pythonCommand) {
        $candidate = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($candidate -and $candidate.Source -notlike '*WindowsApps*') {
            $testVersion = & $candidate.Source -c 'import sys;print(int(sys.version_info >= (3,11)))' 2>$null
            if ($LASTEXITCODE -eq 0 -and "$testVersion".Trim() -eq '1') { $pythonCommand = $candidate.Source }
        }
    }
    if (-not $pythonCommand) { throw 'Python 3.11+ is required. Install it from https://www.python.org/downloads/windows/ and run this installer again.' }
    $clientRoot = Join-Path $env:LOCALAPPDATA 'self-agent\client'
    $work = Join-Path $clientRoot ([Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $work -Force | Out-Null
    $manifestUrl = $ServiceUrl.TrimEnd('/') + '/assets/downloads/client-manifest.json'
    $manifest = Invoke-RestMethod -Uri $manifestUrl -MaximumRedirection 0 -TimeoutSec 30
    if ($manifest.sha256 -notmatch '^[0-9a-f]{64}$' -or $manifest.bytes -gt 10485760) { throw 'Invalid client manifest.' }
    $archive = Join-Path $work 'client.zip'
    Write-Host 'Downloading the verified Self Agent client...'
    Invoke-WebRequest -UseBasicParsing -MaximumRedirection 0 -Uri ($ServiceUrl.TrimEnd('/') + '/assets/downloads/client.zip') -OutFile $archive -TimeoutSec 60
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manifest.sha256) { throw 'Client checksum verification failed.' }
    $source = Join-Path $work 'source'
    Expand-Archive -LiteralPath $archive -DestinationPath $source
    $environment = Join-Path $work 'venv'
    & $pythonCommand @pythonPrefix -m venv $environment
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the client environment.' }
    $venvPython = Join-Path $environment 'Scripts\python.exe'
    $networkProxy = $null
    $network = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' -ErrorAction SilentlyContinue
    if ($network.ProxyEnable -and $network.ProxyServer) {
        $value = [string]$network.ProxyServer
        if ($value -match '(?:^|;)https?=([^;]+)') { $value = $Matches[1] }
        if ($value -match '^(?:http://)?(?:127\.0\.0\.1|localhost):[0-9]+$') {
            if (-not $value.StartsWith('http://')) { $value = 'http://' + $value }
            $networkProxy = $value
        }
    }
    $pipArgs = @('-m','pip','install','--disable-pip-version-check','-e',$source)
    if ($networkProxy) { $pipArgs += @('--proxy',$networkProxy) }
    Write-Host 'Installing the client dependencies...'
    & $venvPython @pipArgs
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. The existing agent configuration has not been changed.' }
    $setupArgs = @('-m','self_agent.cli','setup','--url',$ServiceUrl,'--client',$Client)
    if ($networkProxy) { $setupArgs += @('--proxy',$networkProxy) }
    if ($PairCode) {
        $setupArgs += '--pair-code-stdin'
        $PairCode | & $venvPython @setupArgs
        $PairCode = $null
    } else {
        & $venvPython @setupArgs
    }
    if ($LASTEXITCODE -ne 0) { throw 'Connection was not completed. Download a fresh setup package if the pairing code expired.' }
    Write-Host 'Connected. Restart your selected agent. For Codex, review the new hooks in /hooks.' -ForegroundColor Green
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
