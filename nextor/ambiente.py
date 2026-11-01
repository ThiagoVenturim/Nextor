"""Ambiente de cada modo: brilho da tela do PC e luzes da casa (via Home Assistant).

Tudo e opcional. Sem Home Assistant configurado, so o brilho do PC muda.
"""
import json
import os
import subprocess
import sys
import urllib.request

# Cena padrao das luzes por modo: brilho (%) e temperatura de cor (Kelvin).
LUZES_PADRAO = {
    "normal": (70, 4000),
    "estudo": (100, 5000),
    "trabalho": (85, 4500),
    "tranquilidade": (30, 2700),
    "leitura": (55, 3000),
}
# Brilho da tela do PC por modo (None = nao mexe).
BRILHO_PC_PADRAO = {"leitura": 30, "tranquilidade": 40}


def _env(nome: str, padrao: str = "") -> str:
    return os.getenv(nome, padrao).strip()


def brilho_pc(modo: str) -> int | None:
    valor = _env(f"NEXTOR_BRILHO_{modo.upper()}")
    if valor.isdigit():
        return max(0, min(100, int(valor)))
    return BRILHO_PC_PADRAO.get(modo)


def ajustar_brilho_pc(nivel: int) -> None:
    """Brilho da tela interna do notebook (WMI). Monitores externos nao respondem a isso."""
    if sys.platform != "win32":
        raise RuntimeError("brilho do PC so no Windows")
    nivel = max(0, min(100, int(nivel)))
    script = ("Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods | "
              f"Invoke-CimMethod -MethodName WmiSetBrightness -Arguments @{{ Timeout = 0; Brightness = {nivel} }} | Out-Null")
    subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                   check=True, capture_output=True, timeout=20)


def ler_brilho_pc() -> int | None:
    if sys.platform != "win32":
        return None
    r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                        "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness).CurrentBrightness"],
                       capture_output=True, text=True, timeout=20)
    valor = r.stdout.strip().splitlines()[0] if r.stdout.strip() else ""
    return int(valor) if valor.isdigit() else None


# Brilho de antes do primeiro modo que mexeu na tela, para devolver ao sair dele.
_brilho_anterior: int | None = None


def _ha(servico: str, dados: dict) -> None:
    url = _env("NEXTOR_HA_URL").rstrip("/")
    req = urllib.request.Request(
        f"{url}/api/services/{servico}",
        data=json.dumps(dados).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {_env('NEXTOR_HA_TOKEN')}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310 - URL vem do .env
        r.read()


def luzes_configuradas() -> bool:
    return bool(_env("NEXTOR_HA_URL") and _env("NEXTOR_HA_TOKEN"))


def aplicar_luzes(modo: str) -> str:
    cena = _env(f"NEXTOR_HA_CENA_{modo.upper()}")
    if cena:
        _ha("scene/turn_on", {"entity_id": cena})
        return f"cena {cena}"
    luzes = [x.strip() for x in _env("NEXTOR_HA_LUZES").split(",") if x.strip()]
    if not luzes:
        return "nenhuma luz em NEXTOR_HA_LUZES"
    brilho, kelvin = LUZES_PADRAO.get(modo, LUZES_PADRAO["normal"])
    _ha("light/turn_on", {"entity_id": luzes, "brightness_pct": brilho, "color_temp_kelvin": kelvin})
    return f"{len(luzes)} luz(es) em {brilho}%"


def aplicar(modo: str) -> list[str]:
    """Aplica o ambiente do modo e devolve avisos legiveis. Nunca levanta excecao."""
    global _brilho_anterior
    avisos = []
    nivel = brilho_pc(modo)
    muda_pc = _env("NEXTOR_MODO_MUDA_PC", "sim").lower() in ("1", "true", "sim", "yes")
    if muda_pc and nivel is None and _brilho_anterior is not None:
        nivel, _brilho_anterior = _brilho_anterior, None  # saindo do modo: devolve o brilho de antes
    elif muda_pc and nivel is not None and _brilho_anterior is None:
        try:
            _brilho_anterior = ler_brilho_pc()
        except Exception:
            _brilho_anterior = None
    if muda_pc and nivel is not None:
        try:
            ajustar_brilho_pc(nivel)
            avisos.append(f"Tela do PC em {nivel}%.")
        except Exception as e:
            avisos.append(f"Nao consegui mudar o brilho do PC ({e.__class__.__name__}).")
    if luzes_configuradas():
        try:
            avisos.append(f"Luzes: {aplicar_luzes(modo)}.")
        except Exception as e:
            avisos.append(f"Nao consegui falar com o Home Assistant ({e.__class__.__name__}).")
    return avisos
