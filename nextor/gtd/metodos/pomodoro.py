"""Timer Pomodoro integrado para sessões de foco sobre qualquer metodo (Issue #45)."""
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
import uuid

from ..armazenamento import ArmazenamentoGTD


class TimerPomodoro:
    """Controlador em memoria de sessao Pomodoro."""

    def __init__(
        self,
        duracao_foco_min: int = 25,
        pausa_curta_min: int = 5,
        pausa_longa_min: int = 15,
        ciclos_para_pausa_longa: int = 4,
    ):
        self.duracao_foco_min = duracao_foco_min
        self.pausa_curta_min = pausa_curta_min
        self.pausa_longa_min = pausa_longa_min
        self.ciclos_para_pausa_longa = ciclos_para_pausa_longa

        self.ativo: bool = False
        self.pausado: bool = False
        self.modo: str = "foco"  # "foco", "pausa_curta", "pausa_longa"
        self.item_id: Optional[str] = None
        self.inicio: Optional[datetime] = None
        self.fim_previsto: Optional[datetime] = None
        self.segundos_restantes: int = 0
        self.ciclos_concluidos: int = 0

    def iniciar(
        self,
        item_id: Optional[str] = None,
        duracao_min: Optional[int] = None,
        modo: str = "foco",
    ) -> Dict[str, Any]:
        """Inicia uma sessao de foco ou intervalo."""
        minutos = duracao_min or (
            self.duracao_foco_min if modo == "foco"
            else (self.pausa_longa_min if modo == "pausa_longa" else self.pausa_curta_min)
        )
        agora = datetime.now()
        self.ativo = True
        self.pausado = False
        self.modo = modo
        self.item_id = item_id
        self.inicio = agora
        self.fim_previsto = agora + timedelta(minutes=minutos)
        self.segundos_restantes = minutos * 60

        return self.obter_estado()

    def pausar(self) -> Dict[str, Any]:
        """Pausa temporariamente o timer."""
        if not self.ativo or self.pausado:
            return self.obter_estado()

        agora = datetime.now()
        if self.fim_previsto and agora < self.fim_previsto:
            self.segundos_restantes = max(0, int((self.fim_previsto - agora).total_seconds()))
        self.pausado = True
        return self.obter_estado()

    def parar(self) -> Dict[str, Any]:
        """Interrompe e reseta a sessao atual sem contabilizar."""
        self.ativo = False
        self.pausado = False
        self.item_id = None
        self.inicio = None
        self.fim_previsto = None
        self.segundos_restantes = 0
        return self.obter_estado()

    def concluir(self, db: Optional[ArmazenamentoGTD] = None) -> Dict[str, Any]:
        """Conclui a sessao com sucesso, contabilizando o pomodoro na tarefa."""
        if not self.ativo:
            return self.obter_estado()

        tarefa_titulo = ""
        if self.modo == "foco":
            self.ciclos_concluidos += 1
            if self.item_id:
                try:
                    banco = db if db is not None else ArmazenamentoGTD()
                    item = banco.obter_item(self.item_id)
                    if item:
                        tarefa_titulo = item.titulo
                        contagem = item.obter_meta("pomodoros_concluidos", 0)
                        item.definir_meta("pomodoros_concluidos", contagem + 1)
                        banco.salvar_item(item)
                except Exception:
                    pass

            # Proxima recomendacao
            if self.ciclos_concluidos % self.ciclos_para_pausa_longa == 0:
                proximo_modo = "pausa_longa"
            else:
                proximo_modo = "pausa_curta"
        else:
            proximo_modo = "foco"

        self.ativo = False
        self.pausado = False
        self.item_id = None
        self.fim_previsto = None
        self.segundos_restantes = 0

        return {
            "status": "concluido",
            "modo_concluido": self.modo,
            "ciclos_concluidos": self.ciclos_concluidos,
            "proximo_modo_sugerido": proximo_modo,
            "tarefa_associada": tarefa_titulo,
        }

    def obter_estado(self) -> Dict[str, Any]:
        """Retorna o estado atual em tempo real."""
        if self.ativo and not self.pausado and self.fim_previsto:
            agora = datetime.now()
            if agora >= self.fim_previsto:
                self.segundos_restantes = 0
            else:
                self.segundos_restantes = max(0, int((self.fim_previsto - agora).total_seconds()))

        minutos = self.segundos_restantes // 60
        segundos = self.segundos_restantes % 60
        formatado = f"{minutos:02d}:{segundos:02d}"

        return {
            "ativo": self.ativo,
            "pausado": self.pausado,
            "modo": self.modo,
            "item_id": self.item_id,
            "segundos_restantes": self.segundos_restantes,
            "tempo_formatado": formatado,
            "ciclos_concluidos": self.ciclos_concluidos,
        }


# Instancia singleton para o processo do assistente
pomodoro_instancia = TimerPomodoro()


def iniciar(item_id: Optional[str] = None, duracao_min: Optional[int] = None, modo: str = "foco") -> Dict[str, Any]:
    return pomodoro_instancia.iniciar(item_id=item_id, duracao_min=duracao_min, modo=modo)


def pausar() -> Dict[str, Any]:
    return pomodoro_instancia.pausar()


def parar() -> Dict[str, Any]:
    return pomodoro_instancia.parar()


def concluir(db: Optional[ArmazenamentoGTD] = None) -> Dict[str, Any]:
    return pomodoro_instancia.concluir(db=db)


def obter_estado() -> Dict[str, Any]:
    return pomodoro_instancia.obter_estado()
