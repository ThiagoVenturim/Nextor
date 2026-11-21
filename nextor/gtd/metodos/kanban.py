"""Metodo Kanban Pessoal com limite de WIP (Work In Progress)."""
from typing import Any, Dict, List, Optional

from ..modelos import Item
from .base import Metodo


class MetodoKanban(Metodo):
    """Implementacao de Kanban Pessoal com fluxo contínuo e limite de WIP."""

    nome = "Kanban Pessoal"
    slug = "kanban"
    descricao = "Gestao visual de fluxo com colunas A Fazer, Fazendo e Feito, limitando tarefas em andamento para manter foco."

    def __init__(self, limite_wip: int = 3):
        self.limite_wip = max(1, int(limite_wip or 3))

    def colunas(self) -> List[Dict[str, str]]:
        return [
            {
                "id": "a_fazer",
                "titulo": "A Fazer",
                "descricao": "Backlog de tarefas priorizadas para iniciar",
            },
            {
                "id": "fazendo",
                "titulo": f"Fazendo (Max {self.limite_wip})",
                "descricao": f"Trabalho em andamento limitado a {self.limite_wip} tarefas simultaneas",
            },
            {
                "id": "feito",
                "titulo": "Feito",
                "descricao": "Tarefas entregues e concluidas",
            },
        ]

    def validar_wip(self, qtd_fazendo: int) -> bool:
        """Verifica se uma nova tarefa pode entrar em 'fazendo' sem estourar o WIP."""
        return qtd_fazendo < self.limite_wip

    def classificar(self, item: Item) -> str:
        if item.estado == "feito":
            return "feito"

        meta_col = item.obter_meta("coluna_kanban")
        if meta_col in ("a_fazer", "fazendo", "feito"):
            return meta_col

        if item.obter_meta("em_andamento") is True:
            return "fazendo"

        return "a_fazer"

    def campos_extra(self) -> List[Dict[str, Any]]:
        return [
            {
                "campo": "coluna_kanban",
                "tipo": "select",
                "opcoes": ["a_fazer", "fazendo", "feito"],
                "padrao": "a_fazer",
                "rotulo": "Coluna Kanban",
            },
            {
                "campo": "ordem_kanban",
                "tipo": "int",
                "padrao": 0,
                "rotulo": "Ordem na Coluna",
            },
        ]

    def visao_dia(self, itens: List[Item], agenda: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        dados_base = super().visao_dia(itens, agenda)

        fazendo = dados_base["itens_por_coluna"].get("fazendo", [])
        a_fazer = dados_base["itens_por_coluna"].get("a_fazer", [])

        # Foco diario do Kanban: terminar o que esta fazendo antes de puxar mais
        dados_base["foco_hoje"] = fazendo + a_fazer[:3]
        dados_base["limite_wip"] = self.limite_wip
        dados_base["wip_estourado"] = len(fazendo) > self.limite_wip

        return dados_base
