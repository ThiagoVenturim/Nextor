"""Pacote de notificacoes multicanal do Nextor (Issue #46)."""
from .base import CanalNotificacao
from .telegram import CanalTelegram
from .discord import CanalDiscord
from .whatsapp import CanalWhatsApp
from .webpush import CanalWebPush
from .voz import CanalVoz
from .roteador_notificacoes import (
    RoteadorNotificacoes,
    roteador_instancia,
    notificar,
    EVENTOS_PERMITIDOS,
)

__all__ = [
    "CanalNotificacao",
    "CanalTelegram",
    "CanalDiscord",
    "CanalWhatsApp",
    "CanalWebPush",
    "CanalVoz",
    "RoteadorNotificacoes",
    "roteador_instancia",
    "notificar",
    "EVENTOS_PERMITIDOS",
]
