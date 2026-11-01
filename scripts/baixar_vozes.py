"""Baixa as vozes naturais (Piper) dos idiomas do Nextor para models/piper.

    .venv/Scripts/python.exe scripts/baixar_vozes.py            # pt-BR, en-US, es-ES e fr-FR
    .venv/Scripts/python.exe scripts/baixar_vozes.py pt-BR en-US

As vozes vem do repositorio oficial do Piper (cerca de 60 MB cada) e ficam fora do git.
Outras vozes: https://huggingface.co/rhasspy/piper-voices (troque com NEXTOR_VOZ_PT_BR etc.).
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nextor.fala import IDIOMAS, pasta_piper, voz_piper  # noqa: E402


def main(idiomas: list[str]) -> None:
    idiomas = idiomas or list(IDIOMAS)
    desconhecidos = [i for i in idiomas if i not in IDIOMAS]
    if desconhecidos:
        sys.exit(f"Idiomas desconhecidos: {', '.join(desconhecidos)}. Use: {', '.join(IDIOMAS)}")
    destino = pasta_piper()
    destino.mkdir(parents=True, exist_ok=True)
    vozes = [voz_piper(i) for i in idiomas]
    subprocess.run([sys.executable, "-m", "piper.download_voices", "--download-dir", str(destino), *vozes], check=True)
    print(f"Vozes em {destino}: {', '.join(vozes)}")


if __name__ == "__main__":
    main(sys.argv[1:])
