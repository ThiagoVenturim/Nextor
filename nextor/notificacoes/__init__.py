"""Pacote de notificacoes multicanal do Nextor (Issue #46)."""
from .base import URGENCIAS, CanalNotificacao, formatar_titulo, normalizar_urgencia
from .telegram import CanalTelegram
from .discord import CanalDiscord
from .whatsapp import CanalWhatsApp
from .webpush import CanalWebPush
from .inscricoes_push import InscricoesPush, validar_inscricao
from .voz import CanalVoz
from .roteador_notificacoes import (
    CANAIS_CONHECIDOS,
    RoteadorNotificacoes,
    roteador_instancia,
    notificar,
    EVENTOS_PERMITIDOS,
)

__all__ = [
    "URGENCIAS",
    "CanalNotificacao",
    "formatar_titulo",
    "normalizar_urgencia",
    "CanalTelegram",
    "CanalDiscord",
    "CanalWhatsApp",
    "CanalWebPush",
    "InscricoesPush",
    "validar_inscricao",
    "CanalVoz",
    "CANAIS_CONHECIDOS",
    "RoteadorNotificacoes",
    "roteador_instancia",
    "notificar",
    "EVENTOS_PERMITIDOS",
]
