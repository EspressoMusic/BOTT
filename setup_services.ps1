# Run this once, as Administrator, to make BOTT survive reboots/crashes
# without depending on any Claude Code session being open.

# Stop whatever is currently bound to 8000/5173 (the manually-launched
# processes from before) so the new services can bind those ports.
foreach ($port in 8000, 5173) {
    $ownerIds = (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue).OwningProcess
    foreach ($procId in $ownerIds | Select-Object -Unique) {
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    }
}
Start-Sleep -Seconds 2

$nssm = "C:\Users\Nirhdhd\AppData\Local\Microsoft\WinGet\Packages\NSSM.NSSM_Microsoft.Winget.Source_8wekyb3d8bbwe\nssm-2.24-101-g897c7ad\win64\nssm.exe"

# --- Backend (FastAPI / uvicorn) ---
& $nssm install BOTT-Backend "C:\Users\Nirhdhd\BOTT\backend\venv\Scripts\python.exe" "-m uvicorn app.main:app --host 127.0.0.1 --port 8000"
& $nssm set BOTT-Backend AppDirectory "C:\Users\Nirhdhd\BOTT\backend"
& $nssm set BOTT-Backend AppStdout "C:\Users\Nirhdhd\BOTT\backend\backend_stdout.log"
& $nssm set BOTT-Backend AppStderr "C:\Users\Nirhdhd\BOTT\backend\backend_stderr.log"
& $nssm set BOTT-Backend AppRotateFiles 1
& $nssm set BOTT-Backend AppRotateOnline 1
& $nssm set BOTT-Backend AppRotateBytes 10485760
& $nssm set BOTT-Backend Start SERVICE_AUTO_START
& $nssm set BOTT-Backend AppRestartDelay 3000

# --- Frontend (vite dev server, exposed on LAN) ---
& $nssm install BOTT-Frontend "C:\nvm4w\nodejs\node.exe" "C:\Users\Nirhdhd\BOTT\frontend\node_modules\vite\bin\vite.js --host"
& $nssm set BOTT-Frontend AppDirectory "C:\Users\Nirhdhd\BOTT\frontend"
& $nssm set BOTT-Frontend AppStdout "C:\Users\Nirhdhd\BOTT\frontend\frontend.log"
& $nssm set BOTT-Frontend AppStderr "C:\Users\Nirhdhd\BOTT\frontend\frontend.log"
& $nssm set BOTT-Frontend AppRotateFiles 1
& $nssm set BOTT-Frontend AppRotateOnline 1
& $nssm set BOTT-Frontend AppRotateBytes 10485760
& $nssm set BOTT-Frontend Start SERVICE_AUTO_START
& $nssm set BOTT-Frontend AppRestartDelay 3000

Write-Output "Services installed. Starting them now..."
Start-Service BOTT-Backend
Start-Service BOTT-Frontend
Start-Sleep -Seconds 5
Get-Service BOTT-Backend, BOTT-Frontend
