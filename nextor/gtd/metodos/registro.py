"""Registro e fabrica de metodos de produtividade intercambiaveis (Issue #45).

Adicionar um metodo novo e criar um modulo com uma subclasse de ``Metodo`` e registra-la:

    from nextor.gtd.metodos import Metodo, registrar_metodo

    class MetodoIvyLee(Metodo):
        slug = "ivy_lee"
        ...

    registrar_metodo(MetodoIvyLee())

O metodo passa a aparecer em ``listar_metodos()``, em ``GET /gtd/metodos``, nas abas do
painel e pode ser escolhido como ``metodo_ativo`` na configuracao.
"""
import re
from typing import Any, Dict, List, Mapping, Optional, Type, Union

from .base import Metodo
from .eisenhower import MetodoEisenhower
from .gtd import MetodoGTD
from .kanban import MetodoKanban
from .para import MetodoPARA

METODO_PADRAO = "gtd"
_SLUG_VALIDO = re.compile(r"^[a-z][a-z0-9_]{1,31}$")

REGISTRO_METODOS: Dict[str, Metodo] = {}


def registrar_metodo(metodo: Union[Metodo, Type[Metodo]], substituir: bool = False) -> Metodo:
    """Registra um metodo (instancia ou classe) e o devolve.

    Recusa slugs invalidos e, sem ``substituir=True``, slugs ja registrados.
    """
    instancia = metodo() if isinstance(metodo, type) else metodo
    if not isinstance(instancia, Metodo):
        raise TypeError("metodo precisa herdar de nextor.gtd.metodos.Metodo")
    slug = str(instancia.slug or "").strip().lower()
    if not _SLUG_VALIDO.match(slug):
        raise ValueError(f"slug de metodo invalido: {instancia.slug!r}")
    if not instancia.colunas():
        raise ValueError(f"metodo {slug} precisa declarar ao menos uma coluna")
    if slug in REGISTRO_METODOS and not substituir:
        raise ValueError(f"metodo ja registrado: {slug}")
    REGISTRO_METODOS[slug] = instancia
    return instancia


def remover_metodo(slug: str) -> bool:
    """Remove um metodo do registro. O metodo padrao nao pode ser removido."""
    s = str(slug or "").strip().lower()
    if s == METODO_PADRAO:
        return False
    return REGISTRO_METODOS.pop(s, None) is not None


def metodo_existe(slug: Optional[str]) -> bool:
    return str(slug or "").strip().lower() in REGISTRO_METODOS


def obter_metodo(slug: Optional[str] = None, cfg: Optional[Mapping[str, Any]] = None) -> Metodo:
    """Retorna o metodo pedido (ou o GTD padrao), ajustado a configuracao quando dada."""
    s = (slug or METODO_PADRAO).strip().lower()
    metodo = REGISTRO_METODOS.get(s, REGISTRO_METODOS[METODO_PADRAO])
    return metodo.configurar(cfg) if cfg else metodo


def listar_metodos(cfg: Optional[Mapping[str, Any]] = None) -> List[Dict[str, Any]]:
    """Lista todos os metodos disponiveis com suas caracteristicas e colunas."""
    return [obter_metodo(slug, cfg).descrever() for slug in REGISTRO_METODOS]


for _cls in (MetodoGTD, MetodoPARA, MetodoEisenhower, MetodoKanban):
    registrar_metodo(_cls)
