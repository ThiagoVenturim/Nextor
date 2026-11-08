"""Modelos de dados para o framework GTD do Nextor (A Arte de Fazer Acontecer)."""
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Any, Dict, Optional
import uuid

CONTEXTOS_PERMITIDOS = (
    "@faculdade",
    "@casa",
    "@trabalho",
    "@academia",
    "@leitura",
    "@qualquer",
)

ESTADOS_ITEM = (
    "inbox",
    "proxima",
    "aguardando",
    "algum_dia",
    "feito",
)

ENERGIAS_PERMITIDAS = (
    "baixa",
    "media",
    "alta",
)

ESTADOS_PROJETO = (
    "ativo",
    "concluido",
    "pausado",
)

TIPOS_LEITURA = (
    "livro",
    "artigo",
)

ESTADOS_LEITURA = (
    "quero_ler",
    "lendo",
    "lido",
)


def _agora_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def normalizar_contexto(contexto: Optional[str]) -> str:
    if not contexto:
        return "@qualquer"
    c = contexto.strip().lower()
    if not c.startswith("@"):
        c = f"@{c}"
    if c in CONTEXTOS_PERMITIDOS:
        return c
    return "@qualquer"


def normalizar_prazo(prazo: Any) -> Optional[str]:
    if not prazo:
        return None
    if isinstance(prazo, (datetime, date)):
        return prazo.strftime("%Y-%m-%d")
    p = str(prazo).strip()
    if len(p) >= 10 and p[4] == "-" and p[7] == "-":
        return p[:10]
    return p or None


@dataclass
class Item:
    """Representa um item no GTD (seja no Inbox ou uma Acao organizada)."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    titulo: str = ""
    nota: str = ""
    contexto: str = "@qualquer"
    estado: str = "inbox"
    projeto_id: Optional[str] = None
    prazo: Optional[str] = None
    energia: str = "media"
    criado_em: str = field(default_factory=_agora_iso)
    concluido_em: Optional[str] = None
    origem: str = "local"
    ref_externa: Optional[str] = None

    def __post_init__(self):
        self.contexto = normalizar_contexto(self.contexto)
        if self.estado not in ESTADOS_ITEM:
            self.estado = "inbox"
        if self.energia not in ENERGIAS_PERMITIDAS:
            self.energia = "media"
        self.prazo = normalizar_prazo(self.prazo)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, dados: Dict[str, Any]) -> "Item":
        campos_validos = {
            "id", "titulo", "nota", "contexto", "estado",
            "projeto_id", "prazo", "energia", "criado_em",
            "concluido_em", "origem", "ref_externa"
        }
        filtrados = {k: v for k, v in dados.items() if k in campos_validos}
        return cls(**filtrados)


@dataclass
class Projeto:
    """Representa um projeto com resultado definido e multiplas acoes."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    nome: str = ""
    descricao: str = ""
    estado: str = "ativo"
    criado_em: str = field(default_factory=_agora_iso)
    concluido_em: Optional[str] = None

    def __post_init__(self):
        if self.estado not in ESTADOS_PROJETO:
            self.estado = "ativo"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, dados: Dict[str, Any]) -> "Projeto":
        campos_validos = {
            "id", "nome", "descricao", "estado", "criado_em", "concluido_em"
        }
        filtrados = {k: v for k, v in dados.items() if k in campos_validos}
        return cls(**filtrados)


@dataclass
class Leitura:
    """Representa um livro ou artigo da fila de leitura pessoal."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    titulo: str = ""
    autor: str = ""
    tipo: str = "livro"
    estado: str = "quero_ler"
    paginas_total: int = 0
    paginas_lidas: int = 0
    fonte_url: str = ""
    criado_em: str = field(default_factory=_agora_iso)
    concluido_em: Optional[str] = None

    def __post_init__(self):
        if self.tipo not in TIPOS_LEITURA:
            self.tipo = "livro"
        if self.estado not in ESTADOS_LEITURA:
            self.estado = "quero_ler"
        try:
            self.paginas_total = max(0, int(self.paginas_total))
        except (ValueError, TypeError):
            self.paginas_total = 0
        try:
            self.paginas_lidas = max(0, int(self.paginas_lidas))
        except (ValueError, TypeError):
            self.paginas_lidas = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, dados: Dict[str, Any]) -> "Leitura":
        campos_validos = {
            "id", "titulo", "autor", "tipo", "estado",
            "paginas_total", "paginas_lidas", "fonte_url",
            "criado_em", "concluido_em"
        }
        filtrados = {k: v for k, v in dados.items() if k in campos_validos}
        return cls(**filtrados)
