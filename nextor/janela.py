"""Abre o rosto do Nextor numa janela propria quando ele e chamado e nenhuma tela esta mostrando."""
import os
import subprocess
import sys
import urllib.parse
from pathlib import Path

from . import config

NAVEGADORES = (
    Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft/Edge/Application/msedge.exe",
    Path(os.environ.get("ProgramFiles", "")) / "Microsoft/Edge/Application/msedge.exe",
    Path(os.environ.get("ProgramFiles", "")) / "Google/Chrome/Application/chrome.exe",
)


def abrir_rosto(forcar: bool = False) -> bool:
    """Abre a janela do rosto (Windows). Nao abre de novo se alguma tela ja estiver conectada."""
    from .companheiro import companheiro
    if sys.platform != "win32" or os.getenv("NEXTOR_ROSTO_AUTO", "sim").lower() in ("0", "nao", "false", "no"):
        return False
    if companheiro.ouvintes() > 0 and not forcar:
        return False
    url = f"http://localhost:{config.PORTA}/rosto?token={urllib.parse.quote(config.TOKEN)}"
    exe = next((p for p in NAVEGADORES if p.is_file()), None)
    if exe is None:
        os.startfile(url)  # noqa: S606 - navegador padrao
        return True
    subprocess.Popen([str(exe), f"--app={url}", "--window-size=460,720", "--autoplay-policy=no-user-gesture-required"],  # noqa: S603
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True
