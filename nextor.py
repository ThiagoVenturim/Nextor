"""
Nextor - voz: faz o Google Nest Mini falar um texto, a partir do notebook.

Gera a voz em portugues (gTTS) e envia o audio ao Nest pela rede local (catt).
Uso:
    python nextor.py "texto que o Nextor vai falar"
    python nextor.py            # fala a frase de apresentacao

Nada e instalado no Nest. O audio e gerado localmente e transmitido via Google Cast.
"""
import sys
import subprocess
from pathlib import Path

try:
    from gtts import gTTS
except ImportError:
    sys.exit("Falta a biblioteca gTTS. Rode: .venv/Scripts/python.exe -m pip install gTTS catt")

try:
    from settings import DISPOSITIVO
except ImportError:
    DISPOSITIVO = "Nome do dispositivo no Google Home"

PASTA = Path(__file__).resolve().parent
ARQUIVO_MP3 = PASTA / "nextor_fala.mp3"
CATT = PASTA / ".venv" / "Scripts" / "catt.exe"

FRASE_PADRAO = (
    "Oi Thiago. Eu sou o Nextor, seu assistente. "
    "Esta e a primeira vez que falo com voce pelo Nest. A partir de agora, a gente conversa."
)


def _catt() -> str:
    return str(CATT) if CATT.exists() else "catt"


def falar(texto: str) -> None:
    print(f"Nextor diz: {texto}")
    gTTS(text=texto, lang="pt", tld="com.br").save(str(ARQUIVO_MP3))
    catt = _catt()
    try:
        subprocess.run([catt, "-d", DISPOSITIVO, "cast", str(ARQUIVO_MP3)],
                       check=True, capture_output=True, text=True, timeout=90)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        # Nest pode ter ficado preso num cast anterior: limpa e tenta de novo.
        subprocess.run([catt, "-d", DISPOSITIVO, "stop"], capture_output=True, timeout=30)
        subprocess.run([catt, "-d", DISPOSITIVO, "cast", str(ARQUIVO_MP3)],
                       check=True, capture_output=True, text=True, timeout=90)
    print("Enviado ao Nest.")


if __name__ == "__main__":
    texto = " ".join(sys.argv[1:]).strip() or FRASE_PADRAO
    falar(texto)
