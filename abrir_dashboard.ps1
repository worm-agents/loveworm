# Abre el dashboard de loveworm reiniciando el servidor: si ya estaba corriendo lo cierra y lo levanta de
# nuevo, así siempre toma los últimos cambios del código. El Chrome viejo del bot lo cierra el servidor al arrancar.
$root = $PSScriptRoot
$url = 'http://127.0.0.1:5000'

function Test-Dashboard {
    try { Invoke-WebRequest "$url/api/state" -UseBasicParsing -TimeoutSec 2 | Out-Null; return $true } catch { return $false }
}

function Test-PuertoOcupado {
    [bool](Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue)
}

# el servidor viejo: lo que escucha en el 5000 y cualquier python corriendo loveworm.dashboard
# (también el que levanta la tarea programada con pythonw)
$viejos = @(Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess)
$viejos += Get-CimInstance Win32_Process -Filter "name='python.exe' or name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like '*loveworm.dashboard*' } | Select-Object -ExpandProperty ProcessId
foreach ($id in ($viejos | Where-Object { $_ } | Sort-Object -Unique)) {
    Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
}
for ($i = 0; $i -lt 15 -and (Test-PuertoOcupado); $i++) { Start-Sleep -Seconds 1 }

Start-Process -FilePath "$root\.venv\Scripts\python.exe" -ArgumentList '-m', 'loveworm.dashboard' `
    -WorkingDirectory $root -WindowStyle Minimized
for ($i = 0; $i -lt 30 -and -not (Test-Dashboard); $i++) { Start-Sleep -Seconds 1 }

Start-Process $url
