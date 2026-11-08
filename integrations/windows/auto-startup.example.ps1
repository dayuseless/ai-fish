# ==============================================================================
# Windows Auto-Startup Orchestration Template (auto-startup.example.ps1)
#
# Automates the cold boot sequence for autonomous AI agents & companion bridges:
#   1. Check & start proxy core (e.g. FlClash / Clash / Sing-box) and wait for ports.
#   2. Check & enable Windows system proxy and notify WinINet to apply immediately.
#   3. Pull up the primary AI Agent workspace session (e.g. Antigravity / Claude Code).
#   4. Start the companion host / bridge runtime (e.g. DeepSeek Harness / OneBot bridge).
#
# Customization:
#   Copy this file to `auto-startup.ps1` and adapt the paths below to your environment.
# ==============================================================================

[CmdletBinding()]
param(
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Continue'

# --- Configuration & Paths ---
$ProxyDir        = "C:\Program Files\ProxyClient"
$ProxyExe        = Join-Path $ProxyDir "ProxyClient.exe"
$ProxyPort       = 7890

$AgentWorkspace  = Join-Path $env:USERPROFILE "workspace"
$AgentCommand    = "agy"

$HostRuntimeDir  = "C:\Program Files\AgentHost"
$HostRuntimeExe  = Join-Path $HostRuntimeDir "AgentHost.exe"

$LogFile         = Join-Path $env:USERPROFILE ".ai-fish\boot-start.log"

function Write-Step([string]$msg) {
    $line = "{0} [BOOT] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Write-Host $line -ForegroundColor Cyan
    try {
        $parent = Split-Path -Parent $LogFile
        if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
        Add-Content -Path $LogFile -Value $line -Encoding UTF8
    } catch {}
}

function Test-PortListening([string]$ip, [int]$port, [int]$timeoutMs = 800) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $iar = $client.BeginConnect($ip, $port, $null, $null)
        if (-not $iar.AsyncWaitHandle.WaitOne($timeoutMs)) { return $false }
        return $client.Connected
    } catch {
        return $false
    } finally {
        try { $client.Close() } catch {}
    }
}

Write-Step "========== Auto-Startup Orchestration Sequence Start =========="

# 0. Grace period for Windows desktop stability
if (-not $CheckOnly) {
    Start-Sleep -Seconds 3
}

# ------------------------------------------------------------------------------
# 1. Start Proxy Client & Wait for Port
# ------------------------------------------------------------------------------
Write-Step "==> [1/4] Checking Proxy Core..."
$proxyProc = Get-Process -Name "ProxyClient" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($proxyProc) {
    Write-Step "    [OK] Proxy client is already running (PID=$($proxyProc.Id))"
} else {
    if (Test-Path $ProxyExe) {
        if ($CheckOnly) {
            Write-Step "    [WARN] Proxy client is not running (-CheckOnly mode)"
        } else {
            Write-Step "    [INFO] Launching proxy client: $ProxyExe"
            Start-Process -FilePath $ProxyExe -WorkingDirectory $ProxyDir -WindowStyle Hidden
        }
    } else {
        Write-Step "    [SKIP] Proxy client executable not found: $ProxyExe"
    }
}

# Wait for core port to listen
if (-not $CheckOnly -and (Test-Path $ProxyExe)) {
    $ready = $false
    for ($i = 0; $i -lt 15; $i++) {
        if (Test-PortListening "127.0.0.1" $ProxyPort) {
            $ready = $true
            break
        }
        Start-Sleep -Milliseconds 600
    }
    if ($ready) {
        Write-Step "    [OK] Proxy port 127.0.0.1:$ProxyPort is open and ready"
    } else {
        Write-Step "    [WARN] Proxy port 127.0.0.1:$ProxyPort not responding within timeout"
    }
}

# ------------------------------------------------------------------------------
# 2. Enable Windows System Proxy via WinINet
# ------------------------------------------------------------------------------
Write-Step "==> [2/4] Configuring Windows System Proxy..."
$regPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
$curEnable = (Get-ItemProperty -Path $regPath -Name ProxyEnable -ErrorAction SilentlyContinue).ProxyEnable
$curServer = (Get-ItemProperty -Path $regPath -Name ProxyServer -ErrorAction SilentlyContinue).ProxyServer
$targetServer = "127.0.0.1:$ProxyPort"

if ($curEnable -eq 1 -and $curServer -eq $targetServer) {
    Write-Step "    [OK] System proxy is already enabled and set to $targetServer"
} else {
    if ($CheckOnly) {
        Write-Step "    [WARN] System proxy is currently disabled or points to $curServer"
    } else {
        Set-ItemProperty -Path $regPath -Name ProxyEnable -Value 1
        Set-ItemProperty -Path $regPath -Name ProxyServer -Value $targetServer
        Set-ItemProperty -Path $regPath -Name ProxyOverride -Value "<local>;localhost;127.0.0.1"
        
        # Notify WinINet so existing applications pick up changes immediately
        Add-Type -TypeDefinition @"
        using System;
        using System.Runtime.InteropServices;
        public class WinINet {
            [DllImport("wininet.dll", SetLastError = true)]
            public static extern bool InternetSetOption(IntPtr hInternet, int dwOption, IntPtr lpBuffer, int dwBufferLength);
        }
"@ -ErrorAction SilentlyContinue
        try {
            [WinINet]::InternetSetOption([IntPtr]::Zero, 39, [IntPtr]::Zero, 0) | Out-Null
            [WinINet]::InternetSetOption([IntPtr]::Zero, 37, [IntPtr]::Zero, 0) | Out-Null
            Write-Step "    [OK] System proxy set to $targetServer and WinINet refreshed"
        } catch {
            Write-Step "    [WARN] System proxy registry updated, WinINet notify failed: $_"
        }
    }
}

# ------------------------------------------------------------------------------
# 3. Pull up AI Agent Session
# ------------------------------------------------------------------------------
Write-Step "==> [3/4] Pulling up Agent Session ($AgentWorkspace)..."
if (Test-Path $AgentWorkspace) {
    if (-not $CheckOnly) {
        Start-Process powershell.exe -ArgumentList "-NoExit", "-Command", "Set-Location '$AgentWorkspace'; $AgentCommand"
        Write-Step "    [OK] Agent session launched in new terminal"
    } else {
        Write-Step "    [OK] Workspace exists ($AgentWorkspace)"
    }
} else {
    Write-Step "    [SKIP] Workspace directory not found: $AgentWorkspace"
}

# ------------------------------------------------------------------------------
# 4. Pull up Host Runtime / Companion Bridge
# ------------------------------------------------------------------------------
Write-Step "==> [4/4] Starting Host Runtime / Bridge..."
if (Test-Path $HostRuntimeExe) {
    $hostProc = Get-Process -Name (Split-Path $HostRuntimeExe -LeafBase) -ErrorAction SilentlyContinue
    if ($hostProc) {
        Write-Step "    [OK] Host runtime already running (PID=$($hostProc.Id))"
    } elseif (-not $CheckOnly) {
        Start-Process -FilePath $HostRuntimeExe -WorkingDirectory $HostRuntimeDir
        Write-Step "    [OK] Host runtime started"
    }
} else {
    Write-Step "    [SKIP] Host runtime executable not found: $HostRuntimeExe"
}

Write-Step "========== Auto-Startup Orchestration Completed =========="
