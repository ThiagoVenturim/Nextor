"""
Ouvinte de voz no microfone do computador (offline, Vosk).

Diga "ei Nextor", "fala Nextor", "meu amigo Nextor" (ou "ei Claude", "oi agy"): o rosto abre na tela
e o comando que vem junto, ou logo depois, e executado. Tudo local, sem nuvem.

O ouvinte manda o que ouviu para o servico do Nextor (/comando), que decide, responde com voz e
atualiza o rosto. Se o servico nao estiver rodando, o ouvinte resolve sozinho.

Opcional: so obedecer a voz do dono (ver nextor/voz_dono.py e NEXTOR_VERIFICAR_VOZ).

Rodar (com o servico ja aberto em outro terminal):
    .venv/Scripts/python.exe -m nextor.ouvinte
"""
import json
import queue
import sys
import time
import urllib.request

from . import config
from .chamado import entender

TAXA = 16000


class Escuta:
    """Decide o que fazer com cada frase ouvida.

    Depois de um chamado sem comando ("ei Nextor"), a proxima frase dentro de JANELA_ESCUTA
    segundos vale como comando, sem precisar chamar de novo.
    """

    def __init__(self, janela: float | None = None):
        self.janela = config.JANELA_ESCUTA if janela is None else janela
        self.aberta_ate = 0.0

    def decidir(self, texto: str, agora: float | None = None) -> str | None:
        """Devolve o texto para mandar ao Nextor, ou None para ignorar."""
        agora = time.monotonic() if agora is None else agora
        texto = texto.strip()
        if not texto:
            return None
        chamado = entender(texto)
        if chamado["chamado"]:
            self.aberta_ate = 0.0 if chamado["comando"] else agora + self.janela
            return texto  # o servico entende o chamado, abre o rosto e responde
        if agora <= self.aberta_ate:
            self.aberta_ate = 0.0
            return texto
        return None


def enviar(texto: str) -> str:
    """Manda a frase para o servico do Nextor; sem servico, resolve aqui mesmo."""
    try:
        req = urllib.request.Request(
            f"http://localhost:{config.PORTA}/comando",
            data=json.dumps({"texto": texto}).encode(),
            method="POST",
            headers={"Content-Type": "application/json", "X-Nextor-Token": config.TOKEN},
        )
        with urllib.request.urlopen(req, timeout=180) as r:  # noqa: S310 - servico local
            return json.loads(r.read()).get("resposta", "")
    except Exception as e:
        print(f"[ouvinte] servico indisponivel ({e.__class__.__name__}); respondendo aqui.")
        from .roteador import rotear
        resposta = rotear(texto)["resposta"]
        try:
            from . import fala
            dados, mime, _ = fala.sintetizar(resposta)
            fala.tocar_no_pc(dados, mime)
        except Exception as erro:
            print(f"[ouvinte] sem voz no PC: {erro}")
        return resposta


def _e_o_dono(buf) -> bool:
    if not config.VERIFICAR_VOZ:
        return True
    try:
        import numpy as np
        from .voz_dono import e_o_dono
        return e_o_dono(np.array(buf, dtype="float32"))
    except Exception as e:
        print(f"[ouvinte] verificacao de voz indisponivel ({e}); seguindo.")
        return True


def ouvir() -> None:
    import numpy as np
    import sounddevice as sd
    import vosk

    model = vosk.Model(config.VOSK_MODELO)
    rec = vosk.KaldiRecognizer(model, TAXA)
    rec.SetWords(False)
    q = queue.Queue()
    escuta = Escuta()

    def cb(indata, frames, t, status):
        q.put(bytes(indata))

    print('[ouvinte] ouvindo... diga "ei Nextor" e o comando.')
    audio_atual = bytearray()
    with sd.RawInputStream(samplerate=TAXA, blocksize=8000, dtype="int16", channels=1, callback=cb):
        while True:
            data = q.get()
            audio_atual.extend(data)
            if not rec.AcceptWaveform(data):
                continue
            texto = json.loads(rec.Result()).get("text", "").strip()
            buf = np.frombuffer(bytes(audio_atual), dtype="int16").astype("float32") / 32768.0
            audio_atual = bytearray()
            frase = escuta.decidir(texto)
            if frase is None:
                continue
            if not _e_o_dono(buf):
                print("[ouvinte] voz nao reconhecida como a do dono; ignorando.")
                continue
            print(f"[ouvinte] ouvi: {frase}")
            print(f"[ouvinte] Nextor: {enviar(frase)}")


def main() -> None:
    try:
        ouvir()
    except KeyboardInterrupt:
        print("\n[ouvinte] encerrado.")
        sys.exit(0)


if __name__ == "__main__":
    main()
