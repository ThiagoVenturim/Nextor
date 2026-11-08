"""Registro e fabrica de metodos de produtividade intercambiaveis (Issue #45)."""
from typing import Any, Dict, List, Optional

from .base import Metodo
from .gtd import MetodoGTD
from .para import MetodoPARA
from .eisenhower import MetodoEisenhower
from .kanban import MetodoKanban


REGISTRO_METODOS: Dict[str, Metodo] = {
    "gtd": MetodoGTD(),
    "para": MetodoPARA(),
    "eisenhower": MetodoEisenhower(),
    "kanban": MetodoKanban(),
}


def obter_metodo(slug: Optional[str] = None) -> Metodo:
    """Retorna a instancia do metodo solicitado ou o metodo GTD padrao."""
    s = (slug or "gtd").strip().lower()
    return REGISTRO_METODOS.get(s, REGISTRO_METODOS["gtd"])


def listar_metodos() -> List[Dict[str, Any]]:
    """Lista todos os metodos disponiveis com suas caracteristicas e colunas."""
    resultado = []
    for slug, instancia in REGISTRO_METODOS.items():
        resultado.append({
            "slug": slug,
            "nome": instancia.nome,
            "descricao": instancia.descricao,
            "colunas": instancia.colunas(),
            "campos_extra": instancia.campos_extra(),
        })
    return resultado
