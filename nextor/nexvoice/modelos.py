"""Modelos de dados para o NexVoice: tradutor de audio ao vivo para videos e reunioes (Issue #56)."""
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

MODOS_NEXVOICE = (
    "ouvir",
    "reuniao",
)

DIRECOES_FALA = (
    "entrada",
    "saida",
)

FONTES_AUDIO = (
    "video",
    "aula",
    "microfone",
    "reuniao",
)

ESTADOS_SESSAO = (
    "ativa",
    "pausada",
    "encerrada",
)

MOTORES_STT_SUPORTADOS = (
    "faster_whisper",
    "whisper",
    "vosk",
    "stub",
)

MOTORES_TRADUCAO_SUPORTADOS = (
    "local",
    "libretranslate",
    "nllb",
    "opus_mt",
    "faccoder",
    "claude",
)

MOTORES_TTS_SUPORTADOS = (
    "piper",
    "sapi",
    "gtts",
    "stub",
)

AVISO_CONSENTIMENTO_NEXVOICE_REUNIAO = (
    "Aviso obrigatorio de etica e privacidade (NexVoice): esta reuniao possui traducao e "
    "transcricao de audio ao vivo processadas localmente no dispositivo. Todos os participantes "
    "devem estar cientes e consentir expressamente antes do inicio."
)

AVISO_CONSENTIMENTO_NEXVOICE_AULA = (
    "Aviso de consentimento (NexVoice): traduzir ou transcrever aula ao vivo exige "
    "autorizacao previa do professor e da instituicao de ensino."
)


def _agora_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def formatar_tempo_legenda(segundos: float) -> str:
    """Formata segundos em MM:SS ou HH:MM:SS para legendas ao vivo."""
    s = int(max(0.0, float(segundos)))
    horas = s // 3600
    minutos = (s % 3600) // 60
    segs = s % 60
    if horas > 0:
        return f"{horas:02d}:{minutos:02d}:{segs:02d}"
    return f"{minutos:02d}:{segs:02d}"


def formatar_timestamp_srt(segundos: float) -> str:
    """Formata segundos no padrao SubRip (.srt) HH:MM:SS,mmm."""
    total_ms = int(round(max(0.0, float(segundos)) * 1000))
    horas = total_ms // 3_600_000
    resto = total_ms % 3_600_000
    minutos = resto // 60_000
    resto = resto % 60_000
    segs = resto // 1000
    ms = resto % 1000
    return f"{horas:02d}:{minutos:02d}:{segs:02d},{ms:03d}"


@dataclass
class TrechoVoz:
    """Trecho de fala capturado, transcrito, traduzido e sintetizado em tempo real."""
    sessao_id: str
    indice: int
    direcao: str = "entrada"
    locutor: str = "locutor"
    idioma_origem: str = "en-US"
    idioma_destino: str = "pt-BR"
    texto_original: str = ""
    texto_traduzido: str = ""
    inicio_seg: float = 0.0
    fim_seg: float = 2.5
    latencia_ms: int = 0
    motor_stt: str = "faster_whisper"
    motor_traducao: str = "local"
    motor_tts: str = "piper"
    fala_id: str = ""
    duracao_tts_seg: float = 0.0
    id: str = field(default_factory=lambda: f"tv-{uuid.uuid4().hex[:8]}")
    criado_em: str = field(default_factory=_agora_iso)

    def __post_init__(self):
        d = (self.direcao or "entrada").strip().lower()
        self.direcao = d if d in DIRECOES_FALA else "entrada"
        self.locutor = (self.locutor or ("eu" if self.direcao == "saida" else "interlocutor")).strip()
        self.texto_original = (self.texto_original or "").strip()
        self.texto_traduzido = (self.texto_traduzido or "").strip()
        self.inicio_seg = max(0.0, float(self.inicio_seg or 0.0))
        self.fim_seg = max(self.inicio_seg + 0.5, float(self.fim_seg or (self.inicio_seg + 2.5)))
        self.latencia_ms = max(0, int(self.latencia_ms or 0))
        self.duracao_tts_seg = max(0.0, float(self.duracao_tts_seg or 0.0))

    @property
    def legenda_formatada(self) -> str:
        t_ini = formatar_tempo_legenda(self.inicio_seg)
        seta = "->" if self.direcao == "saida" else "<-"
        return f"[{t_ini}] [{self.locutor} {seta} {self.idioma_destino}] {self.texto_traduzido}"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["legenda_formatada"] = self.legenda_formatada
        return d

    @classmethod
    def from_dict(cls, dados: Dict[str, Any]) -> "TrechoVoz":
        campos_validos = {
            "id", "sessao_id", "indice", "direcao", "locutor",
            "idioma_origem", "idioma_destino", "texto_original", "texto_traduzido",
            "inicio_seg", "fim_seg", "latencia_ms", "motor_stt",
            "motor_traducao", "motor_tts", "fala_id", "duracao_tts_seg", "criado_em",
        }
        filtrados = {k: v for k, v in dados.items() if k in campos_validos}
        filtrados.setdefault("indice", 1)
        return cls(**filtrados)


@dataclass
class SessaoNexVoice:
    """Sessao de traducao de audio ao vivo no modo ouvir (video/aula) ou reuniao (bidirecional)."""
    titulo: str
    modo: str = "ouvir"
    fonte: str = "video"
    idioma_meu: str = "pt-BR"
    idioma_outro: str = "en-US"
    motor_stt: str = "faster_whisper"
    motor_traducao: str = "local"
    motor_tts: str = "piper"
    sintetizar_voz: bool = True
    processamento_local_estrito: bool = True
    consentimento_exigido: bool = False
    consentimento_confirmado: bool = False
    consentimento_participantes: str = ""
    consentimento_em: Optional[str] = None
    aviso_consentimento: str = ""
    disciplina: str = ""
    material_id: Optional[int] = None
    estado: str = "ativa"
    trechos: List[TrechoVoz] = field(default_factory=list)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    criado_em: str = field(default_factory=_agora_iso)
    encerrado_em: Optional[str] = None

    def __post_init__(self):
        self.titulo = (self.titulo or "Sessao NexVoice").strip()
        m = (self.modo or "ouvir").strip().lower()
        self.modo = m if m in MODOS_NEXVOICE else "ouvir"
        f = (self.fonte or ("reuniao" if self.modo == "reuniao" else "video")).strip().lower()
        self.fonte = f if f in FONTES_AUDIO else ("reuniao" if self.modo == "reuniao" else "video")
        est = (self.estado or "ativa").strip().lower()
        self.estado = est if est in ESTADOS_SESSAO else "ativa"

        if self.modo == "reuniao" or self.fonte in ("reuniao", "aula"):
            self.consentimento_exigido = True
            if not self.aviso_consentimento:
                self.aviso_consentimento = (
                    AVISO_CONSENTIMENTO_NEXVOICE_AULA
                    if self.fonte == "aula" and self.modo == "ouvir"
                    else AVISO_CONSENTIMENTO_NEXVOICE_REUNIAO
                )

    @property
    def transcricao_bilingue(self) -> str:
        linhas: List[str] = []
        for t in self.trechos:
            carimbo = f"[{formatar_tempo_legenda(t.inicio_seg)} - {formatar_tempo_legenda(t.fim_seg)}]"
            linhas.append(
                f"{carimbo} ({t.locutor} | {t.idioma_origem} -> {t.idioma_destino})\n"
                f"  Original: {t.texto_original}\n"
                f"  Traducao: {t.texto_traduzido}"
            )
        return "\n".join(linhas)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["trechos"] = [t.to_dict() for t in self.trechos]
        return d

    @classmethod
    def from_dict(cls, dados: Dict[str, Any]) -> "SessaoNexVoice":
        trechos_raw = dados.get("trechos") or []
        trechos_objs: List[TrechoVoz] = []
        for idx, tr in enumerate(trechos_raw, 1):
            if isinstance(tr, TrechoVoz):
                trechos_objs.append(tr)
            elif isinstance(tr, dict):
                tr_copy = dict(tr)
                tr_copy.setdefault("indice", idx)
                tr_copy.setdefault("sessao_id", dados.get("id", ""))
                trechos_objs.append(TrechoVoz.from_dict(tr_copy))

        campos_validos = {
            "id", "titulo", "modo", "fonte", "idioma_meu", "idioma_outro",
            "motor_stt", "motor_traducao", "motor_tts", "sintetizar_voz",
            "processamento_local_estrito", "consentimento_exigido",
            "consentimento_confirmado", "consentimento_participantes",
            "consentimento_em", "aviso_consentimento", "disciplina",
            "material_id", "estado", "criado_em", "encerrado_em",
        }
        filtrados = {k: v for k, v in dados.items() if k in campos_validos}
        filtrados["trechos"] = trechos_objs
        return cls(**filtrados)
