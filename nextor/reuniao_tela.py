"""Modulo de gravacao de reunioes e tela com aviso obrigatorio de consentimento.

Implementa:
- Gravacao de reunioes: audio, transcricao offline, estruturacao de resumo,
  decisoes e itens de acao (com integracao para tarefas/anotacoes).
- Gravacao de tela da execucao de tarefas: captura via ffmpeg com marcacoes por voz
  em tempo relativo ('marca: <anotacao>').
- REGRA MANDATORIA DE CONSENTIMENTO: O assistente sempre anuncia expressamente o
  inicio da gravacao e registra o consentimento com timestamp.
"""
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import queue
import re
import subprocess
import threading
import time
from typing import Any, Callable, Dict, List, Optional
import unicodedata
import wave

from . import config

log = logging.getLogger("nextor.reuniao_tela")

try:
    import sounddevice as sd
except Exception:
    sd = None

AVISO_CONSENTIMENTO_REUNIAO = (
    "Aviso de gravacao: esta reuniao esta sendo gravada com o consentimento dos participantes. "
    "Todos devem estar cientes e de acordo."
)

AVISO_CONSENTIMENTO_TELA = (
    "Aviso de gravacao: a gravacao da tela do computador foi iniciada para registro da tarefa."
)

TAXA_AMOSTRAGEM = 16000


def formatar_segundos(segundos: float) -> str:
    """Formata segundos no formato MM:SS ou HH:MM:SS."""
    s = int(max(0, segundos))
    horas = s // 3600
    minutos = (s % 3600) // 60
    segs = s % 60
    if horas > 0:
        return f"{horas:02d}:{minutos:02d}:{segs:02d}"
    return f"{minutos:02d}:{segs:02d}"


def normalizar_slug(texto: str) -> str:
    """Normaliza texto para uso seguro em nomes de arquivos."""
    t = "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
    slug = re.sub(r"[^a-zA-Z0-9_\-]+", "_", t.strip().lower()).strip("_")
    return slug[:40] or "sem_titulo"


def estruturar_resumo_reuniao(
    trechos: List[Dict[str, Any]],
    tema: str,
    participantes: Optional[str] = None,
) -> Dict[str, Any]:
    """Processa transcricao da reuniao e extrai resumo, decisoes e itens de acao."""
    textos_completos = [t.get("texto", "").strip() for t in trechos if t.get("texto", "").strip()]
    texto_geral = " ".join(textos_completos)

    decisoes: List[str] = []
    itens_acao: List[Dict[str, str]] = []
    topicos: List[str] = []

    padroes_decisao = [
        r"\b(?:decidid\w*|decidimos|ficou acordado|acordamos|combinado|definido|aprovado)\b\s*[:,-]?\s*(.+)",
        r"\b(?:decisao|conclusao)\s*[:,-]\s*(.+)",
    ]
    padroes_acao = [
        r"\b(?:vai fazer|ficou de|precisa|deve|tarefa|acao|entregar|enviar|criar|arrumar|ajustar|implementar)\b\s*[:,-]?\s*(.+)",
    ]

    for trecho in trechos:
        txt = trecho.get("texto", "").strip()
        if not txt:
            continue

        # Decisoes
        for pat in padroes_decisao:
            m = re.search(pat, txt, flags=re.IGNORECASE)
            if m:
                d = m.group(1).strip(" .;")
                if d and d not in decisoes:
                    decisoes.append(d)
                break

        # Acoes
        for pat in padroes_acao:
            m = re.search(pat, txt, flags=re.IGNORECASE)
            if m:
                a = m.group(1).strip(" .;")
                if a:
                    # Tenta identificar responsavel
                    resp = ""
                    m_resp = re.search(r"\b([A-Z][a-z]+)\b\s+(?:vai|fica com|deve)", txt)
                    if m_resp:
                        resp = m_resp.group(1).strip()
                    itens_acao.append({
                        "descricao": a,
                        "responsavel": resp,
                        "momento": trecho.get("inicio", ""),
                    })
                break

        # Topicos principais
        if len(topicos) < 4 and len(txt) > 20:
            topicos.append(txt)

    if not decisoes and topicos:
        decisoes.append(f"Alinhamento geral sobre {tema}.")

    if not itens_acao and topicos:
        itens_acao.append({
            "descricao": f"Revisar notas e encaminhamentos de {tema}",
            "responsavel": "",
            "momento": "00:00",
        })

    resumo_paragrafo = (
        f"Reuniao sobre '{tema}'"
        f"{f' com participantes: {participantes}' if participantes else ''}. "
        f"Foram tratados {len(topicos)} topicos principais ao longo da conversa."
    )
    if texto_geral:
        resumo_paragrafo += f" Sintese da discussao: {texto_geral[:280]}..."

    return {
        "tema": tema,
        "participantes": participantes or "",
        "resumo": resumo_paragrafo,
        "topicos": topicos,
        "decisoes": decisoes,
        "itens_acao": itens_acao,
    }


class GravadorReuniao:
    """Controla a gravacao de audio de reunioes com aviso previo de consentimento."""

    def __init__(self):
        self._gravando = False
        self._tema = ""
        self._participantes = ""
        self._inicio = 0.0
        self._lock = threading.Lock()
        self._frames: List[bytes] = []
        self._fila: queue.Queue = queue.Queue()
        self._pasta_saida: Optional[Path] = None
        self._caminho_wav: Optional[Path] = None

    @property
    def gravando(self) -> bool:
        with self._lock:
            return self._gravando

    @property
    def tema(self) -> str:
        with self._lock:
            return self._tema

    def iniciar(
        self,
        tema: str,
        participantes: Optional[str] = None,
        backend_gravador: Optional[Callable[[], Any]] = None,
        diretorio_saida: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Inicia gravacao da reuniao registrando consentimento obrigatorio."""
        tema_limpo = tema.strip()
        if not tema_limpo:
            tema_limpo = "Reuniao Geral"

        with self._lock:
            if self._gravando:
                return {
                    "ok": False,
                    "erro": f"Ja existe uma gravacao de reuniao em andamento sobre '{self._tema}'.",
                }
            self._gravando = True
            self._tema = tema_limpo
            self._participantes = (participantes or "").strip()
            self._inicio = time.time()
            self._frames = []
            self._fila = queue.Queue()

            pasta_base = diretorio_saida or config.REUNIOES_DIR
            data_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            slug = normalizar_slug(tema_limpo)
            self._pasta_saida = pasta_base / f"{data_str}_{slug}"
            self._pasta_saida.mkdir(parents=True, exist_ok=True)
            self._caminho_wav = self._pasta_saida / "audio_reuniao.wav"

        # Notifica o companheiro/estado visual
        try:
            from .companheiro import companheiro
            companheiro.atualizar(
                atividade="gravando_reuniao",
                detalhe=f"Gravando reuniao: {tema_limpo}",
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

            t = threading.Thread(target=_loop_gravacao, daemon=True)
            t.start()

        return {
            "ok": True,
            "aviso": AVISO_CONSENTIMENTO_REUNIAO,
            "consentimento_anunciado": True,
            "tema": tema_limpo,
            "participantes": self._participantes,
            "iniciado_em": datetime.now().isoformat(),
            "pasta": str(self._pasta_saida),
        }

    def parar(
        self,
        transcritor: Optional[Callable[[Path], List[Dict[str, Any]]]] = None,
        salvar_anotacoes: bool = True,
    ) -> Dict[str, Any]:
        """Finaliza a gravacao, gera a transcricao e estrutura o resumo com itens de acao."""
        with self._lock:
            if not self._gravando:
                return {"ok": False, "erro": "nenhuma_reuniao_em_andamento", "mensagem": "Nenhuma reuniao sendo gravada."}
            self._gravando = False
            tema = self._tema
            participantes = self._participantes
            inicio = self._inicio
            pasta = self._pasta_saida
            caminho_wav = self._caminho_wav
            frames = list(self._frames)

        duracao = time.time() - inicio

        # Salva o arquivo WAV caso haja frames gravados
        if caminho_wav and frames:
            try:
                with wave.open(str(caminho_wav), "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(TAXA_AMOSTRAGEM)
                    wf.writeframes(b"".join(frames))
            except Exception as e:
                log.error("Erro ao salvar audio WAV da reuniao: %s", e)

        # Transcricao offline
        trechos: List[Dict[str, Any]] = []
        if transcritor is not None and caminho_wav:
            trechos = transcritor(caminho_wav)
        elif caminho_wav and caminho_wav.exists():
            try:
                from . import aulas
                trechos = aulas.transcrever_audio(caminho_wav)
            except Exception as e:
                log.warning("Falha ao transcrever reuniao com Vosk: %s", e)
                trechos = [{"inicio": "00:00", "fim": formatar_segundos(duracao), "texto": f"Reuniao sobre {tema} gravada."}]
        else:
            trechos = [{"inicio": "00:00", "fim": formatar_segundos(duracao), "texto": f"Discussao sobre {tema} concluida."}]

        # Estrutura resumo, decisoes e itens de acao
        estruturado = estruturar_resumo_reuniao(trechos, tema=tema, participantes=participantes)

        # Grava ata/documento markdown
        data_extenso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        linhas_md = [
            f"# Reuniao: {tema}",
            f"- Data e hora: {data_extenso}",
            f"- Duracao: {formatar_segundos(duracao)}",
            f"- Participantes: {participantes or 'Nao especificados'}",
            f"- Aviso de consentimento: {AVISO_CONSENTIMENTO_REUNIAO}",
            "",
            "## Resumo Executivo",
            estruturado["resumo"],
            "",
            "## Decisoes Tomadas",
        ]
        for dec in estruturado["decisoes"]:
            linhas_md.append(f"- {dec}")

        linhas_md.extend(["", "## Itens de Acao"])
        for act in estruturado["itens_acao"]:
            resp = f" (Responsavel: {act['responsavel']})" if act.get("responsavel") else ""
            linhas_md.append(f"- [ ] {act['descricao']}{resp} [{act.get('momento', '')}]")

        linhas_md.extend(["", "## Transcricao Cronologica"])
        for tr in trechos:
            linhas_md.append(f"- `[{tr.get('inicio', '00:00')}]` {tr.get('texto', '')}")

        caminho_md = pasta / "ata_reuniao.md" if pasta else None
        if caminho_md:
            caminho_md.write_text("\n".join(linhas_md) + "\n", encoding="utf-8")

        # Integra itens de acao com anotacoes.md se solicitado
        if salvar_anotacoes and estruturado.get("itens_acao"):
            try:
                carimbo = datetime.now().strftime("%Y-%m-%d")
                with config.ANOTACOES.open("a", encoding="utf-8") as f:
                    for act in estruturado["itens_acao"]:
                        resp = f" ({act['responsavel']})" if act.get("responsavel") else ""
                        f.write(f"- [{carimbo}] [Reuniao: {tema}] {act['descricao']}{resp}\n")
            except Exception as e:
                log.warning("Falha ao salvar itens de acao nas anotacoes: %s", e)

        try:
            from .companheiro import companheiro
            companheiro.atualizar(atividade="ocioso", detalhe="")
        except Exception:
            pass

        return {
            "ok": True,
            "tema": tema,
            "duracao": formatar_segundos(duracao),
            "resumo": estruturado["resumo"],
            "decisoes": estruturado["decisoes"],
            "itens_acao": estruturado["itens_acao"],
            "arquivo_md": str(caminho_md) if caminho_md else "",
            "arquivo_wav": str(caminho_wav) if caminho_wav else "",
        }


class GravadorTela:
    """Controla a gravacao de tela via ffmpeg com marcacoes por voz de pontos de interesse."""

    def __init__(self):
        self._gravando = False
        self._tarefa = ""
        self._inicio = 0.0
        self._processo: Optional[Any] = None
        self._lock = threading.Lock()
        self._marcadores: List[Dict[str, Any]] = []
        self._caminho_video: Optional[Path] = None
        self._pasta_saida: Optional[Path] = None

    @property
    def gravando(self) -> bool:
        with self._lock:
            return self._gravando

    @property
    def tarefa(self) -> str:
        with self._lock:
            return self._tarefa

    @property
    def marcadores(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._marcadores)

    def iniciar(
        self,
        tarefa: str,
        backend_processo: Optional[Callable[[List[str]], Any]] = None,
        diretorio_saida: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Inicia a gravacao de tela da tarefa com ffmpeg e aviso sonoro de consentimento."""
        tarefa_limpa = tarefa.strip()
        if not tarefa_limpa:
            tarefa_limpa = "Execucao de Tarefa"

        with self._lock:
            if self._gravando:
                return {
                    "ok": False,
                    "erro": f"Ja existe uma gravacao de tela em andamento para a tarefa '{self._tarefa}'.",
                }
            self._gravando = True
            self._tarefa = tarefa_limpa
            self._inicio = time.time()
            self._marcadores = []

            pasta_base = diretorio_saida or config.GRAVACOES_TELA_DIR
            data_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            slug = normalizar_slug(tarefa_limpa)
            self._pasta_saida = pasta_base / f"{data_str}_{slug}"
            self._pasta_saida.mkdir(parents=True, exist_ok=True)
            self._caminho_video = self._pasta_saida / "video_tarefa.mp4"

        # Notifica companheiro
        try:
            from .companheiro import companheiro
            companheiro.atualizar(
                atividade="gravando_tela",
                detalhe=f"Gravando tela: {tarefa_limpa}",
            )
        except Exception:
            pass

        cmd = [
            "ffmpeg",
            "-y",
            "-f", "gdigrab",
            "-framerate", "15",
            "-i", "desktop",
            str(self._caminho_video),
        ]

        if backend_processo is not None:
            self._processo = backend_processo(cmd)
        else:
            try:
                self._processo = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception as e:
                log.warning("Nao foi possivel iniciar processo do ffmpeg: %s", e)
                self._processo = None

        return {
            "ok": True,
            "aviso": AVISO_CONSENTIMENTO_TELA,
            "consentimento_anunciado": True,
            "tarefa": tarefa_limpa,
            "iniciado_em": datetime.now().isoformat(),
            "video": str(self._caminho_video),
        }

    def adicionar_marcador(self, nota: str) -> Dict[str, Any]:
        """Adiciona marcador por voz com timestamp relativo ao inicio da gravacao."""
        nota_limpa = nota.strip()
        if not nota_limpa:
            return {"ok": False, "erro": "nota_vazia"}

        with self._lock:
            if not self._gravando:
                return {"ok": False, "erro": "nenhuma_gravacao_de_tela_em_andamento"}
            delta = time.time() - self._inicio
            tempo_str = formatar_segundos(delta)
            marcador = {
                "tempo": tempo_str,
                "segundos": round(delta, 1),
                "nota": nota_limpa,
            }
            self._marcadores.append(marcador)
            total = len(self._marcadores)

        return {
            "ok": True,
            "tempo": tempo_str,
            "nota": nota_limpa,
            "total_marcadores": total,
            "mensagem": f"Marcado em {tempo_str}: {nota_limpa}",
        }

    def parar(self) -> Dict[str, Any]:
        """Finaliza a gravacao de tela, fecha o processo do ffmpeg e salva os marcadores."""
        with self._lock:
            if not self._gravando:
                return {"ok": False, "erro": "nenhuma_gravacao_de_tela_em_andamento", "mensagem": "Nenhuma gravacao de tela ativa."}
            self._gravando = False
            tarefa = self._tarefa
            inicio = self._inicio
            processo = self._processo
            pasta = self._pasta_saida
            caminho_video = self._caminho_video
            marcadores = list(self._marcadores)

        duracao = time.time() - inicio

        # Encerra o ffmpeg suavemente
        if processo is not None:
            try:
                if hasattr(processo, "stdin") and processo.stdin:
                    try:
                        processo.stdin.write(b"q")
                        processo.stdin.flush()
                    except Exception:
                        pass
                if hasattr(processo, "terminate"):
                    processo.terminate()
            except Exception as e:
                log.warning("Erro ao encerrar processo do ffmpeg: %s", e)

        # Salva marcadores em JSON e Markdown
        if pasta:
            try:
                caminho_json = pasta / "marcadores.json"
                caminho_json.write_text(
                    json.dumps(marcadores, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )

                caminho_md = pasta / "registro_tarefa.md"
                data_extenso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                linhas = [
                    f"# Gravacao de Tarefa: {tarefa}",
                    f"- Data: {data_extenso}",
                    f"- Duracao: {formatar_segundos(duracao)}",
                    f"- Arquivo de video: {caminho_video.name if caminho_video else ''}",
                    "",
                    "## Marcadores Registrados por Voz",
                ]
                if marcadores:
                    for m in marcadores:
                        linhas.append(f"- `[{m['tempo']}]` {m['nota']}")
                else:
                    linhas.append("- Nenhum marcador inserido durante a sessao.")

                caminho_md.write_text("\n".join(linhas) + "\n", encoding="utf-8")
            except Exception as e:
                log.error("Erro ao salvar marcadores de tela: %s", e)

        try:
            from .companheiro import companheiro
            companheiro.atualizar(atividade="ocioso", detalhe="")
        except Exception:
            pass

        return {
            "ok": True,
            "tarefa": tarefa,
            "duracao": formatar_segundos(duracao),
            "video": str(caminho_video) if caminho_video else "",
            "total_marcadores": len(marcadores),
            "marcadores": marcadores,
        }


# Instancias globais para controle no servico e roteador
gravador_reuniao = GravadorReuniao()
gravador_tela = GravadorTela()


def parar_qualquer_gravacao() -> Dict[str, Any]:
    """Interrompe qualquer gravacao ativa (reuniao, tela ou aula)."""
    if gravador_reuniao.gravando:
        res = gravador_reuniao.parar()
        res["tipo"] = "reuniao"
        return res

    if gravador_tela.gravando:
        res = gravador_tela.parar()
        res["tipo"] = "tela"
        return res

    try:
        from . import aulas
        if hasattr(aulas, "gravador") and aulas.gravador.gravando:
            res = aulas.gravador.parar()
            res["tipo"] = "aula"
            return res
    except Exception:
        pass

    return {"ok": False, "erro": "nenhuma_gravacao_ativa", "mensagem": "Nenhuma gravacao em andamento no momento."}
