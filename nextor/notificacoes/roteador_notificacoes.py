"""Roteador inteligente de notificacoes multicanal com horario de silencio (Issue #46)."""
from datetime import datetime, time
import logging
from typing import Any, Dict, List, Optional

from .base import URGENCIAS_QUE_FURAM_SILENCIO, CanalNotificacao, normalizar_urgencia
from .telegram import CanalTelegram
from .discord import CanalDiscord
from .whatsapp import CanalWhatsApp
from .webpush import CanalWebPush
from .voz import CanalVoz

log = logging.getLogger("nextor.notificacoes.roteador")

EVENTOS_PERMITIDOS = (
    "lembrete",
    "agenda_do_dia",
    "tarefa_atrasada",
    "pr_para_revisar",
    "pomodoro_fim",
    "reuniao_lembrete",
    "reuniao_inicio",
)

CANAIS_CONHECIDOS = ("telegram", "discord", "whatsapp", "webpush", "voz")


class RoteadorNotificacoes:
    """Roteia notificacoes para os canais apropriados de acordo com configuracoes e regras de silencio."""

    def __init__(self, canais: Optional[Dict[str, CanalNotificacao]] = None):
        self.canais: Dict[str, CanalNotificacao] = canais if canais is not None else {
            "telegram": CanalTelegram(),
            "discord": CanalDiscord(),
            "whatsapp": CanalWhatsApp(),
            "webpush": CanalWebPush(),
            "voz": CanalVoz(),
        }

    def registrar_canal(self, canal: CanalNotificacao) -> None:
        self.canais[canal.slug] = canal

    def listar_status_canais(self) -> List[Dict[str, Any]]:
        status = []
        for slug, inst in self.canais.items():
            item: Dict[str, Any] = {"slug": slug, "nome": inst.nome, "configurado": inst.configurado()}
            # Detalhes sem segredo: modo do Discord e quantos aparelhos tem web push.
            if hasattr(inst, "modo"):
                item["modo"] = inst.modo()
            if hasattr(inst, "inscricoes"):
                try:
                    item["aparelhos"] = inst.inscricoes.quantidade()
                except Exception:
                    item["aparelhos"] = 0
            status.append(item)
        return status

    def em_horario_silencio(
        self,
        inicio_str: str = "22:00",
        fim_str: str = "07:00",
        hora_referencia: Optional[time] = None,
    ) -> bool:
        """Verifica se o momento atual coincide com a janela de silencio do usuario."""
        try:
            h_ini, m_ini = map(int, inicio_str.strip().split(":"))
            h_fim, m_fim = map(int, fim_str.strip().split(":"))
            t_ini = time(h_ini, m_ini)
            t_fim = time(h_fim, m_fim)
        except Exception:
            return False

        t_atual = hora_referencia or datetime.now().time()

        if t_ini <= t_fim:
            return t_ini <= t_atual <= t_fim
        else:
            # Janela cruza a meia-noite (ex: 22:00 as 07:00)
            return t_atual >= t_ini or t_atual <= t_fim

    def notificar(
        self,
        evento: str,
        titulo: str,
        corpo: str,
        urgencia: str = "normal",
        canais_especificos: Optional[List[str]] = None,
        config_usuario: Optional[Dict[str, Any]] = None,
        hora_referencia: Optional[time] = None,
    ) -> Dict[str, Any]:
        """Despacha uma notificacao para os canais configurados."""
        cfg = config_usuario or {}
        urgencia = normalizar_urgencia(urgencia)
        silencio_cfg = cfg.get("horario_silencio") or {"ativo": True, "inicio": "22:00", "fim": "07:00"}

        # 1. Checa horario de silencio se ativo
        if silencio_cfg.get("ativo", True) and urgencia not in URGENCIAS_QUE_FURAM_SILENCIO:
            if self.em_horario_silencio(
                inicio_str=silencio_cfg.get("inicio", "22:00"),
                fim_str=silencio_cfg.get("fim", "07:00"),
                hora_referencia=hora_referencia,
            ):
                return {
                    "sucesso": True,
                    "silenciado": True,
                    "motivo": "horario_de_silencio",
                    "despachados": [],
                    "falhas": [],
                    "ignorados": [],
                }

        # 2. Determina quais canais devem receber este evento
        if canais_especificos:
            alvos = canais_especificos
        else:
            eventos_map = cfg.get("eventos_notificacao") or {}
            alvos = eventos_map.get(evento, ["telegram"])
        if not isinstance(alvos, (list, tuple)):
            alvos = []

        canais_ativos_cfg = set(cfg.get("canais_ativos", ["telegram", "discord", "whatsapp", "webpush", "voz"]))

        despachados = []
        falhas = []
        ignorados = []

        for slug in dict.fromkeys(alvos):
            if slug not in canais_ativos_cfg:
                ignorados.append({"canal": slug, "motivo": "inativo"})
                continue
            canal = self.canais.get(slug)
            if not canal:
                ignorados.append({"canal": slug, "motivo": "desconhecido"})
                continue

            if not canal.configurado():
                ignorados.append({"canal": slug, "motivo": "nao_configurado"})
                continue

            try:
                ok = canal.enviar(titulo=titulo, corpo=corpo, urgencia=urgencia)
                if ok:
                    despachados.append(slug)
                else:
                    falhas.append(slug)
            except Exception as e:
                log.warning("Falha nao esperada no canal %s: %s", slug, type(e).__name__)
                falhas.append(slug)

        return {
            "sucesso": len(despachados) > 0 or len(alvos) == 0,
            "silenciado": False,
            "despachados": despachados,
            "falhas": falhas,
            "ignorados": ignorados,
        }


# Instancia singleton
roteador_instancia = RoteadorNotificacoes()


def notificar(
    evento: str,
    titulo: str,
    corpo: str,
    urgencia: str = "normal",
    canais_especificos: Optional[List[str]] = None,
    config_usuario: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Atalho para o roteador global. Sem config_usuario, usa a config salva no painel
    (canais ativos, eventos por canal e horario de silencio)."""
    if config_usuario is None:
        try:
            from ..gtd.configuracao import carregar_config
            config_usuario = carregar_config()
        except Exception as e:
            log.warning("Config de notificacoes indisponivel, usando padrao: %s", type(e).__name__)
            config_usuario = {}
    return roteador_instancia.notificar(
        evento=evento,
        titulo=titulo,
        corpo=corpo,
        urgencia=urgencia,
        canais_especificos=canais_especificos,
        config_usuario=config_usuario,
    )
