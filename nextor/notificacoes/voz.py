"""Canal de notificacao falada pelo Google Nest ou alto-falante local."""
import logging
import os
from typing import Callable, Optional

from .. import config
from .base import CanalNotificacao

log = logging.getLogger("nextor.notificacoes.voz")


class CanalVoz(CanalNotificacao):
    """Adaptador de envio de notificacoes faladas no ambiente."""

    nome = "Voz (Nest / PC)"
    slug = "voz"

    def __init__(self, fn_falar: Optional[Callable[[str], None]] = None):
        self._fn_falar = fn_falar

    def configurado(self) -> bool:
        if self._fn_falar is not None:
            return True
        saida = os.getenv("NEXTOR_VOZ_SAIDA", "") or getattr(config, "NEXTOR_VOZ_SAIDA", "pc")
        return saida.strip().lower() not in ("nenhuma", "desligada", "0", "false")

    def enviar(self, titulo: str, corpo: str, urgencia: str = "normal") -> bool:
        if not self.configurado():
            return False

        texto_falado = f"{titulo.strip()}. {corpo.strip()}"

        if self._fn_falar is not None:
            try:
                self._fn_falar(texto_falado)
                return True
            except Exception as e:
                log.warning("Falha mockada ao falar notificacao: %s", type(e).__name__)
                return False

        try:
            from .. import voz
            voz.falar(texto_falado)
            return True
        except Exception as e:
            log.warning("Falha ao falar notificacao no Nest/PC: %s", type(e).__name__)
            return False
