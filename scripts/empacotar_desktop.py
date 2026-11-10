"""Valida o PWA universal e prepara as configuracoes de empacotamento desktop e mobile.

Uso:
  python scripts/empacotar_desktop.py
  python scripts/empacotar_desktop.py --plataforma windows
  python scripts/empacotar_desktop.py --abrir
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from nextor import janela, multiplataforma


def sincronizar_arquivos_empacotamento(pasta_packaging: Path | None = None) -> dict[str, str]:
    base = pasta_packaging or multiplataforma.PACKAGING_DIR
    tauri_dir = base / "desktop"
    android_dir = base / "android"
    tauri_dir.mkdir(parents=True, exist_ok=True)
    android_dir.mkdir(parents=True, exist_ok=True)

    tauri_path = tauri_dir / "tauri.conf.json"
    cap_path = android_dir / "capacitor.config.json"

    tauri_path.write_text(
        json.dumps(multiplataforma.gerar_config_tauri(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    cap_path.write_text(
        json.dumps(multiplataforma.gerar_config_capacitor(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "tauri": str(tauri_path),
        "capacitor": str(cap_path),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verifica e prepara o empacotamento multiplataforma do Nextor.")
    parser.add_argument(
        "--plataforma",
        default="todas",
        help="Plataforma alvo: web, windows, linux, macos, android, ios ou todas.",
    )
    parser.add_argument(
        "--abrir",
        action="store_true",
        help="Abre o painel PWA em janela dedicada no desktop atual.",
    )
    args = parser.parse_args(argv)

    status_pwa = multiplataforma.verificar_requisitos_pwa()
    if not status_pwa["ok"]:
        print(f"Erro: ativos do PWA incompletos. Ausentes: {status_pwa['arquivos_ausentes']}")
        return 1

    arqs = sincronizar_arquivos_empacotamento()
    print(f"PWA universal validado em: {status_pwa['pasta_web']}")
    print(f"Configuracao desktop (Tauri): {arqs['tauri']}")
    print(f"Configuracao mobile (Capacitor): {arqs['capacitor']}")

    if args.plataforma != "todas":
        plat = multiplataforma.obter_plataforma(args.plataforma)
        if not plat:
            print(f"Plataforma desconhecida: {args.plataforma}")
            return 2
        print(f"\nPassos para {plat['nome']} ({', '.join(plat['formatos'])}):")
        for idx, passo in enumerate(plat.get("passos_instalacao", []), start=1):
            print(f"  {idx}. {passo}")

    if args.abrir:
        janela.abrir_app("/painel")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
