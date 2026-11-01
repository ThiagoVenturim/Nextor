# Agenda (ou atualiza) a rotina matinal do Nextor no Agendador de Tarefas do Windows.
# Le a hora de NEXTOR_ROTINA_HORA no .env (padrao 07:00). Rode de novo apos mudar a hora.
#
#   powershell -ExecutionPolicy Bypass -File scripts\agendar_rotina.ps1
#
# Remover:  Unregister-ScheduledTask -TaskName "NextorBomDia" -Confirm:$false

$raiz = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$python = Join-Path $raiz ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $python)) { $python = Join-Path $raiz ".venv\Scripts\python.exe" }

# Le a hora do .env
$hora = "07:00"
$envFile = Join-Path $raiz ".env"
if (Test-Path $envFile) {
    foreach ($linha in Get-Content $envFile) {
        if ($linha -match '^\s*NEXTOR_ROTINA_HORA\s*=\s*(.+)\s*$') { $hora = $matches[1].Trim() }
    }
}

$action  = New-ScheduledTaskAction -Execute $python -Argument "-m nextor.rotina" -WorkingDirectory $raiz
$trigger = New-ScheduledTaskTrigger -Daily -At $hora
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd

Register-ScheduledTask -TaskName "NextorBomDia" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Output "Rotina 'NextorBomDia' agendada para $hora todos os dias."
Write-Output "Testar agora: Start-ScheduledTask -TaskName 'NextorBomDia'"
