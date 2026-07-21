$project = "C:\Users\vashu\OneDrive\Documents\Telegram Bot"
$logFile = Join-Path $project "github-auto-sync.log"

try {
    Set-Location $project

    $changes = git status --porcelain

    if (-not $changes) {
        exit 0
    }

    git add -A

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    git commit -m "Automatic backup: $timestamp"

    if ($LASTEXITCODE -ne 0) {
        Add-Content $logFile "[$timestamp] Commit failed."
        exit 1
    }

    git push origin main

    if ($LASTEXITCODE -eq 0) {
        Add-Content $logFile "[$timestamp] Changes uploaded successfully."
    } else {
        Add-Content $logFile "[$timestamp] Push failed. Sign-in or internet may be required."
    }
}
catch {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content $logFile "[$timestamp] ERROR: $($_.Exception.Message)"
}
