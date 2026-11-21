"""Protocolo e classe base para metodos de produtividade intercambiaveis (Issue #45)."""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from ..modelos import Item


class Metodo(ABC):
    """Classe base abstrata para qualquer metodo de produtividade pessoal."""

    nome: str = "Metodo Base"
    slug: str = "base"
    descricao: str = "Descricao do metodo de produtividade."

    @abstractmethod
    def colunas(self) -> List[Dict[str, str]]:
        """Retorna a lista de colunas/baldes que este metodo utiliza.

        Cada coluna deve conter:
        - id: identificador unico da coluna
        - titulo: titulo exibido na interface
        - descricao: explicacao breve do proposito da coluna
        """
        raise NotImplementedError

    @abstractmethod
    def classificar(self, item: Item) -> str:
        """Determina em qual coluna/balde o item se enquadra."""
        raise NotImplementedError

    def campos_extra(self) -> List[Dict[str, Any]]:
        """Lista de campos adicionais que o metodo requer ou suporta.

        Exemplo:
        [
            {"campo": "urgente", "tipo": "bool", "padrao": False, "rotulo": "Urgente"},
            {"campo": "importante", "tipo": "bool", "padrao": False, "rotulo": "Importante"}
        ]
        """
        return []

    def visao_dia(self, itens: List[Item], agenda: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Gera a visao formatada do dia especifico para o metodo."""
        itens_classificados: Dict[str, List[Dict[str, Any]]] = {
            col["id"]: [] for col in self.colunas()
        }
        for it in itens:
            col_id = self.classificar(it)
            if col_id in itens_classificados:
                itens_classificados[col_id].append(it.to_dict())
            else:
                primeira_col = self.colunas()[0]["id"]
                itens_classificados[primeira_col].append(it.to_dict())

        return {
            "metodo": self.slug,
            "metodo_nome": self.nome,
            "agenda": agenda or [],
            "colunas": self.colunas(),
            "itens_por_coluna": itens_classificados,
        }
