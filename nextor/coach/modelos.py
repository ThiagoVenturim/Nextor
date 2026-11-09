"""Modelos de dados para o treinador e coach de estudos do Nextor (Issue #57)."""
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional
import uuid

TIPOS_RECURSO = (
    "video",
    "aula",
    "livro",
    "exercicio",
    "artigo",
    "teste",
    "revisao",
)

ESTADOS_ACAO = (
    "pendente",
    "feito",
    "pulado",
)

XP_POR_TIPO: Dict[str, int] = {
    "video": 10,
    "aula": 20,
    "livro": 15,
    "exercicio": 25,
    "artigo": 15,
    "teste": 30,
    "revisao": 20,
}


def _agora_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def calcular_nivel(xp_total: int) -> int:
    """Calcula o nivel a partir do XP acumulado (1 nivel a cada 100 XP)."""
    if xp_total < 0:
        return 1
    return 1 + (xp_total // 100)


def calcular_bonus_streak(streak: int) -> int:
    """Calcula pontos extras por streak diario (5 pontos por dia consecutivo, maximo 50)."""
    if streak <= 1:
        return 0
    return min(streak * 5, 50)


@dataclass
class Recurso:
    """Recurso pedagogico pertencente a uma trilha de aprendizado."""
    trilha_id: str = ""
    tipo: str = "aula"
    titulo: str = ""
    ordem: int = 1
    duracao_min: int = 15
    dominio_publico: bool = False
    url: Optional[str] = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    descricao: str = ""

    def __post_init__(self):
        t = (self.tipo or "").strip().lower()
        self.tipo = t if t in TIPOS_RECURSO else "aula"
        if not self.titulo:
            self.titulo = "Recurso sem titulo"
        if self.duracao_min <= 0:
            self.duracao_min = 15
        if self.ordem <= 0:
            self.ordem = 1

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, dados: Dict[str, Any]) -> "Recurso":
        campos_validos = {
            "id", "trilha_id", "tipo", "titulo", "ordem",
            "duracao_min", "dominio_publico", "url", "descricao"
        }
        filtrados = {k: v for k, v in dados.items() if k in campos_validos}
        return cls(**filtrados)


@dataclass
class Trilha:
    """Trilha estruturada de aprendizado para uma habilidade ou materia."""
    id: str
    titulo: str
    habilidade: str
    nivel: str = "iniciante"
    descricao: str = ""
    recursos: List[Recurso] = field(default_factory=list)
    criado_em: str = field(default_factory=_agora_iso)
    atualizado_em: Optional[str] = None
    autor: str = "Nextor"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["recursos"] = [r.to_dict() for r in self.recursos]
        return d

    @classmethod
    def from_dict(cls, dados: Dict[str, Any]) -> "Trilha":
        trilha_id = dados.get("id", "")
        recursos_dados = dados.get("recursos", [])
        recursos_objs: List[Recurso] = []
        for r in recursos_dados:
            if isinstance(r, Recurso):
                if not r.trilha_id and trilha_id:
                    r.trilha_id = trilha_id
                recursos_objs.append(r)
            elif isinstance(r, dict):
                r_dict = dict(r)
                if not r_dict.get("trilha_id") and trilha_id:
                    r_dict["trilha_id"] = trilha_id
                recursos_objs.append(Recurso.from_dict(r_dict))

        campos_validos = {
            "id", "titulo", "habilidade", "nivel",
            "descricao", "criado_em", "atualizado_em", "autor"
        }
        filtrados = {k: v for k, v in dados.items() if k in campos_validos}
        filtrados["recursos"] = recursos_objs
        return cls(**filtrados)


@dataclass
class Plano:
    """Cronograma e ritmo de estudo de uma trilha."""
    trilha_id: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    criado_em: str = field(default_factory=_agora_iso)
    dias_semana: int = 5
    minutos_dia: int = 30
    ativo: bool = True
    data_inicio: str = field(default_factory=lambda: date.today().isoformat())

    def __post_init__(self):
        if self.dias_semana < 1:
            self.dias_semana = 1
        elif self.dias_semana > 7:
            self.dias_semana = 7
        if self.minutos_dia <= 0:
            self.minutos_dia = 30

    @property
    def ritmo(self) -> Dict[str, int]:
        return {
            "dias_semana": self.dias_semana,
            "minutos_dia": self.minutos_dia,
        }

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["ritmo"] = self.ritmo
        return d

    @classmethod
    def from_dict(cls, dados: Dict[str, Any]) -> "Plano":
        ritmo = dados.get("ritmo") or {}
        dias_sem = dados.get("dias_semana", ritmo.get("dias_semana", 5))
        min_dia = dados.get("minutos_dia", ritmo.get("minutos_dia", 30))
        campos_validos = {"id", "trilha_id", "criado_em", "ativo", "data_inicio"}
        filtrados = {k: v for k, v in dados.items() if k in campos_validos}
        filtrados["dias_semana"] = int(dias_sem)
        filtrados["minutos_dia"] = int(min_dia)
        return cls(**filtrados)


@dataclass
class ProgressoAcao:
    """Acao de estudo agendada em um plano."""
    plano_id: str
    recurso_id: str
    data: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    estado: str = "pendente"
    pontos: int = 0
    concluido_em: Optional[str] = None
    gtd_item_id: Optional[str] = None

    def __post_init__(self):
        if self.estado not in ESTADOS_ACAO:
            self.estado = "pendente"
        if len(self.data) >= 10:
            self.data = self.data[:10]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, dados: Dict[str, Any]) -> "ProgressoAcao":
        campos_validos = {
            "id", "plano_id", "recurso_id", "data",
            "estado", "pontos", "concluido_em", "gtd_item_id"
        }
        filtrados = {k: v for k, v in dados.items() if k in campos_validos}
        return cls(**filtrados)


@dataclass
class Pontuacao:
    """Estatisticas de gamificacao e pontuacao de um plano."""
    plano_id: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    xp_total: int = 0
    nivel: int = 1
    streak: int = 0
    ultima_data: Optional[str] = None

    def __post_init__(self):
        if self.xp_total > 0 and self.nivel == 1:
            self.nivel = max(1, calcular_nivel(self.xp_total))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, dados: Dict[str, Any]) -> "Pontuacao":
        campos_validos = {"id", "plano_id", "xp_total", "nivel", "streak", "ultima_data"}
        filtrados = {k: v for k, v in dados.items() if k in campos_validos}
        return cls(**filtrados)
