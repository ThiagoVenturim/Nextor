"""Protocolo e classe base para canais de notificacao multicanal (Issue #46)."""
from abc import ABC, abstractmethod

# Niveis de urgencia aceitos. "alta" e "critica" furam o horario de silencio.
URGENCIAS = ("baixa", "normal", "alta", "critica")
URGENCIAS_QUE_FURAM_SILENCIO = ("alta", "critica")


def normalizar_urgencia(urgencia: str) -> str:
    """Devolve a urgencia em minusculas ou "normal" se o valor for desconhecido."""
    u = str(urgencia or "").strip().lower()
    return u if u in URGENCIAS else "normal"


def formatar_titulo(titulo: str, urgencia: str = "normal") -> str:
    """Marca o titulo como urgente nos canais de texto quando a urgencia e alta ou critica."""
    t = str(titulo or "").strip()
    if normalizar_urgencia(urgencia) in URGENCIAS_QUE_FURAM_SILENCIO:
        return f"URGENTE: {t}"
    return t


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
