"""Suporte multiplataforma do Nextor (Issue #52).

Centraliza o catalogo de plataformas suportadas (Web PWA, Windows, Linux, macOS,
Android e iPhone/iOS), deteccao de sistema por User-Agent, validacao dos ativos do
PWA universal (manifest, service worker, icones e shell HTML) e geracao de
configuracoes de empacotamento desktop (Tauri) e mobile (Capacitor / TWA) sem
segredos embutidos.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import config

WEB_DIR = Path(__file__).resolve().parent / "web"
DIST_DIR = config.RAIZ / "dist"
PACKAGING_DIR = config.RAIZ / "packaging"

PLATAFORMAS: dict[str, dict[str, Any]] = {
    "web": {
        "id": "web",
        "nome": "Web (PWA Universal)",
        "categoria": "universal",
        "etapa": 1,
        "formatos": ["PWA (manifest.webmanifest + Service Worker)"],
        "instalavel": True,
        "offline_shell": True,
        "executa_servico_local": False,
        "conexao": "Rede local (http://localhost:5005 ou IP da LAN) ou VPN privada",
        "passos_instalacao": [
            "Suba o servico na maquina principal com `python -m nextor`.",
            "Abra `http://localhost:5005/painel` (ou `/gtd`) no navegador.",
            "Clique em 'Instalar app' no banner ou no icone de instalacao da barra de enderecos.",
        ],
    },
    "windows": {
        "id": "windows",
        "nome": "Windows",
        "categoria": "desktop",
        "etapa": 1,
        "formatos": [".msi", ".exe", "PWA Desktop (Edge / Chrome --app)"],
        "instalavel": True,
        "offline_shell": True,
        "executa_servico_local": True,
        "conexao": "Local (127.0.0.1) ou rede local",
        "comando_empacotamento": "python scripts/empacotar_desktop.py --plataforma windows",
        "passos_instalacao": [
            "Opcao imediata (sem build): execute `python -m nextor` e instale o PWA pelo Edge/Chrome ou rode `powershell -ExecutionPolicy Bypass -File scripts/rosto.ps1`.",
            "Opcao instalador (.msi / .exe): execute `python scripts/empacotar_desktop.py --plataforma windows` para validar os ativos e gerar a estrutura Tauri em `packaging/desktop/`.",
            "Com Rust e Tauri CLI instalados, rode `cargo tauri build` para gerar os instaladores em `src-tauri/target/release/bundle/`.",
        ],
    },
    "linux": {
        "id": "linux",
        "nome": "Linux",
        "categoria": "desktop",
        "etapa": 1,
        "formatos": [".AppImage", ".deb", "PWA Desktop (Chromium / Chrome --app)"],
        "instalavel": True,
        "offline_shell": True,
        "executa_servico_local": True,
        "conexao": "Local (127.0.0.1) ou rede local",
        "comando_empacotamento": "python scripts/empacotar_desktop.py --plataforma linux",
        "passos_instalacao": [
            "Opcao imediata: suba `python3 -m nextor` e instale o PWA pelo navegador.",
            "Opcao empacotada (.AppImage / .deb): execute `python3 scripts/empacotar_desktop.py --plataforma linux` e `cargo tauri build`.",
        ],
    },
    "macos": {
        "id": "macos",
        "nome": "macOS",
        "categoria": "desktop",
        "etapa": 1,
        "formatos": [".dmg", ".app", "Safari Adicionar ao Dock"],
        "instalavel": True,
        "offline_shell": True,
        "executa_servico_local": True,
        "conexao": "Local (127.0.0.1) ou rede local",
        "comando_empacotamento": "python scripts/empacotar_desktop.py --plataforma macos",
        "passos_instalacao": [
            "Opcao imediata: no Safari (macOS Sonoma+), abra `/painel` e clique em Arquivo > Adicionar ao Dock.",
            "Opcao empacotada (.dmg / .app): execute `python3 scripts/empacotar_desktop.py --plataforma macos` e `cargo tauri build`.",
        ],
    },
    "android": {
        "id": "android",
        "nome": "Android",
        "categoria": "mobile",
        "etapa": 2,
        "formatos": ["PWA (Chrome)", ".apk (Capacitor / TWA Bubblewrap)"],
        "instalavel": True,
        "offline_shell": True,
        "executa_servico_local": False,
        "conexao": "Wi-Fi na mesma rede local ou VPN privada (ex.: Tailscale)",
        "comando_empacotamento": "python scripts/empacotar_desktop.py --plataforma android",
        "passos_instalacao": [
            "Opcao recomendada (PWA): abra `http://<IP_DO_PC>:5005/painel` ou `/gtd` no Chrome do Android e toque em 'Instalar aplicativo'.",
            "Opcao APK nativo (Capacitor): execute `python scripts/empacotar_desktop.py --plataforma android` para sincronizar a pasta `nextor/web/` e gere o APK com `npx cap build android`.",
            "No app instalado, configure o endereco do seu Nextor (LAN ou IP Tailscale) e o token na secao Conexao.",
        ],
    },
    "ios": {
        "id": "ios",
        "nome": "iPhone e iPad (iOS)",
        "categoria": "mobile",
        "etapa": 3,
        "formatos": ["PWA (Safari Tela de Inicio)", "Atalhos da Siri", "Capacitor (opcional)"],
        "instalavel": True,
        "offline_shell": True,
        "executa_servico_local": False,
        "conexao": "Wi-Fi na mesma rede local ou VPN privada (ex.: Tailscale)",
        "limites_ios": [
            "O iOS nao permite que aplicativos de terceiros gerenciem o sistema operacional nem executem processos Python em background continuo.",
            "Para ser instalavel e receber Web Push no iOS 16.4+, o PWA precisa ser adicionado a Tela de Inicio pelo Safari (Compartilhar > Adicionar a Tela de Inicio).",
            "Comandos de voz com a tela bloqueada usam o app Atalhos (Shortcuts) integrado ao endpoint `/comando` ou `/v1/assistente` (ver `docs/ATALHO_IPHONE.md`).",
            "Empacotamento nativo via Capacitor no iOS exige macOS com Xcode e conta Apple Developer para assinatura fora de desenvolvimento local.",
        ],
        "passos_instalacao": [
            "No Safari do iPhone/iPad, acesse `http://<IP_DO_PC>:5005/painel` ou `/gtd`.",
            "Toque no botao Compartilhar e selecione 'Adicionar a Tela de Inicio'.",
            "Abra o icone criado na tela inicial e salve seu token no bloco Conexao.",
            "Para comandos por voz na Siri, configure o atalho descrito em `docs/ATALHO_IPHONE.md`.",
        ],
    },
}


def detectar_plataforma(user_agent: str | None) -> str:
    """Detecta a plataforma do cliente a partir do cabecalho User-Agent."""
    ua = (user_agent or "").lower()
    if not ua:
        return "web"
    if any(k in ua for k in ("iphone", "ipad", "ipod")):
        return "ios"
    if "android" in ua:
        return "android"
    if "windows" in ua or "win64" in ua or "win32" in ua:
        return "windows"
    if "macintosh" in ua or "mac os x" in ua:
        return "macos"
    if "linux" in ua or "x11" in ua:
        return "linux"
    return "web"


def listar_plataformas() -> list[dict[str, Any]]:
    """Retorna a lista ordenada de plataformas suportadas."""
    ordem = ("web", "windows", "linux", "macos", "android", "ios")
    return [dict(PLATAFORMAS[k]) for k in ordem if k in PLATAFORMAS]


def obter_plataforma(slug: str) -> dict[str, Any] | None:
    """Retorna os metadados de uma plataforma especifica."""
    chave = (slug or "").strip().lower()
    if chave in ("mac", "osx", "darwin"):
        chave = "macos"
    elif chave in ("iphone", "ipad"):
        chave = "ios"
    elif chave in ("win", "win32"):
        chave = "windows"
    item = PLATAFORMAS.get(chave)
    return dict(item) if item else None


def verificar_requisitos_pwa(pasta_web: Path | None = None) -> dict[str, Any]:
    """Valida se todos os arquivos do PWA universal existem e sao validos."""
    base = pasta_web or WEB_DIR
    obrigatorios = [
        "manifest.webmanifest",
        "sw.js",
        "painel.html",
        "painel.css",
        "painel.js",
        "download.html",
        "rosto.html",
        "icone-192.png",
        "icone-512.png",
        "gtd/index.html",
        "gtd/manifest.webmanifest",
        "gtd/sw.js",
    ]
    ausentes = [arq for arq in obrigatorios if not (base / arq).is_file()]

    manifest_valido = False
    campos_manifest: list[str] = []
    manifest_path = base / "manifest.webmanifest"
    if manifest_path.is_file():
        try:
            dados = json.loads(manifest_path.read_text(encoding="utf-8"))
            campos_esperados = ("name", "short_name", "start_url", "display", "icons")
            campos_manifest = [c for c in campos_esperados if c in dados]
            manifest_valido = (
                len(campos_manifest) == len(campos_esperados)
                and dados.get("display") == "standalone"
                and isinstance(dados.get("icons"), list)
                and len(dados["icons"]) >= 2
            )
        except (OSError, ValueError, TypeError):
            manifest_valido = False

    return {
        "ok": len(ausentes) == 0 and manifest_valido,
        "pasta_web": str(base),
        "arquivos_verificados": obrigatorios,
        "arquivos_ausentes": ausentes,
        "manifest_valido": manifest_valido,
        "campos_manifest": campos_manifest,
    }


def gerar_config_tauri(porta: int | None = None) -> dict[str, Any]:
    """Gera a configuracao Tauri (v2) para empacotar o Nextor no Windows, Linux e macOS.

    Reaproveita integralmente o PWA universal (`nextor/web`) sem duplicar interface
    e sem incluir tokens ou segredos no repositorio.
    """
    p = porta or config.PORTA
    return {
        "$schema": "https://schema.tauri.app/config/2",
        "productName": "Nextor",
        "version": "0.1.0",
        "identifier": "io.github.thiagoventurim.nextor",
        "build": {
            "frontendDist": "../../nextor/web",
            "devUrl": f"http://localhost:{p}/painel",
        },
        "app": {
            "windows": [
                {
                    "title": "Nextor",
                    "width": 1024,
                    "height": 740,
                    "minWidth": 360,
                    "minHeight": 560,
                    "resizable": True,
                    "fullscreen": False,
                }
            ],
            "security": {
                "csp": "default-src 'self'; connect-src 'self' http://localhost:* http://127.0.0.1:* http://192.168.*:* http://10.*:* http://100.*:*; img-src 'self' data: blob:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'"
            },
        },
        "bundle": {
            "active": True,
            "targets": ["msi", "nsis", "deb", "appimage", "dmg", "app"],
            "icon": [
                "../../nextor/web/icone-192.png",
                "../../nextor/web/icone-512.png",
            ],
        },
    }


def gerar_config_capacitor() -> dict[str, Any]:
    """Gera a configuracao do Capacitor para empacotar o PWA do Nextor em APK Android / iOS."""
    return {
        "appId": "io.github.thiagoventurim.nextor",
        "appName": "Nextor",
        "webDir": "../../nextor/web",
        "bundledWebRuntime": False,
        "server": {
            "androidScheme": "http",
            "cleartext": True,
        },
    }
