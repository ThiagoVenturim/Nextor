"""
Verificacao de voz (opcional): fazer o Nextor so obedecer a voz do dono.

Usa embeddings de voz (resemblyzer). Honestamente: e aproximado e exige um cadastro
de algumas amostras. Se resemblyzer nao estiver instalado, a verificacao fica desligada.

Instalar (pesado, traz torch):  .venv/Scripts/python.exe -m pip install resemblyzer
Cadastrar a sua voz:            .venv/Scripts/python.exe -m nextor.voz_dono
"""
import numpy as np

from . import config

try:
    from resemblyzer import VoiceEncoder, preprocess_wav
    _enc = None
except ImportError:
    VoiceEncoder = None


def _encoder():
    global _enc
    if VoiceEncoder is None:
        raise RuntimeError("resemblyzer nao instalado (pip install resemblyzer).")
    if _enc is None:
        _enc = VoiceEncoder()
    return _enc


def embedding(audio_float32) -> "np.ndarray":
    wav = preprocess_wav(audio_float32, source_sr=16000)
    return _encoder().embed_utterance(wav)


def cadastrar(audio_float32) -> None:
    emb = embedding(audio_float32)
    np.save(config.VOZ_DONO, emb)


def disponivel() -> bool:
    return VoiceEncoder is not None and config.VOZ_DONO.exists()


def e_o_dono(audio_float32, limiar: float = 0.75) -> bool:
    if not disponivel():
        return True  # sem cadastro/lib: nao bloqueia
    dono = np.load(config.VOZ_DONO)
    emb = embedding(audio_float32)
    sim = float(np.dot(dono, emb) / (np.linalg.norm(dono) * np.linalg.norm(emb)))
    return sim >= limiar


if __name__ == "__main__":
    import sounddevice as sd
    print("Cadastro de voz do dono. Fale por ~5 segundos apos o aviso.")
    input("Enter para gravar... ")
    seg = 5
    audio = sd.rec(int(seg * 16000), samplerate=16000, channels=1, dtype="float32")
    sd.wait()
    cadastrar(audio.flatten())
    print(f"Voz cadastrada em {config.VOZ_DONO}.")
