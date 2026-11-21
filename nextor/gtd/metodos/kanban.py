"""Metodo Kanban Pessoal com limite de WIP (Work In Progress)."""
from typing import Any, Dict, List, Mapping, Optional

from ..modelos import Item
from .base import LimiteWIPExcedido, Metodo

LIMITE_WIP_PADRAO = 3
LIMITE_WIP_MAXIMO = 50


def normalizar_limite_wip(valor: Any) -> int:
    try:
        n = int(valor)
    except (TypeError, ValueError):
        return LIMITE_WIP_PADRAO
    return max(1, min(LIMITE_WIP_MAXIMO, n))


class MetodoKanban(Metodo):
    """Implementacao de Kanban Pessoal com fluxo continuo e limite de WIP."""

    nome = "Kanban Pessoal"
    slug = "kanban"
    descricao = "Gestao visual de fluxo com colunas A Fazer, Fazendo e Feito, limitando tarefas em andamento para manter foco."

    def __init__(self, limite_wip: int = LIMITE_WIP_PADRAO):
        self.limite_wip = normalizar_limite_wip(limite_wip)

    def configurar(self, cfg: Optional[Mapping[str, Any]] = None) -> "MetodoKanban":
        if not cfg or "kanban_wip_limite" not in cfg:
            return self
        return MetodoKanban(limite_wip=cfg.get("kanban_wip_limite"))

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

    def regras(self) -> Dict[str, Any]:
        return {"limite_wip": self.limite_wip, "coluna_wip": "fazendo"}

    def validar_wip(self, qtd_fazendo: int) -> bool:
        """Verifica se uma nova tarefa pode entrar em 'fazendo' sem estourar o WIP."""
        return qtd_fazendo < self.limite_wip

    def classificar(self, item: Item) -> str:
        if item.estado == "feito":
            return "feito"

        meta_col = item.obter_meta("coluna_kanban")
        if meta_col in ("a_fazer", "fazendo"):
            return meta_col

        if item.obter_meta("em_andamento") is True:
            return "fazendo"

        return "a_fazer"

    def mover(self, item: Item, coluna: str, itens: Optional[List[Item]] = None) -> Item:
        c = self.validar_coluna(coluna)
        if c == "fazendo" and self.classificar(item) != "fazendo":
            em_andamento = sum(
                1 for outro in (itens or []) if outro.id != item.id and self.classificar(outro) == "fazendo"
            )
            if not self.validar_wip(em_andamento):
                raise LimiteWIPExcedido(
                    f"Limite de WIP atingido ({em_andamento}/{self.limite_wip}). Termine algo antes de puxar outra tarefa."
                )
        self._ajustar_conclusao(item, c)
        item.definir_meta("coluna_kanban", c)
        item.definir_meta("em_andamento", c == "fazendo")
        return item

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
        dados_base["wip_cheio"] = len(fazendo) >= self.limite_wip

        return dados_base
