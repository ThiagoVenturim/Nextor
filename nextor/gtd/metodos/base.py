"""Protocolo e classe base para metodos de produtividade intercambiaveis (Issue #45).

Todos os metodos trabalham sobre o mesmo modelo de dados (``Item``). Cada metodo guarda
o que precisa em campos proprios dentro de ``Item.metadados`` (ou no ``estado``, no caso
do GTD), entao trocar de metodo nunca apaga a classificacao feita em outro.

Para criar um metodo novo: herde de ``Metodo``, defina ``slug``, ``nome``, ``descricao``,
``colunas()``, ``classificar()`` e ``mover()``, e chame ``registrar_metodo`` (modulo
``registro``). O painel PWA monta abas, colunas e o seletor "Mover para" a partir do
que o metodo declara, sem codigo especifico por metodo.
"""
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional

from ..modelos import Item


class ErroMovimento(ValueError):
    """Movimento de item recusado pelas regras do metodo."""


class ColunaInvalida(ErroMovimento):
    """A coluna pedida nao existe no metodo."""


class LimiteWIPExcedido(ErroMovimento):
    """A coluna de trabalho em andamento ja esta no limite."""


class Metodo(ABC):
    """Classe base abstrata para qualquer metodo de produtividade pessoal."""

    nome: str = "Metodo Base"
    slug: str = "base"
    descricao: str = "Descricao do metodo de produtividade."
    # Coluna que representa "concluido": mover para ela marca o item como feito.
    # None quando o metodo nao tem uma coluna de conclusao propria.
    coluna_concluida: Optional[str] = "feito"
    # Coluna para onde vai um item reaberto quando sai da coluna de conclusao.
    estado_ao_reabrir: str = "proxima"

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

    def regras(self) -> Dict[str, Any]:
        """Regras do metodo expostas ao painel (limites, avisos). Padrao: nenhuma."""
        return {}

    def configurar(self, cfg: Optional[Mapping[str, Any]] = None) -> "Metodo":
        """Devolve uma instancia ajustada a configuracao do usuario.

        O padrao devolve a propria instancia. Metodos com parametros (por exemplo o
        limite de WIP do Kanban) devolvem uma nova instancia configurada.
        """
        return self

    def ids_colunas(self) -> List[str]:
        return [c["id"] for c in self.colunas()]

    def validar_coluna(self, coluna: str) -> str:
        c = str(coluna or "").strip().lower()
        if c not in self.ids_colunas():
            raise ColunaInvalida(f"Coluna '{coluna}' nao existe no metodo {self.slug}")
        return c

    def mover(self, item: Item, coluna: str, itens: Optional[List[Item]] = None) -> Item:
        """Move o item para a coluna pedida segundo as regras do metodo.

        ``itens`` e a lista atual de itens (usada por regras como o limite de WIP).
        O padrao grava a coluna em ``metadados['coluna_<slug>']`` e cuida de concluir
        ou reabrir o item. Subclasses gravam em seus campos proprios.
        """
        c = self.validar_coluna(coluna)
        self._ajustar_conclusao(item, c)
        item.definir_meta(f"coluna_{self.slug}", c)
        return item

    def _ajustar_conclusao(self, item: Item, coluna: str) -> None:
        """Marca como feito ao entrar na coluna de conclusao e reabre ao sair dela."""
        if self.coluna_concluida is None:
            return
        if coluna == self.coluna_concluida:
            if item.estado != "feito":
                item.estado = "feito"
                item.concluido_em = datetime.now().isoformat(timespec="seconds")
        elif item.estado == "feito":
            item.estado = self.estado_ao_reabrir
            item.concluido_em = None

    def descrever(self) -> Dict[str, Any]:
        """Catalogo do metodo para o painel e para a configuracao."""
        return {
            "slug": self.slug,
            "nome": self.nome,
            "descricao": self.descricao,
            "colunas": self.colunas(),
            "campos_extra": self.campos_extra(),
            "coluna_concluida": self.coluna_concluida,
            "regras": self.regras(),
        }

    def visao_dia(self, itens: List[Item], agenda: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Gera a visao formatada do dia especifico para o metodo."""
        colunas = self.colunas()
        itens_classificados: Dict[str, List[Dict[str, Any]]] = {col["id"]: [] for col in colunas}
        primeira_col = colunas[0]["id"]
        for it in itens:
            col_id = self.classificar(it)
            if col_id not in itens_classificados:
                col_id = primeira_col
            itens_classificados[col_id].append(it.to_dict())

        return {
            "metodo": self.slug,
            "metodo_nome": self.nome,
            "metodo_descricao": self.descricao,
            "agenda": agenda or [],
            "colunas": colunas,
            "campos_extra": self.campos_extra(),
            "coluna_concluida": self.coluna_concluida,
            "regras": self.regras(),
            "itens_por_coluna": itens_classificados,
        }
