# Lance le terminal quantbot (s'il ne tourne pas déjà) puis l'ouvre dans le navigateur. Double-clic via le raccourci du Bureau.
# Lecture seule : ce script ne lance que l'interface (aucun ordre, aucune simulation).
Add-Type -AssemblyName System.Windows.Forms
$ErrorActionPreference = "Stop"
try {
    $root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
    Set-Location $root
    $portFile = Join-Path $root "runtime\terminal.port"
    $port = 3214
    function Test-Terminal([int]$p) {
        try { $r = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$p/api/health" -TimeoutSec 2; return ($r.Content -like '*read_only*') } catch { return $false }
    }
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "Python est introuvable. Installez Python 3.10+ (cochez 'Add python.exe to PATH') puis relancez." }
    $ErrorActionPreference = "Continue"      # PowerShell 5.1 traite le texte d'erreur d'une commande native comme fatal avec "Stop"
    python -c "import fastapi, uvicorn, pandas" 2>&1 | Out-Null
    $missing = ($LASTEXITCODE -ne 0)
    if ($missing) {
        [System.Windows.Forms.MessageBox]::Show("Premier lancement : installation des dépendances (quelques minutes). Cliquez OK puis patientez.", "quantbot") | Out-Null
        python -m pip install -r requirements.txt 2>&1 | Out-Null
        $failed = ($LASTEXITCODE -ne 0)
        $ErrorActionPreference = "Stop"
        if ($failed) { throw "L'installation des dépendances a échoué (pip). Ouvrez PowerShell dans $root et lancez : pip install -r requirements.txt" }
    }
    $ErrorActionPreference = "Stop"
    if (Test-Path $portFile) { $saved = [int](Get-Content $portFile -Raw); if (Test-Terminal $saved) { $port = $saved } }
    if (-not (Test-Terminal $port)) {
        if (Test-Path $portFile) { Remove-Item $portFile -Force -ErrorAction SilentlyContinue }
        Start-Process python -ArgumentList @("-m", "quantbot", "ui", "--port", "$port") -WorkingDirectory $root -WindowStyle Minimized
        $ok = $false
        for ($i = 0; $i -lt 60; $i++) {
            Start-Sleep -Milliseconds 700
            if (Test-Path $portFile) { $port = [int](Get-Content $portFile -Raw) }
            if (Test-Terminal $port) { $ok = $true; break }
        }
        if (-not $ok) { throw "Le serveur ne répond pas sur le port $port. Ouvrez PowerShell dans $root et lancez : python -m quantbot ui  (lisez le message d'erreur)." }
    }
    Start-Process "http://127.0.0.1:$port/"
} catch {
    [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, "quantbot - erreur") | Out-Null
    exit 1
}
