# Abre o rosto do Nextor numa janela propria (modo aplicativo do Edge ou do Chrome).
#   powershell -ExecutionPolicy Bypass -File scripts\rosto.ps1
# O Nextor precisa estar rodando (python -m nextor). O token sai do .env do perfil ativo.
$raiz = Split-Path -Parent $PSScriptRoot
$perfil = if (Test-Path "$raiz\.perfil") { (Get-Content "$raiz\.perfil" -Raw).Trim() } else { "" }
$env_arquivo = if ($perfil -and (Test-Path "$raiz\.env.$perfil")) { "$raiz\.env.$perfil" } else { "$raiz\.env" }
$linhas = Get-Content $env_arquivo
$token = (($linhas | Where-Object { $_ -match '^NEXTOR_TOKEN=' }) -replace '^NEXTOR_TOKEN=', '').Trim('"')
$porta = (($linhas | Where-Object { $_ -match '^NEXTOR_PORTA=' }) -replace '^NEXTOR_PORTA=', '').Trim('"')
if (-not $porta) { $porta = '5005' }
$url = "http://localhost:$porta/rosto?token=$([uri]::EscapeDataString($token))"

$navegadores = @(
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe"
)
$exe = $navegadores | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $exe) { Start-Process $url; exit 0 }
Start-Process $exe -ArgumentList "--app=$url", "--window-size=460,720", "--autoplay-policy=no-user-gesture-required"
