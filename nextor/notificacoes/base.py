"""Protocolo e classe base para canais de notificacao multicanal (Issue #46)."""
from abc import ABC, abstractmethod


class CanalNotificacao(ABC):
    """Classe base para adaptadores de envio de notificacoes."""

    nome: str = "Canal Base"
    slug: str = "base"

    @abstractmethod
    def configurado(self) -> bool:
        """Verifica se os parametros necessarios (tokens, endpoints) estao configurados no ambiente."""
        raise NotImplementedError

    @abstractmethod
    def enviar(self, titulo: str, corpo: str, urgencia: str = "normal") -> bool:
        """Envia uma notificacao. Retorna True em caso de sucesso, False em falha.

        Regra inegociavel: Nunca lancar excecoes nao tratadas que exponham tokens ou credenciais.
        """
        raise NotImplementedError
