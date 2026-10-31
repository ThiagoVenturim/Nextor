"""Voz do Nextor: gera a fala (gTTS) e envia ao Nest pela rede local (catt)."""
import sys
import subprocess

from . import config

try:
    from gtts import gTTS
except ImportError:
    gTTS = None


def _catt() -> str:
    return str(config.CATT) if config.CATT.exists() else "catt"


def falar(texto: str) -> None:
    if gTTS is None:
        raise RuntimeError("Falta gTTS: pip install -r requirements.txt")
    print(f"Nextor diz: {texto}")
    gTTS(text=texto, lang="pt", tld="com.br").save(str(config.MP3))
    catt = _catt()
    try:
        subprocess.run([catt, "-d", config.DISPOSITIVO, "cast", str(config.MP3)],
                       check=True, capture_output=True, text=True, timeout=90)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        # Nest pode ter ficado preso num cast anterior: limpa e tenta de novo.
        subprocess.run([catt, "-d", config.DISPOSITIVO, "stop"], capture_output=True, timeout=30)
        subprocess.run([catt, "-d", config.DISPOSITIVO, "cast", str(config.MP3)],
                       check=True, capture_output=True, text=True, timeout=90)
    print("Enviado ao Nest.")


FRASE_PADRAO = (
    "Oi. Eu sou o Nextor, seu assistente. "
    "Esta e a primeira vez que falo com voce pelo Nest. A partir de agora, a gente conversa."
)


if __name__ == "__main__":
    texto = " ".join(sys.argv[1:]).strip() or FRASE_PADRAO
    falar(texto)
