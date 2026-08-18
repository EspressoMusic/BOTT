$ErrorActionPreference = 'SilentlyContinue'

Write-Host "=== בודק ומפעיל את BOTT ===" -ForegroundColor Cyan

# 1) MT5 terminal — the backend can't connect without it
$mt5 = Get-Process -Name terminal64 -ErrorAction SilentlyContinue
if (-not $mt5) {
    Write-Host "מפעיל את MetaTrader 5..."
    Start-Process -FilePath "C:\Program Files\MetaTrader 5\terminal64.exe" -WindowStyle Minimized
    Start-Sleep -Seconds 12
} else {
    Write-Host "MetaTrader 5 כבר פעיל."
}

# 2) Backend (port 8000)
$backendUp = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if (-not $backendUp) {
    Write-Host "מפעיל את הבקאנד..."
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "C:\Users\Nirhdhd\BOTT\backend\start_backend.bat" -WindowStyle Hidden
    Start-Sleep -Seconds 8
} else {
    Write-Host "הבקאנד כבר פעיל."
}

# 3) Frontend (port 5173) — launch node directly (not via npm.cmd) so it
# survives detached and doesn't depend on a console being allocated.
$frontendUp = Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue
if (-not $frontendUp) {
    Write-Host "מפעיל את הפרונטאנד..."
    Start-Process -FilePath "C:\nvm4w\nodejs\node.exe" `
        -ArgumentList '"C:\Users\Nirhdhd\BOTT\frontend\node_modules\vite\bin\vite.js" --host' `
        -WorkingDirectory "C:\Users\Nirhdhd\BOTT\frontend" -WindowStyle Hidden `
        -RedirectStandardOutput "C:\Users\Nirhdhd\BOTT\frontend\frontend.log" `
        -RedirectStandardError "C:\Users\Nirhdhd\BOTT\frontend\frontend_err.log"
    Start-Sleep -Seconds 5
} else {
    Write-Host "הפרונטאנד כבר פעיל."
}

Start-Sleep -Seconds 3
Write-Host ""
try {
    $status = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/bot/status" -TimeoutSec 8 -ErrorAction Stop
    $enabled = if ($status.bot_enabled) { "פעיל" } else { "כבוי (מתג הפעלה)" }
    Write-Host "✅ הבוט חי! מצב: $enabled | יתרה: $($status.account.balance)$ | פוזיציות פתוחות: $($status.account.open_trade_count)" -ForegroundColor Green
    Write-Host "קישור: http://192.168.1.173:5173"
} catch {
    Write-Host "❌ הבקאנד עדיין לא מגיב אחרי ניסיון ההפעלה. אולי MT5 עוד בטעינה — סגור את החלון הזה, חכה דקה, והרץ שוב." -ForegroundColor Red
}

Write-Host ""
Write-Host "אפשר לסגור את החלון הזה."
Start-Sleep -Seconds 30
