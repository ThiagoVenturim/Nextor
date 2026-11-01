"""Voz do Nextor no computador: sintese natural (Piper, local) em pt-BR, ingles, espanhol e frances.

Motores, do melhor para o mais simples:
- piper: voz neural local e gratuita (pip install piper-tts + scripts/baixar_vozes.py);
- sapi: vozes do Windows (offline, mais roboticas);
- gtts: Google Text-to-Speech (precisa de internet).

O audio vai para a tela do rosto (que toca e mexe a boca) ou direto para as caixas de som do PC.
"""
import io
import itertools
import os
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

from . import config

IDIOMAS = {
    "pt-BR": {"nome": "Portugues", "piper": "pt_BR-faber-medium", "gtts": ("pt", "com.br"),
              "instrucao": "Responda em portugues do Brasil."},
    "en-US": {"nome": "English", "piper": "en_US-lessac-medium", "gtts": ("en", "com"),
              "instrucao": "Answer in English."},
    "es-ES": {"nome": "Espanol", "piper": "es_ES-davefx-medium", "gtts": ("es", "es"),
              "instrucao": "Responde en espanol."},
    "fr-FR": {"nome": "Francais", "piper": "fr_FR-siwis-medium", "gtts": ("fr", "fr"),
              "instrucao": "Reponds en francais."},
}
PADRAO = "pt-BR"


def _env(nome: str, padrao: str = "") -> str:
    return os.getenv(nome, padrao).strip()


def idioma_inicial() -> str:
    valor = _env("NEXTOR_IDIOMA", PADRAO)
    return valor if valor in IDIOMAS else PADRAO


def pasta_piper() -> Path:
    return Path(_env("NEXTOR_PIPER_DIR") or (config.RAIZ / "models" / "piper"))


def voz_piper(idioma: str) -> str:
    """Nome da voz Piper do idioma; troque com NEXTOR_VOZ_PT_BR=pt_BR-edresson-low etc."""
    return _env(f"NEXTOR_VOZ_{idioma.replace('-', '_').upper()}") or IDIOMAS[idioma]["piper"]


# ----------------------------------------------------------------------------- motores

_vozes_carregadas: dict[str, object] = {}
_trava_piper = threading.Lock()


def _piper(texto: str, idioma: str) -> tuple[bytes, str]:
    modelo = pasta_piper() / f"{voz_piper(idioma)}.onnx"
    if not modelo.is_file():
        raise FileNotFoundError(f"voz {modelo.name} nao baixada (rode scripts/baixar_vozes.py)")
    from piper import PiperVoice
    with _trava_piper:
        voz = _vozes_carregadas.get(str(modelo))
        if voz is None:
            voz = _vozes_carregadas[str(modelo)] = PiperVoice.load(str(modelo))
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            voz.synthesize_wav(texto, w)
    return buf.getvalue(), "audio/wav"


def _sapi(texto: str, idioma: str) -> tuple[bytes, str]:
    if sys.platform != "win32":
        raise RuntimeError("vozes SAPI so no Windows")
    with tempfile.TemporaryDirectory() as tmp:
        arq = Path(tmp) / "fala.wav"
        entrada = Path(tmp) / "texto.txt"
        entrada.write_text(texto, encoding="utf-8")
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$v = $s.GetInstalledVoices() | Where-Object {{ $_.VoiceInfo.Culture.Name -eq '{idioma}' }} | Select-Object -First 1; "
            "if ($v) { $s.SelectVoice($v.VoiceInfo.Name) }; "
            f"$s.SetOutputToWaveFile('{arq}'); "
            f"$s.Speak([IO.File]::ReadAllText('{entrada}')); $s.Dispose()"
        )
        subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                       check=True, capture_output=True, timeout=60)
        return arq.read_bytes(), "audio/wav"


def _gtts(texto: str, idioma: str) -> tuple[bytes, str]:
    from gtts import gTTS
    lang, tld = IDIOMAS[idioma]["gtts"]
    buf = io.BytesIO()
    gTTS(text=texto, lang=lang, tld=tld).write_to_fp(buf)
    return buf.getvalue(), "audio/mpeg"


MOTORES = {"piper": _piper, "sapi": _sapi, "gtts": _gtts}


def sintetizar(texto: str, idioma: str = PADRAO, motor: str | None = None) -> tuple[bytes, str, str]:
    """Gera o audio. Tenta o motor pedido (ou piper, sapi, gtts) e devolve (bytes, mime, motor usado)."""
    idioma = idioma if idioma in IDIOMAS else PADRAO
    escolhido = (motor or _env("NEXTOR_VOZ_MOTOR", "auto")).lower()
    ordem = [escolhido] if escolhido in MOTORES else ["piper", "sapi", "gtts"]
    erros = []
    for nome in ordem:
        try:
            dados, mime = MOTORES[nome](texto, idioma)
            return dados, mime, nome
        except Exception as e:
            erros.append(f"{nome}: {e}")
    raise RuntimeError("; ".join(erros))


def duracao(dados: bytes, mime: str, texto: str) -> float:
    if mime == "audio/wav":
        try:
            with wave.open(io.BytesIO(dados)) as w:
                return w.getnframes() / float(w.getframerate())
        except wave.Error:
            pass
    return max(1.5, len(texto) / 14.0)  # estimativa: ~14 caracteres por segundo


# ----------------------------------------------------------------------------- audios servidos

_contador = itertools.count(1)
_audios: dict[str, tuple[bytes, str]] = {}
MAX_AUDIOS = 10


def guardar(dados: bytes, mime: str) -> str:
    fala_id = f"{int(time.time())}-{next(_contador)}"
    _audios[fala_id] = (dados, mime)
    while len(_audios) > MAX_AUDIOS:
        _audios.pop(next(iter(_audios)))
    return fala_id


def pegar(fala_id: str) -> tuple[bytes, str] | None:
    return _audios.get(fala_id)


def tocar_no_pc(dados: bytes, mime: str) -> None:
    """Toca direto nas caixas de som do Windows (quando nenhuma tela do rosto esta aberta)."""
    if sys.platform != "win32" or mime != "audio/wav":
        raise RuntimeError("tocar direto so funciona com WAV no Windows")
    import winsound
    winsound.PlaySound(dados, winsound.SND_MEMORY)
