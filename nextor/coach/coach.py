"""Logica central do treinador de estudos do Nextor (Issue #57).

Monta cronograma respeitando minutos/dia, seleciona acao do dia
pulando dias cheios e sem repetir o que ja foi feito, calcula XP e streak,
sobe de nivel e integra com o painel GTD e modo estudante.
"""
from datetime import date, datetime, timedelta
import logging
from typing import Any, Dict, List, Optional, Union

from .armazenamento import ArmazenamentoCoach
from .modelos import (
    Plano,
    Pontuacao,
    ProgressoAcao,
    Recurso,
    Trilha,
    XP_POR_TIPO,
    calcular_bonus_streak,
    calcular_nivel,
)
from .trilhas import obter_trilha

log = logging.getLogger("nextor.coach")


def _obter_db(db: Optional[ArmazenamentoCoach]) -> ArmazenamentoCoach:
    return db if db is not None else ArmazenamentoCoach()


def _para_data_obj(d: Optional[Union[str, date, datetime]]) -> date:
    if d is None:
        return date.today()
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    try:
        return date.fromisoformat(str(d)[:10])
    except Exception:
        return date.today()


def dia_esta_cheio(
    data: Optional[Union[str, date, datetime]] = None,
    db_gtd: Optional[Any] = None,
    limite_eventos: int = 3,
) -> bool:
    """Verifica se a data possui agenda saturada ou entregas criticas.

    Fontes consultadas:
    1. Google Agenda (via nextor.agenda.eventos_entre)
    2. Entregas de faculdade / trabalho no GTD com contexto @faculdade ou @trabalho
    3. Prazos iminentes de Canvas LMS e Google Sala de Aula
    """
    dt = _para_data_obj(data)

    # 1. Agenda
    try:
        from .. import agenda
        if hasattr(agenda, "eventos_entre"):
            evs = agenda.eventos_entre(dt, dt + timedelta(days=1)) or []
            if len(evs) >= limite_eventos:
                return True
            for ev in evs:
                tit = (ev.get("titulo") or "").lower()
                if any(k in tit for k in ("dia cheio", "dia ocupado", "bloqueado", "reunioes consecutivas", "viagem")):
                    return True
    except Exception:
        pass

    # 2. GTD (@trabalho / @faculdade com prazo hoje)
    try:
        from ..gtd.armazenamento import ArmazenamentoGTD
        banco_gtd = db_gtd if db_gtd is not None else ArmazenamentoGTD()
        itens_hoje = banco_gtd.listar_itens(estado="proxima", data_prazo=dt.isoformat())
        criticos = [
            it for it in itens_hoje
            if it.contexto in ("@trabalho", "@faculdade")
        ]
        if len(criticos) >= 2 or len(itens_hoje) >= 5:
            return True
    except Exception:
        pass

    # 3. Canvas LMS
    try:
        from .. import canvas_lms
        if canvas_lms.esta_configurado():
            tarefas_canvas = canvas_lms.proximas_tarefas(dias=1) or []
            if len(tarefas_canvas) >= 2:
                return True
    except Exception:
        pass

    # 4. Google Classroom
    try:
        from .. import google_classroom
        if google_classroom.esta_configurado():
            atividades_cr = google_classroom.proximas_atividades(dias=1) or []
            if len(atividades_cr) >= 2:
                return True
    except Exception:
        pass

    return False


def criar_plano(
    trilha: Union[Trilha, str],
    ritmo: Optional[Dict[str, int]] = None,
    data_inicio: Optional[Union[str, date]] = None,
    db: Optional[ArmazenamentoCoach] = None,
    integrar_gtd: bool = True,
) -> Plano:
    """Gera o cronograma de estudos distribuindo recursos no tempo respeitando minutos/dia."""
    banco = _obter_db(db)

    # Resolve trilha
    if isinstance(trilha, str):
        t_obj = banco.obter_trilha(trilha) or obter_trilha(trilha)
        if not t_obj:
            raise ValueError(f"Trilha '{trilha}' nao encontrada.")
    elif isinstance(trilha, Trilha):
        t_obj = trilha
        banco.salvar_trilha(t_obj)
    else:
        raise TypeError("trilha deve ser um objeto Trilha ou o ID de uma trilha cadastrada.")

    recursos = sorted(t_obj.recursos, key=lambda r: r.ordem)
    if not recursos:
        raise ValueError("A trilha nao possui nenhum recurso cadastrado.")

    ritmo_dict = ritmo or {}
    dias_semana = int(ritmo_dict.get("dias_semana", 5))
    minutos_dia = int(ritmo_dict.get("minutos_dia", 30))
    dt_inicio = _para_data_obj(data_inicio)

    plano = Plano(
        trilha_id=t_obj.id,
        dias_semana=dias_semana,
        minutos_dia=minutos_dia,
        data_inicio=dt_inicio.isoformat(),
        ativo=True,
    )
    banco.salvar_plano(plano)

    # Distribuicao dos recursos respeitando minutos/dia e dias/semana
    dia_atual = dt_inicio
    minutos_alocados_hoje = 0

    def _eh_dia_de_estudo(d: date) -> bool:
        if dias_semana >= 7:
            return True
        if dias_semana == 5:
            return d.weekday() < 5
        if dias_semana == 6:
            return d.weekday() < 6
        # Distribuicao uniforme para dias_semana < 5
        intervalo = 7 / dias_semana
        dias_permitidos = [int(i * intervalo) % 7 for i in range(dias_semana)]
        return d.weekday() in dias_permitidos

    acoes: List[ProgressoAcao] = []

    for rec in recursos:
        # Se o dia atual nao for valido pelo ritmo, avanca
        while not _eh_dia_de_estudo(dia_atual):
            dia_atual += timedelta(days=1)
            minutos_alocados_hoje = 0

        # Se ja acumulou minutos no dia e adicionar este recurso estoura o limite diario
        if minutos_alocados_hoje > 0 and (minutos_alocados_hoje + rec.duracao_min > minutos_dia):
            dia_atual += timedelta(days=1)
            while not _eh_dia_de_estudo(dia_atual):
                dia_atual += timedelta(days=1)
            minutos_alocados_hoje = 0

        acao = ProgressoAcao(
            plano_id=plano.id,
            recurso_id=rec.id,
            data=dia_atual.isoformat(),
            estado="pendente",
            pontos=0,
        )
        banco.salvar_acao(acao)
        acoes.append(acao)

        minutos_alocados_hoje += rec.duracao_min
        if minutos_alocados_hoje >= minutos_dia:
            dia_atual += timedelta(days=1)
            minutos_alocados_hoje = 0

    # Inicializa pontuacao
    pontuacao = Pontuacao(
        plano_id=plano.id,
        xp_total=0,
        nivel=1,
        streak=0,
        ultima_data=None,
    )
    banco.salvar_pontuacao(pontuacao)

    # Integracao com GTD
    if integrar_gtd:
        try:
            from .integracao_gtd import criar_tarefas_gtd_plano
            criar_tarefas_gtd_plano(plano, acoes, banco, None)
        except Exception as e:
            log.warning("Falha ao integrar acoes iniciais ao GTD: %s", e)

    return plano


def acao_do_dia(
    plano: Union[Plano, str],
    data: Optional[Union[str, date]] = None,
    db: Optional[ArmazenamentoCoach] = None,
    db_gtd: Optional[Any] = None,
    verificar_dia_saturado: bool = True,
) -> Optional[ProgressoAcao]:
    """Seleciona a proxima acao de estudo pendente.

    Regras:
    - Pula dias cheios na agenda ou com entregas prioritarias de trabalho/faculdade.
    - Nunca repete acao que ja foi concluida ('feito').
    - Prioriza a acao agendada para a data solicitada ou a proxima pendente mais antiga.
    """
    banco = _obter_db(db)
    plano_obj = banco.obter_plano(plano) if isinstance(plano, str) else plano
    if not plano_obj:
        return None

    dt = _para_data_obj(data)

    if verificar_dia_saturado and dia_esta_cheio(dt, db_gtd=db_gtd):
        log.info("Dia %s esta cheio. Nenhuma acao sugerida para hoje.", dt.isoformat())
        return None

    # Busca acoes pendentes
    acoes_pendentes = banco.listar_acoes(plano_id=plano_obj.id, estado="pendente")
    if not acoes_pendentes:
        return None

    # 1. Procura acao com prazo para hoje
    data_str = dt.isoformat()
    for a in acoes_pendentes:
        if a.data == data_str:
            return a

    # 2. Se nao tiver para hoje, busca acao atrasada (data <= hoje)
    for a in acoes_pendentes:
        if a.data <= data_str:
            return a

    # 3. Caso contrario, proxima pendente
    return acoes_pendentes[0]


def concluir(
    plano: Union[Plano, str],
    recurso: Union[Recurso, str],
    data: Optional[Union[str, date]] = None,
    db: Optional[ArmazenamentoCoach] = None,
    db_gtd: Optional[Any] = None,
    sincronizar_gtd: bool = True,
) -> Dict[str, Any]:
    """Marca a acao como feita, atualiza streak e calcula XP e subida de nivel."""
    banco = _obter_db(db)
    plano_id = plano.id if isinstance(plano, Plano) else str(plano)
    recurso_id = recurso.id if isinstance(recurso, Recurso) else str(recurso)
    dt = _para_data_obj(data)
    data_str = dt.isoformat()

    acao = banco.obter_acao_por_recurso(plano_id, recurso_id)
    if not acao:
        # Se nao achou por recurso direto, busca acao da data
        acoes_data = banco.listar_acoes(plano_id, data=data_str, estado="pendente")
        if acoes_data:
            acao = acoes_data[0]
            recurso_id = acao.recurso_id

    if not acao:
        raise ValueError(f"Acao nao encontrada para plano '{plano_id}' e recurso '{recurso_id}'.")

    pontuacao = banco.obter_pontuacao(plano_id) or Pontuacao(plano_id=plano_id)

    # Se a acao ja foi concluida anteriormente, evita computar novamente
    if acao.estado == "feito":
        return {
            "ok": True,
            "plano_id": plano_id,
            "recurso_id": recurso_id,
            "acao": acao.to_dict(),
            "xp_ganho": acao.pontos,
            "xp_total": pontuacao.xp_total,
            "nivel": pontuacao.nivel,
            "streak": pontuacao.streak,
            "subiu_de_nivel": False,
            "pontuacao": pontuacao.to_dict(),
        }

    rec_obj = banco.obter_recurso(recurso_id)
    tipo_recurso = rec_obj.tipo if rec_obj else "aula"

    # Atualiza streak
    ontem_str = (dt - timedelta(days=1)).isoformat()

    if pontuacao.ultima_data == ontem_str:
        pontuacao.streak += 1
    elif pontuacao.ultima_data == data_str:
        # Mesma data mantem streak
        if pontuacao.streak == 0:
            pontuacao.streak = 1
    else:
        pontuacao.streak = 1

    # Calculo de XP
    xp_base = XP_POR_TIPO.get(tipo_recurso, 15)
    bonus_streak = calcular_bonus_streak(pontuacao.streak)
    xp_ganho = xp_base + bonus_streak

    # Atualiza acao
    acao.estado = "feito"
    acao.concluido_em = datetime.now().isoformat(timespec="seconds")
    acao.pontos = xp_ganho
    banco.salvar_acao(acao)

    # Atualiza pontuacao
    pontuacao.xp_total += xp_ganho
    novo_nivel = calcular_nivel(pontuacao.xp_total)
    subiu_de_nivel = novo_nivel > pontuacao.nivel
    pontuacao.nivel = novo_nivel
    pontuacao.ultima_data = data_str
    banco.salvar_pontuacao(pontuacao)

    # Se a acao tiver ligacao com GTD, conclui la tambem
    if sincronizar_gtd and acao.gtd_item_id:
        try:
            from .integracao_gtd import concluir_tarefa_gtd_vinculada
            concluir_tarefa_gtd_vinculada(acao.gtd_item_id, db_gtd=db_gtd)
        except Exception as e:
            log.warning("Falha ao sincronizar conclusao com GTD: %s", e)

    return {
        "ok": True,
        "plano_id": plano_id,
        "recurso_id": recurso_id,
        "acao": acao.to_dict(),
        "xp_ganho": xp_ganho,
        "xp_total": pontuacao.xp_total,
        "nivel": pontuacao.nivel,
        "streak": pontuacao.streak,
        "subiu_de_nivel": subiu_de_nivel,
        "pontuacao": pontuacao.to_dict(),
    }


def resumo(
    plano: Union[Plano, str],
    db: Optional[ArmazenamentoCoach] = None,
) -> Dict[str, Any]:
    """Retorna o progresso geral, pontuacao, streak e proximos passos do plano."""
    banco = _obter_db(db)
    plano_obj = banco.obter_plano(plano) if isinstance(plano, str) else plano
    if not plano_obj:
        raise ValueError(f"Plano '{plano}' nao encontrado.")

    trilha_obj = banco.obter_trilha(plano_obj.trilha_id) or obter_trilha(plano_obj.trilha_id)
    pontuacao = banco.obter_pontuacao(plano_obj.id) or Pontuacao(plano_id=plano_obj.id)

    todas_acoes = banco.listar_acoes(plano_id=plano_obj.id)
    total = len(todas_acoes)
    feitas = sum(1 for a in todas_acoes if a.estado == "feito")
    pendentes = sum(1 for a in todas_acoes if a.estado == "pendente")
    percentual = round((feitas / total * 100.0), 1) if total > 0 else 0.0

    proximas: List[Dict[str, Any]] = []
    for a in todas_acoes:
        if a.estado == "pendente":
            rec = banco.obter_recurso(a.recurso_id)
            proximas.append({
                "acao_id": a.id,
                "recurso_id": a.recurso_id,
                "titulo": rec.titulo if rec else "Recurso",
                "tipo": rec.tipo if rec else "aula",
                "duracao_min": rec.duracao_min if rec else 15,
                "url": rec.url if rec else None,
                "data": a.data,
            })
            if len(proximas) >= 5:
                break

    return {
        "plano": plano_obj.to_dict(),
        "trilha": trilha_obj.to_dict() if trilha_obj else None,
        "pontuacao": pontuacao.to_dict(),
        "total_acoes": total,
        "concluidas": feitas,
        "pendentes": pendentes,
        "percentual": percentual,
        "xp_total": pontuacao.xp_total,
        "nivel": pontuacao.nivel,
        "streak": pontuacao.streak,
        "proximos_passos": proximas,
    }


def obter_ou_criar_plano_padrao(
    db: Optional[ArmazenamentoCoach] = None,
    trilha_id: str = "ingles_iniciante",
) -> Plano:
    """Retorna o plano ativo do usuario ou cria um automaticamente a partir da trilha de ingles."""
    banco = _obter_db(db)
    planos = banco.listar_planos(ativo_apenas=True)
    if planos:
        return planos[0]

    trilha_obj = banco.obter_trilha(trilha_id) or obter_trilha(trilha_id)
    if not trilha_obj:
        from .trilhas import carregar_todas_trilhas
        ts = carregar_todas_trilhas()
        if ts:
            trilha_obj = ts[0]
        else:
            raise ValueError("Nenhuma trilha encontrada para criar plano inicial.")

    return criar_plano(trilha_obj, ritmo={"dias_semana": 5, "minutos_dia": 30}, db=banco)
