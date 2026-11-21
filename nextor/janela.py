"""Abre o rosto ou o painel PWA do Nextor numa janela dedicada (Windows, Linux e macOS)."""
import os
import shutil
import subprocess
import sys
import urllib.parse
import webbrowser
from pathlib import Path

from . import config

NAVEGADORES = (
    Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft/Edge/Application/msedge.exe",
    Path(os.environ.get("ProgramFiles", "")) / "Microsoft/Edge/Application/msedge.exe",
    Path(os.environ.get("ProgramFiles", "")) / "Google/Chrome/Application/chrome.exe",
)

NAVEGADORES_MACOS = (
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
    Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
    Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
)

NAVEGADORES_LINUX = (
    "google-chrome",
    "google-chrome-stable",
    "microsoft-edge",
    "chromium",
    "chromium-browser",
    "brave-browser",
)


def localizar_navegador_app(plataforma: str | None = None) -> Path | None:
    """Encontra um navegador compativel com modo aplicativo (--app=URL) no sistema operacional."""
    plat = (plataforma or sys.platform).lower()
    if plat == "win32" or plat.startswith("win"):
        return next((p for p in NAVEGADORES if p.is_file()), None)
    if plat == "darwin" or plat == "macos":
        return next((p for p in NAVEGADORES_MACOS if p.is_file()), None)
    if plat.startswith("linux"):
        for cmd in NAVEGADORES_LINUX:
            encontrado = shutil.which(cmd)
            if encontrado:
                return Path(encontrado)
    return None


def _abrir_janela_url(url: str, largura: int = 460, altura: int = 720, plataforma: str | None = None) -> bool:
    plat = (plataforma or sys.platform).lower()
    exe = localizar_navegador_app(plat)
    if exe is not None:
        subprocess.Popen(
            [
                str(exe),
                f"--app={url}",
                f"--window-size={largura},{altura}",
                "--autoplay-policy=no-user-gesture-required",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    if plat == "win32" and hasattr(os, "startfile"):
        os.startfile(url)
        return True
    return webbrowser.open(url)


def abrir_rosto(forcar: bool = False) -> bool:
    """Abre a janela do rosto. Nao abre de novo se alguma tela ja estiver conectada."""
    from .companheiro import companheiro
    if os.getenv("NEXTOR_ROSTO_AUTO", "sim").lower() in ("0", "nao", "false", "no"):
        return False
    if companheiro.ouvintes() > 0 and not forcar:
        return False
    url = f"http://localhost:{config.PORTA}/rosto?token={urllib.parse.quote(config.TOKEN)}"
    return _abrir_janela_url(url, largura=460, altura=720)


def abrir_app(caminho: str = "/painel", largura: int = 1024, altura: int = 740) -> bool:
    """Abre a interface PWA universal do Nextor em modo aplicativo no desktop (Windows, Linux, macOS)."""
    rota = caminho if caminho.startswith("/") else f"/{caminho}"
    url = f"http://localhost:{config.PORTA}{rota}#token={urllib.parse.quote(config.TOKEN)}"
    return _abrir_janela_url(url, largura=largura, altura=altura)
