"""Modulo de gravacao e transcricao de aulas para o modo Estudos."""
import json
import os
import queue
import threading
import time
import wave
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import config, estudos

try:
    import sounddevice as sd
except Exception:
    sd = None

try:
    import numpy as np
except Exception:
    np = None

try:
    import vosk
except Exception:
    vosk = None

AVISO_CONSENTIMENTO = (
    "Aviso de consentimento: gravar aulas exige autorizacao previa do professor "
    "e da instituicao de ensino."
)
TAXA_AMOSTRAGEM = 16000


def formatar_segundos(segundos: float) -> str:
    """Formata segundos no formato MM:SS ou HH:MM:SS."""
    s = int(segundos)
    horas = s // 3600
    minutos = (s % 3600) // 60
    segs = s % 60
    if horas > 0:
        return f"{horas:02d}:{minutos:02d}:{segs:02d}"
    return f"{minutos:02d}:{segs:02d}"


def transcrever_audio(
    caminho_wav: Path,
    transcritor_fake: Optional[Callable[[Path], List[Dict[str, Any]]]] = None,
    modelo_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Transcreve arquivo de audio WAV em trechos timestamped (inicio, fim, texto)."""
    if transcritor_fake is not None:
        return transcritor_fake(caminho_wav)

    if not caminho_wav.exists():
        return []

    caminho_modelo = modelo_path or config.VOSK_MODELO
    if vosk is None or not Path(caminho_modelo).exists():
        # Fallback informativo se o modelo Vosk local nao estiver baixado
        return [
            {
                "inicio": "00:00",
                "fim": "00:10",
                "texto": "Audio gravado. Transcricao local pendente do modelo Vosk.",
            }
        ]

    try:
        wf = wave.open(str(caminho_wav), "rb")
    except Exception:
        return []

    trechos: List[Dict[str, Any]] = []
    try:
        model = vosk.Model(str(caminho_modelo))
        rec = vosk.KaldiRecognizer(model, wf.getframerate())
        rec.SetWords(True)

        bloco_tamanho = 4000
        taxa = wf.getframerate()
        frames_lidos = 0

        while True:
            data = wf.readframes(bloco_tamanho)
            if len(data) == 0:
                break
            frames_lidos += len(data) // 2
            if rec.AcceptWaveform(data):
                res = json.loads(rec.Result())
                texto = res.get("text", "").strip()
                if texto:
                    palavras = res.get("result", [])
                    if palavras:
                        t_ini = formatar_segundos(palavras[0].get("start", 0.0))
                        t_fim = formatar_segundos(palavras[-1].get("end", 0.0))
                    else:
                        segundo_atual = frames_lidos / taxa
                        t_ini = formatar_segundos(max(0.0, segundo_atual - 5.0))
                        t_fim = formatar_segundos(segundo_atual)
                    trechos.append({"inicio": t_ini, "fim": t_fim, "texto": texto})

        res_final = json.loads(rec.FinalResult())
        texto_final = res_final.get("text", "").strip()
        if texto_final:
            palavras = res_final.get("result", [])
            segundo_atual = frames_lidos / taxa if taxa else 0.0
            if palavras:
                t_ini = formatar_segundos(palavras[0].get("start", 0.0))
                t_fim = formatar_segundos(palavras[-1].get("end", segundo_atual))
            else:
                t_ini = formatar_segundos(max(0.0, segundo_atual - 5.0))
                t_fim = formatar_segundos(segundo_atual)
            trechos.append({"inicio": t_ini, "fim": t_fim, "texto": texto_final})
    except Exception:
        pass
    finally:
        wf.close()

    return trechos


class GravadorAula:
    """Controla a gravacao de audio de uma aula com consentimento e indicador de estado."""

    def __init__(self):
        self._gravando = False
        self._disciplina = ""
        self._inicio = 0.0
        self._lock = threading.Lock()
        self._frames: List[bytes] = []
        self._stream = None
        self._thread = None
        self._fila: queue.Queue = queue.Queue()

    @property
    def gravando(self) -> bool:
        with self._lock:
            return self._gravando

    @property
    def disciplina(self) -> str:
        with self._lock:
            return self._disciplina

    def iniciar(
        self,
        disciplina: str,
        backend_gravador: Optional[Callable[[], Any]] = None,
    ) -> Dict[str, Any]:
        nome_disc = disciplina.strip()
        if not nome_disc:
            return {"ok": False, "erro": "Nome da disciplina obrigatorio para iniciar gravacao."}

        with self._lock:
            if self._gravando:
                return {
                    "ok": False,
                    "erro": f"Ja existe uma gravacao em andamento para {self._disciplina}.",
                }
            self._gravando = True
            self._disciplina = nome_disc
            self._inicio = time.time()
            self._frames = []
            self._fila = queue.Queue()

        # Atualiza o indicador claro de gravacao no companheiro
        try:
            from .companheiro import companheiro
            companheiro.atualizar(
                atividade="gravando_aula",
                detalhe=f"Gravando aula de {nome_disc}",
            )
        except Exception:
            pass

        if backend_gravador is not None:
            backend_gravador()
        elif sd is not None:
            def _loop_gravacao():
                def _callback(indata, frames, t, status):
                    if self.gravando:
                        self._fila.put(bytes(indata))

                try:
                    with sd.RawInputStream(
                        samplerate=TAXA_AMOSTRAGEM,
                        channels=1,
                        dtype="int16",
                        callback=_callback,
                    ):
                        while self.gravando:
                            try:
                                data = self._fila.get(timeout=0.2)
                                self._frames.append(data)
                            except queue.Empty:
                                continue
                except Exception:
                    pass

            self._thread = threading.Thread(target=_loop_gravacao, daemon=True)
            self._thread.start()

        return {
            "ok": True,
            "disciplina": nome_disc,
            "gravando": True,
            "consentimento": AVISO_CONSENTIMENTO,
            "aviso": f"{AVISO_CONSENTIMENTO} Iniciando gravacao da aula de {nome_disc}.",
        }

    def parar(
        self,
        transcritor_fake: Optional[Callable[[Path], List[Dict[str, Any]]]] = None,
        base_dir: Optional[Path] = None,
        caminho_db: Optional[Path] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            if not self._gravando:
                return {"ok": False, "erro": "Nenhuma gravacao em andamento."}
            self._gravando = False
            disciplina = self._disciplina
            frames = list(self._frames)
            self._frames = []

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

        # Restaura o estado normal do companheiro
        try:
            from .companheiro import companheiro
            companheiro.atualizar(atividade="normal", detalhe="")
        except Exception:
            pass

        pasta_disc = estudos.obter_pasta_disciplina(disciplina, base_dir=base_dir)
        carimbo = datetime.now().strftime("%Y%m%d_%H%M%S")
        arquivo_wav = pasta_disc / f"aula_{carimbo}.wav"

        # Salva o audio em WAV 16kHz mono PCM 16-bit
        with wave.open(str(arquivo_wav), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(TAXA_AMOSTRAGEM)
            if frames:
                wf.writeframes(b"".join(frames))
            else:
                # Se vazio (ex: em teste offline), grava 1s de silencio
                wf.writeframes(b"\x00" * (TAXA_AMOSTRAGEM * 2))

        # Transcricao do audio
        trechos = transcrever_audio(arquivo_wav, transcritor_fake=transcritor_fake)

        # Monta arquivo de texto da transcricao com carimbos de horario
        linhas_texto = [
            f"# Aula de {disciplina}",
            f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
            f"Arquivo de audio: {arquivo_wav.name}",
            f"{AVISO_CONSENTIMENTO}",
            "",
            "## Transcricao",
        ]
        if trechos:
            for t in trechos:
                linhas_texto.append(f"[{t['inicio']} - {t['fim']}] {t['texto']}")
        else:
            linhas_texto.append("[00:00 - 00:00] Nenhum trecho falado reconhecido.")

        conteudo_transcricao = "\n".join(linhas_texto)
        arquivo_txt = pasta_disc / f"aula_{carimbo}_transcricao.txt"
        arquivo_txt.write_text(conteudo_transcricao, encoding="utf-8")

        # Indexa na biblioteca de estudos
        res_import = estudos.importar_material(
            disciplina_nome=disciplina,
            origem=arquivo_txt,
            titulo=f"Aula {disciplina} - {carimbo}",
            tipo="txt",
            base_dir=base_dir,
            caminho_db=caminho_db,
            pastas_autorizadas=[pasta_disc],
            canal="local",
        )

        return {
            "ok": True,
            "disciplina": disciplina,
            "caminho_audio": str(arquivo_wav),
            "caminho_transcricao": str(arquivo_txt),
            "trechos": trechos,
            "material_id": res_import.get("id"),
            "aviso": f"Gravacao da aula de {disciplina} encerrada e transcrita com sucesso.",
        }

    def status(self) -> Dict[str, Any]:
        with self._lock:
            duracao = int(time.time() - self._inicio) if self._gravando else 0
            return {
                "gravando": self._gravando,
                "disciplina": self._disciplina,
                "duracao_segundos": duracao,
            }


gravador = GravadorAula()


def iniciar_gravacao(
    disciplina: str,
    backend_gravador: Optional[Callable[[], Any]] = None,
) -> Dict[str, Any]:
    return gravador.iniciar(disciplina, backend_gravador=backend_gravador)


def parar_gravacao(
    transcritor_fake: Optional[Callable[[Path], List[Dict[str, Any]]]] = None,
    base_dir: Optional[Path] = None,
    caminho_db: Optional[Path] = None,
) -> Dict[str, Any]:
    return gravador.parar(
        transcritor_fake=transcritor_fake,
        base_dir=base_dir,
        caminho_db=caminho_db,
    )


def status_gravacao() -> Dict[str, Any]:
    return gravador.status()
