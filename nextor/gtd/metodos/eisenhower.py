"""Metodo Matriz de Eisenhower (Urgente vs Importante)."""
from datetime import date
from typing import Any, Dict, List, Optional

from ..modelos import Item
from .base import Metodo


class MetodoEisenhower(Metodo):
    """Implementacao da Matriz de Eisenhower de 4 quadrantes."""

    nome = "Matriz de Eisenhower"
    slug = "eisenhower"
    descricao = "Priorizacao estrategica baseada em Urgencia e Importancia: Fazer Primeiro (Q1), Agendar (Q2), Delegar (Q3) e Eliminar (Q4)."

    def colunas(self) -> List[Dict[str, str]]:
        return [
            {"id": "fazer", "titulo": "Fazer Primeiro (Q1)", "descricao": "Urgente e Importante: crises, prazos imediatos e prioridades"},
            {"id": "agendar", "titulo": "Agendar Foco (Q2)", "descricao": "Importante mas Nao Urgente: planejamento, estudos e desenvolvimento"},
            {"id": "delegar", "titulo": "Delegar (Q3)", "descricao": "Urgente mas Nao Importante: interrupcoes e demandas que outros podem fazer"},
            {"id": "eliminar", "titulo": "Eliminar (Q4)", "descricao": "Nao Urgente e Nao Importante: distracoes e tarefas descartaveis"},
            {"id": "feito", "titulo": "Concluido", "descricao": "Tarefas finalizadas"},
        ]

    def classificar(self, item: Item) -> str:
        if item.estado == "feito":
            return "feito"

        meta_q = item.obter_meta("quadrante")
        if meta_q in ("fazer", "agendar", "delegar", "eliminar"):
            return meta_q

        # Avalia urgencia e importancia explicitas ou inferidas
        urgente_meta = item.obter_meta("urgente")
        importante_meta = item.obter_meta("importante")

        hoje = date.today().isoformat()
        if urgente_meta is not None:
            eh_urgente = bool(urgente_meta)
        else:
            eh_urgente = bool((item.prazo and item.prazo <= hoje) or item.energia == "alta")

        if importante_meta is not None:
            eh_importante = bool(importante_meta)
        else:
            eh_importante = bool(
                item.contexto in ("@trabalho", "@faculdade", "@leitura") or
                "importante" in item.nota.lower() or
                "urgente" in item.nota.lower()
            )

        if eh_urgente and eh_importante:
            return "fazer"
        if not eh_urgente and eh_importante:
            return "agendar"
        if eh_urgente and not eh_importante:
            return "delegar"
        return "eliminar"

    def campos_extra(self) -> List[Dict[str, Any]]:
        return [
            {"campo": "urgente", "tipo": "bool", "padrao": False, "rotulo": "Urgente"},
            {"campo": "importante", "tipo": "bool", "padrao": False, "rotulo": "Importante"},
        ]

    def visao_dia(self, itens: List[Item], agenda: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        dados_base = super().visao_dia(itens, agenda)

        # Foco diario de Eisenhower: Q1 primeiro, depois Q2
        q1 = dados_base["itens_por_coluna"].get("fazer", [])
        q2 = dados_base["itens_por_coluna"].get("agendar", [])
        dados_base["foco_hoje"] = q1 + q2[:4]

        return dados_base
