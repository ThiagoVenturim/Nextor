"""Modelos de dados para o NexRead: tradutor de artigo/pagina ao vivo com estudo (Issue #55)."""
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

TAGS_BLOCO_PERMITIDAS = (
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "blockquote",
    "li",
    "pre",
    "code",
    "figcaption",
    "div",
)

CORES_MARCACAO = (
    "amarelo",
    "verde",
    "azul",
    "rosa",
    "roxo",
)

MODOS_LAYOUT = (
    "bilingue",
    "substituir",
    "lado_a_lado",
)


def _agora_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class BlocoPagina:
    """Bloco estrutural de um artigo ou pagina web mantendo o layout."""
    indice: int
    tag: str = "p"
    texto_original: str = ""
    texto_traduzido: str = ""
    id: str = field(default_factory=lambda: f"b-{uuid.uuid4().hex[:8]}")
    pagina_pdf: Optional[int] = None
    atributos: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        t = (self.tag or "p").strip().lower()
        self.tag = t if t in TAGS_BLOCO_PERMITIDAS else "p"
        self.texto_original = (self.texto_original or "").strip()
        self.texto_traduzido = (self.texto_traduzido or "").strip()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, dados: Dict[str, Any]) -> "BlocoPagina":
        campos_validos = {
            "id", "indice", "tag", "texto_original",
            "texto_traduzido", "pagina_pdf", "atributos",
        }
        filtrados = {k: v for k, v in dados.items() if k in campos_validos}
        if "indice" not in filtrados:
            filtrados["indice"] = 1
        return cls(**filtrados)


@dataclass
class ArtigoLido:
    """Artigo ou pagina aberta pelo usuario no NexRead com traducao ao vivo."""
    titulo: str
    url: str = ""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    titulo_traduzido: str = ""
    autor: str = ""
    veiculo: str = ""
    ano: Optional[int] = None
    idioma_origem: str = "auto"
    idioma_destino: str = "pt-BR"
    motor_traducao: str = "local"
    modo_layout: str = "bilingue"
    tipo_origem: str = "html"
    blocos: List[BlocoPagina] = field(default_factory=list)
    html_traduzido: str = ""
    disciplina: str = ""
    material_id: Optional[int] = None
    aberta_pelo_usuario: bool = True
    criado_em: str = field(default_factory=_agora_iso)
    atualizado_em: Optional[str] = None

    def __post_init__(self):
        if not self.titulo:
            self.titulo = "Artigo sem titulo"
        if not self.titulo_traduzido:
            self.titulo_traduzido = self.titulo
        if self.modo_layout not in MODOS_LAYOUT:
            self.modo_layout = "bilingue"

    @property
    def texto_completo_original(self) -> str:
        return "\n\n".join(b.texto_original for b in self.blocos if b.texto_original)

    @property
    def texto_completo_traduzido(self) -> str:
        return "\n\n".join(
            (b.texto_traduzido or b.texto_original)
            for b in self.blocos
            if (b.texto_traduzido or b.texto_original)
        )

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["blocos"] = [b.to_dict() for b in self.blocos]
        return d

    @classmethod
    def from_dict(cls, dados: Dict[str, Any]) -> "ArtigoLido":
        blocos_raw = dados.get("blocos") or []
        blocos_objs: List[BlocoPagina] = []
        for idx, b in enumerate(blocos_raw, 1):
            if isinstance(b, BlocoPagina):
                blocos_objs.append(b)
            elif isinstance(b, dict):
                b_copy = dict(b)
                b_copy.setdefault("indice", idx)
                blocos_objs.append(BlocoPagina.from_dict(b_copy))

        campos_validos = {
            "id", "titulo", "url", "titulo_traduzido", "autor", "veiculo", "ano",
            "idioma_origem", "idioma_destino", "motor_traducao", "modo_layout",
            "tipo_origem", "html_traduzido", "disciplina", "material_id",
            "aberta_pelo_usuario", "criado_em", "atualizado_em",
        }
        filtrados = {k: v for k, v in dados.items() if k in campos_validos}
        filtrados["blocos"] = blocos_objs
        return cls(**filtrados)


@dataclass
class Marcacao:
    """Trecho destacado e anotado pelo estudante em um artigo."""
    artigo_id: str
    trecho_original: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    bloco_id: str = ""
    trecho_traduzido: str = ""
    nota: str = ""
    cor: str = "amarelo"
    tags: List[str] = field(default_factory=list)
    criado_em: str = field(default_factory=_agora_iso)

    def __post_init__(self):
        c = (self.cor or "amarelo").strip().lower()
        self.cor = c if c in CORES_MARCACAO else "amarelo"
        self.trecho_original = (self.trecho_original or "").strip()
        self.trecho_traduzido = (self.trecho_traduzido or "").strip()
        self.nota = (self.nota or "").strip()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, dados: Dict[str, Any]) -> "Marcacao":
        campos_validos = {
            "id", "artigo_id", "bloco_id", "trecho_original",
            "trecho_traduzido", "nota", "cor", "tags", "criado_em",
        }
        filtrados = {k: v for k, v in dados.items() if k in campos_validos}
        if isinstance(filtrados.get("tags"), str):
            filtrados["tags"] = [t.strip() for t in filtrados["tags"].split(",") if t.strip()]
        return cls(**filtrados)


@dataclass
class GravacaoLeitura:
    """Nota de voz ou gravacao de estudo vinculada a um artigo no NexRead."""
    artigo_id: str
    transcricao: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    titulo: str = "Nota de estudo"
    caminho_audio: str = ""
    duracao_seg: int = 0
    bloco_id: str = ""
    criado_em: str = field(default_factory=_agora_iso)

    def __post_init__(self):
        self.transcricao = (self.transcricao or "").strip()
        if not self.titulo:
            self.titulo = "Nota de estudo"
        if self.duracao_seg < 0:
            self.duracao_seg = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, dados: Dict[str, Any]) -> "GravacaoLeitura":
        campos_validos = {
            "id", "artigo_id", "titulo", "transcricao",
            "caminho_audio", "duracao_seg", "bloco_id", "criado_em",
        }
        filtrados = {k: v for k, v in dados.items() if k in campos_validos}
        return cls(**filtrados)


@dataclass
class MensagemChatArtigo:
    """Turno de conversa com a IA sobre o tema do artigo com citacao de fontes."""
    artigo_id: str
    papel: str
    conteudo: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    acao: str = "perguntar"
    fontes: List[str] = field(default_factory=list)
    artigos_relacionados: List[Dict[str, Any]] = field(default_factory=list)
    criado_em: str = field(default_factory=_agora_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, dados: Dict[str, Any]) -> "MensagemChatArtigo":
        campos_validos = {
            "id", "artigo_id", "papel", "conteudo", "acao",
            "fontes", "artigos_relacionados", "criado_em",
        }
        filtrados = {k: v for k, v in dados.items() if k in campos_validos}
        return cls(**filtrados)
