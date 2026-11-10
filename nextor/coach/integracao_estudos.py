"""Integracao do Coach com o modo estudante (quiz, flashcards, resumos, notificacoes) (Issue #57)."""
import logging
from typing import Any, Dict, Optional

from .modelos import Plano, ProgressoAcao, Recurso

log = logging.getLogger("nextor.coach.estudos")


def obter_material_apoio(recurso: Recurso) -> Dict[str, Any]:
    """Reusa os recursos do modo estudante (quiz, flashcards, resumos) para apoiar a acao."""
    tipo = recurso.tipo
    resultado: Dict[str, Any] = {
        "tipo": tipo,
        "titulo": recurso.titulo,
        "url": recurso.url,
        "descricao": recurso.descricao,
        "apoio_disponivel": False,
        "detalhes": {},
    }

    if tipo in ("teste", "exercicio"):
        try:
            from .. import quiz
            # Tenta buscar questoes do banco se houver materias cadastradas
            questoes = quiz.buscar_questoes_por_disciplina(1) if hasattr(quiz, "buscar_questoes_por_disciplina") else []
            resultado["apoio_disponivel"] = True
            resultado["detalhes"] = {
                "modulo": "quiz",
                "total_questoes_sugeridas": len(questoes),
                "instrucao": "Responda pelo comando de voz ou painel: 'iniciar quiz'.",
            }
        except Exception:
            resultado["detalhes"] = {"modulo": "quiz", "instrucao": "Pratique com perguntas e respostas."}

    elif tipo == "revisao":
        try:
            from .. import qa_estudos
            resultado["apoio_disponivel"] = True
            resultado["detalhes"] = {
                "modulo": "qa_estudos",
                "instrucao": "Faca perguntas sobre o conteudo ou revise seus resumos.",
            }
        except Exception:
            resultado["detalhes"] = {"modulo": "resumos", "instrucao": "Revise as anotacoes anteriores."}

    return resultado


def notificar_acao_do_dia(
    acao: ProgressoAcao,
    recurso: Recurso,
    plano: Plano,
) -> Dict[str, Any]:
    """Envia notificacao multicanal com a acao de estudo recomendada para hoje."""
    try:
        from ..notificacoes import notificar
        from ..gtd.configuracao import carregar_config

        cfg = carregar_config()
        corpo = (
            f"Seu estudo de hoje: {recurso.titulo} ({recurso.duracao_min} min). "
            f"Tipo: {recurso.tipo}."
        )
        if recurso.url:
            corpo += f" Link: {recurso.url}"

        return notificar(
            evento="lembrete",
            titulo="Coach de Estudos Nextor",
            corpo=corpo,
            config_usuario=cfg,
        )
    except Exception as e:
        log.warning("Falha ao enviar notificacao do estudo do dia: %s", e)
        return {"despachados": [], "falhas": [str(e)]}
