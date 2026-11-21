"""Modulo coach de estudos do Nextor (Issue #57)."""
from .modelos import (
    Plano,
    Pontuacao,
    ProgressoAcao,
    Recurso,
    Trilha,
    calcular_bonus_streak,
    calcular_nivel,
)
from .armazenamento import ArmazenamentoCoach
from .trilhas import (
    carregar_todas_trilhas,
    carregar_trilhas_embutidas,
    carregar_trilhas_usuario,
    criar_trilha,
    obter_trilha,
    salvar_trilha_usuario,
)
from .coach import (
    acao_do_dia,
    concluir,
    criar_plano,
    dia_esta_cheio,
    obter_ou_criar_plano_padrao,
    resumo,
)
from .integracao_gtd import (
    concluir_tarefa_gtd_vinculada,
    criar_tarefa_gtd_para_acao,
    criar_tarefas_gtd_plano,
    sincronizar_conclusao_gtd,
)

__all__ = [
    "Plano",
    "Pontuacao",
    "ProgressoAcao",
    "Recurso",
    "Trilha",
    "calcular_bonus_streak",
    "calcular_nivel",
    "ArmazenamentoCoach",
    "carregar_todas_trilhas",
    "carregar_trilhas_embutidas",
    "carregar_trilhas_usuario",
    "criar_trilha",
    "obter_trilha",
    "salvar_trilha_usuario",
    "acao_do_dia",
    "concluir",
    "criar_plano",
    "dia_esta_cheio",
    "obter_ou_criar_plano_padrao",
    "resumo",
    "concluir_tarefa_gtd_vinculada",
    "criar_tarefa_gtd_para_acao",
    "criar_tarefas_gtd_plano",
    "sincronizar_conclusao_gtd",
]
