# Crea la tarea "LoveWorm - Dashboard": levanta el dashboard (http://127.0.0.1:5000) al iniciar sesión, sin ventana.
# Con "Abrir Chrome solo al iniciar" prendido en Configuración, los swipes diarios y el piloto corren sin tocar nada.
# Para sacarla: Unregister-ScheduledTask -TaskName 'LoveWorm - Dashboard' -Confirm:$false
$ErrorActionPreference = 'Stop'
$user = "$env:USERDOMAIN\$env:USERNAME"
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$pythonw = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
$action = New-ScheduledTaskAction -Execute $pythonw -Argument '-m loveworm.dashboard' -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
# demora y reintentos: al iniciar sesión un disco secundario (donde puede estar el proyecto) puede no estar listo todavía
$trigger.Delay = 'PT1M'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName 'LoveWorm - Dashboard' -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
    -Description 'Levanta el dashboard de LoveWorm en http://127.0.0.1:5000 al iniciar sesión.' -Force | Out-Null
Write-Output "Tarea creada: el dashboard de LoveWorm arranca solo al iniciar sesión."
