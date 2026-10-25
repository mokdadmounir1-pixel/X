# Crée le raccourci « Quantbot - Terminal » sur le Bureau (avec l'icône du fennec en diamant). À lancer une seule fois.
Add-Type -AssemblyName System.Windows.Forms
$ErrorActionPreference = "Stop"
try {
    $root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
    $icon = Join-Path $root "assets\fennec_diamond.ico"
    if (-not (Test-Path $icon) -and (Get-Command python -ErrorAction SilentlyContinue)) { Push-Location $root; python tools\make_icon.py | Out-Null; Pop-Location }
    $desktop = [Environment]::GetFolderPath("Desktop")      # gère aussi un Bureau redirigé par OneDrive
    $lnkPath = Join-Path $desktop "Quantbot - Terminal.lnk"
    $sh = New-Object -ComObject WScript.Shell
    $lnk = $sh.CreateShortcut($lnkPath)
    $lnk.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
    $lnk.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$root\scripts\launch_terminal.ps1`""
    $lnk.WorkingDirectory = $root
    if (Test-Path $icon) { $lnk.IconLocation = $icon }
    $lnk.Description = "Terminal quantbot (lecture seule) - http://127.0.0.1:3214/"
    $lnk.Save()
    [System.Windows.Forms.MessageBox]::Show("Raccourci créé sur le Bureau :`n$lnkPath`n`nDouble-cliquez dessus pour ouvrir le terminal.", "quantbot") | Out-Null
} catch {
    [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, "quantbot - erreur") | Out-Null
    exit 1
}
