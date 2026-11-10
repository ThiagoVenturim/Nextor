"""Logica do framework GTD (A Arte de Fazer Acontecer) para o Nextor.

Implementa os cinco passos do fluxo de trabalho GTD:
1. Capturar (inbox)
2. Esclarecer / Processar (proxima acao, projeto, leitura, algum dia, aguardando ou lixo)
3. Organizar (contextos: @faculdade, @casa, @trabalho, @academia, @leitura, @qualquer)
4. Refletir (agenda do dia e revisao semanal de projetos sem proxima acao)
5. Engajar (sugestao de ordem do dia)
"""
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
import uuid

from .. import config
from .armazenamento import ArmazenamentoGTD
from .modelos import (
    Item,
    Projeto,
    Leitura,
    CONTEXTOS_PERMITIDOS,
    normalizar_contexto,
    normalizar_prazo,
)

ORDEM_CONTEXTOS_DIA = (
    "@trabalho",
    "@faculdade",
    "@casa",
    "@academia",
    "@estudo",
    "@leitura",
    "@qualquer",
)


def _obter_db(db: Optional[ArmazenamentoGTD]) -> ArmazenamentoGTD:
    return db if db is not None else ArmazenamentoGTD()


def capturar(
    titulo: str,
    nota: str = "",
    contexto: str = "@qualquer",
    energia: str = "media",
    prazo: Optional[str] = None,
    projeto_id: Optional[str] = None,
    origem: str = "local",
    ref_externa: Optional[str] = None,
    db: Optional[ArmazenamentoGTD] = None,
) -> Item:
    """Captura rapida para a caixa de entrada (Inbox)."""
    t = (titulo or "").strip()
    if not t:
        raise ValueError("O titulo da tarefa nao pode ser vazio.")

    item = Item(
        id=str(uuid.uuid4()),
        titulo=t,
        nota=(nota or "").strip(),
        contexto=normalizar_contexto(contexto),
        estado="inbox",
        projeto_id=projeto_id,
        prazo=normalizar_prazo(prazo),
        energia=energia if energia in ("baixa", "media", "alta") else "media",
        origem=origem,
        ref_externa=ref_externa,
    )
    banco = _obter_db(db)
    return banco.salvar_item(item)


def processar(
    item_id: str,
    novo_estado: str,
    novo_contexto: Optional[str] = None,
    projeto_id: Optional[str] = None,
    prazo: Optional[str] = None,
    energia: Optional[str] = None,
    db: Optional[ArmazenamentoGTD] = None,
) -> Optional[Item]:
    """Processa um item da caixa de entrada ou atualiza o estado de uma acao.

    novo_estado pode ser:
    - 'lixo': exclui o item do banco e retorna None.
    - 'projeto': converte o item em um novo Projeto ativo e conclui o item.
    - 'leitura': converte o item em uma nova Leitura ('quero_ler') e conclui o item.
    - 'proxima', 'aguardando', 'algum_dia', 'inbox', 'feito': atualiza o item.
    """
    banco = _obter_db(db)
    item = banco.obter_item(item_id)
    if not item:
        raise ValueError(f"Item com id '{item_id}' nao encontrado.")

    estado_alvo = (novo_estado or "").strip().lower()

    if estado_alvo == "lixo":
        banco.remover_item(item.id)
        return None

    if estado_alvo == "projeto":
        projeto = Projeto(
            id=str(uuid.uuid4()),
            nome=item.titulo,
            descricao=item.nota,
            estado="ativo",
        )
        banco.salvar_projeto(projeto)
        item.estado = "feito"
        item.concluido_em = datetime.now().isoformat(timespec="seconds")
        item.projeto_id = projeto.id
        return banco.salvar_item(item)

    if estado_alvo == "leitura":
        leitura = Leitura(
            id=str(uuid.uuid4()),
            titulo=item.titulo,
            autor="",
            tipo="livro",
            estado="quero_ler",
            paginas_total=0,
            paginas_lidas=0,
            fonte_url=item.nota if item.nota.startswith("http") else "",
        )
        banco.salvar_leitura(leitura)
        item.estado = "feito"
        item.concluido_em = datetime.now().isoformat(timespec="seconds")
        return banco.salvar_item(item)

    if estado_alvo in ("inbox", "proxima", "aguardando", "algum_dia", "feito"):
        item.estado = estado_alvo
        if novo_contexto:
            item.contexto = normalizar_contexto(novo_contexto)
        if projeto_id is not None:
            item.projeto_id = projeto_id or None
        if prazo is not None:
            item.prazo = normalizar_prazo(prazo)
        if energia:
            item.energia = energia if energia in ("baixa", "media", "alta") else item.energia

        if estado_alvo == "feito":
            item.concluido_em = datetime.now().isoformat(timespec="seconds")
            if item.origem == "coach" or (item.ref_externa and item.ref_externa.startswith("coach:")):
                try:
                    from ..coach.integracao_gtd import sincronizar_conclusao_gtd
                    sincronizar_conclusao_gtd(item.id, db_gtd=banco)
                except Exception:
                    pass
        else:
            item.concluido_em = None

        return banco.salvar_item(item)

    raise ValueError(f"Estado desconhecido: '{novo_estado}'.")


def listar_por_contexto(
    contexto: str,
    estado: str = "proxima",
    db: Optional[ArmazenamentoGTD] = None,
) -> List[Item]:
    """Lista tarefas ativas filtradas por contexto."""
    banco = _obter_db(db)
    ctx_norm = normalizar_contexto(contexto)
    return banco.listar_itens(estado=estado, contexto=ctx_norm)


def agenda_do_dia(db: Optional[ArmazenamentoGTD] = None) -> Dict[str, Any]:
    """Reune a agenda do dia a partir de 3 fontes:

    1. Eventos da Google Agenda (nextor/agenda.py eventos_hoje)
    2. Proximas acoes do GTD (priorizando prazo hoje ou atrasado)
    3. Meta de leitura do dia e progresso atual
    """
    banco = _obter_db(db)
    hoje_iso = date.today().isoformat()

    # 1. Google Agenda
    eventos: List[Dict[str, Any]] = []
    analise_agenda: Dict[str, Any] = {}
    try:
        from .. import agenda
        if hasattr(agenda, "eventos_hoje"):
            evs = agenda.eventos_hoje() or []
            if hasattr(agenda, "analisar_dia"):
                analise_agenda = agenda.analisar_dia(evs)
            for e in evs:
                inicio = e.get("inicio")
                hora_str = inicio.strftime("%H:%M") if isinstance(inicio, datetime) else "Dia todo"
                eventos.append({
                    "uid": e.get("uid", ""),
                    "titulo": e.get("titulo", ""),
                    "horario": hora_str,
                    "dia_inteiro": e.get("dia_inteiro", False),
                    "eh_reuniao": e.get("eh_reuniao", False),
                    "link_video": e.get("link_video"),
                    "participantes": e.get("participantes", []),
                    "duracao_minutos": e.get("duracao_minutos", 0),
                })
    except Exception:
        eventos = []
        analise_agenda = {}

    # 2. Proximas acoes do GTD
    todas_proximas = banco.listar_itens(estado="proxima")

    atrasadas = []
    hoje_acoes = []
    sem_prazo_ou_futuras = []

    for item in todas_proximas:
        if item.prazo:
            if item.prazo < hoje_iso:
                atrasadas.append(item.to_dict())
            elif item.prazo == hoje_iso:
                hoje_acoes.append(item.to_dict())
            else:
                sem_prazo_ou_futuras.append(item.to_dict())
        else:
            sem_prazo_ou_futuras.append(item.to_dict())

    # Ordenacao sugerida do dia por contexto e prazo
    def _ordem_chave(i: Dict[str, Any]) -> int:
        ctx = i.get("contexto", "@qualquer")
        return ORDEM_CONTEXTOS_DIA.index(ctx) if ctx in ORDEM_CONTEXTOS_DIA else 99

    hoje_acoes.sort(key=_ordem_chave)
    sem_prazo_ou_futuras.sort(key=_ordem_chave)
    acoes_prioritarias = atrasadas + hoje_acoes + sem_prazo_ou_futuras[:5]

    # 3. Meta de leitura
    meta_diaria = getattr(config, "LEITURA_META_DIARIA", 20)
    paginas_lidas_hoje = banco.paginas_lidas_na_data(hoje_iso)
    leituras_ativas = banco.listar_leituras(estado="lendo")
    livro_atual = leituras_ativas[0].to_dict() if leituras_ativas else None

    leitura_info = {
        "meta_diaria": meta_diaria,
        "paginas_lidas_hoje": paginas_lidas_hoje,
        "faltam_paginas": max(0, meta_diaria - paginas_lidas_hoje),
        "meta_atingida": paginas_lidas_hoje >= meta_diaria,
        "livro_atual": livro_atual,
    }

    # Resumo falado
    partes_resumo = []
    total_reunioes = analise_agenda.get("total_reunioes", sum(1 for e in eventos if e.get("eh_reuniao")))
    if eventos:
        if total_reunioes > 0:
            partes_resumo.append(f"Voce tem {len(eventos)} compromissos na agenda, sendo {total_reunioes} reuniao(oes).")
        else:
            partes_resumo.append(f"Voce tem {len(eventos)} compromissos na agenda.")
    else:
        partes_resumo.append("Nenhum compromisso marcado na agenda.")

    if analise_agenda.get("conflitos"):
        partes_resumo.append(f"Atencao: {len(analise_agenda['conflitos'])} conflito(s) de horario detectado(s).")

    if analise_agenda.get("dia_cheio"):
        partes_resumo.append("Dia cheio com pouca folga entre compromissos.")

    qtd_urgentes = len(atrasadas) + len(hoje_acoes)
    if qtd_urgentes > 0:
        partes_resumo.append(f"{qtd_urgentes} proximas acoes para hoje ou atrasadas.")
    elif todas_proximas:
        partes_resumo.append(f"{len(todas_proximas)} proximas acoes disponiveis.")
    else:
        partes_resumo.append("Nenhuma proxima acao pendente.")

    if leitura_info["meta_atingida"]:
        partes_resumo.append(f"Meta de leitura do dia batida com {paginas_lidas_hoje} paginas.")
    else:
        partes_resumo.append(
            f"Meta de leitura: {paginas_lidas_hoje} de {meta_diaria} paginas "
            f"(faltam {leitura_info['faltam_paginas']})."
        )

    resumo_falado = " ".join(partes_resumo)

    return {
        "data": hoje_iso,
        "eventos_agenda": eventos,
        "reunioes": analise_agenda.get("reunioes", [e for e in eventos if e.get("eh_reuniao")]),
        "blocos_livres": analise_agenda.get("blocos_livres", []),
        "conflitos": analise_agenda.get("conflitos", []),
        "dia_cheio": analise_agenda.get("dia_cheio", False),
        "motivo_dia_cheio": analise_agenda.get("motivo_dia_cheio", ""),
        "sugestoes_timeboxing": analise_agenda.get("sugestoes_timeboxing", []),
        "acoes_urgentes": atrasadas + hoje_acoes,
        "proximas_acoes": acoes_prioritarias,
        "leitura": leitura_info,
        "resumo_falado": resumo_falado,
    }


def criar_tarefa_de_evento(
    evento: Dict[str, Any],
    contexto: str = "@trabalho",
    db: Optional[ArmazenamentoGTD] = None,
) -> Item:
    """Cria uma tarefa no GTD a partir de um evento do calendario."""
    banco = _obter_db(db)
    titulo = str(evento.get("titulo") or evento.get("summary") or "Tarefa do Calendario").strip()
    inicio = evento.get("inicio")
    prazo = None
    if isinstance(inicio, datetime):
        prazo = inicio.date().isoformat()
    elif isinstance(inicio, date):
        prazo = inicio.isoformat()
    elif isinstance(inicio, str) and len(inicio) >= 10:
        prazo = inicio[:10]

    nota_partes = []
    if evento.get("descricao"):
        nota_partes.append(str(evento["descricao"]).strip())
    if evento.get("link_video"):
        nota_partes.append(f"Link de video: {evento['link_video']}")
    if evento.get("local"):
        nota_partes.append(f"Local: {evento['local']}")

    nota = "\n".join(nota_partes)
    uid = str(evento.get("uid") or f"agenda:{titulo}-{prazo}")
    ref_externa = f"agenda:{uid}" if not uid.startswith("agenda:") else uid

    # Evita duplicatas se ja existir
    existente = banco.buscar_item_por_ref(ref_externa)
    if existente:
        return existente

    item = Item(
        id=str(uuid.uuid4()),
        titulo=titulo,
        nota=nota,
        contexto=normalizar_contexto(contexto),
        estado="proxima",
        prazo=prazo,
        energia="media",
        origem="agenda",
        ref_externa=ref_externa,
    )
    return banco.salvar_item(item)


def criar_evento_de_tarefa(
    item_id: str,
    horario: str = "09:00",
    duracao_minutos: int = 60,
    db: Optional[ArmazenamentoGTD] = None,
) -> Dict[str, Any]:
    """Cria a representacao de um evento de calendario a partir de uma tarefa GTD com prazo."""
    banco = _obter_db(db)
    item = banco.obter_item(item_id)
    if not item:
        raise ValueError(f"Item com id '{item_id}' nao encontrado.")

    prazo_str = item.prazo or date.today().isoformat()
    try:
        ano, mes, dia = map(int, prazo_str.split("-"))
        d_prazo = date(ano, mes, dia)
    except Exception:
        d_prazo = date.today()

    try:
        h, m = map(int, horario.strip().split(":"))
    except Exception:
        h, m = 9, 0

    from ..agenda import TZ
    inicio = datetime(d_prazo.year, d_prazo.month, d_prazo.day, h, m, tzinfo=TZ)
    fim = inicio + timedelta(minutes=duracao_minutos)

    evento = {
        "uid": f"gtd:item:{item.id}",
        "titulo": item.titulo,
        "inicio": inicio,
        "fim": fim,
        "dia_inteiro": False,
        "duracao_minutos": duracao_minutos,
        "descricao": item.nota or f"Tarefa do GTD [{item.contexto}]",
        "local": "",
        "url": "",
        "participantes": [],
        "link_video": None,
        "eh_reuniao": False,
        "item_id": item.id,
    }

    # Atualiza a nota do item para registrar agendamento
    marca = f"[Agendado para {prazo_str} {horario}]"
    if marca not in item.nota:
        item.nota = f"{item.nota}\n{marca}".strip()
        banco.salvar_item(item)

    return evento


def revisao_semanal(db: Optional[ArmazenamentoGTD] = None) -> Dict[str, Any]:
    """Executa a revisao semanal do GTD:

    - Identifica itens parados na caixa de entrada
    - Identifica projetos ativos sem nenhuma proxima acao definida
    - Lista compromissos aguardando terceiros
    - Lista itens da pasta 'algum dia / talvez'
    """
    banco = _obter_db(db)
    agora = datetime.now()
    limite_inbox_parado = agora - timedelta(days=2)

    itens_inbox = banco.listar_itens(estado="inbox")
    itens_parados = []
    for item in itens_inbox:
        try:
            dt_criacao = datetime.fromisoformat(item.criado_em)
            if dt_criacao < limite_inbox_parado:
                itens_parados.append(item.to_dict())
        except Exception:
            itens_parados.append(item.to_dict())

    # Projetos sem proxima acao
    projetos_ativos = banco.listar_projetos(estado="ativo")
    proximas = banco.listar_itens(estado="proxima")
    projetos_com_acao = {p.projeto_id for p in proximas if p.projeto_id}

    projetos_sem_acao = [
        proj.to_dict() for proj in projetos_ativos if proj.id not in projetos_com_acao
    ]

    aguardando = [i.to_dict() for i in banco.listar_itens(estado="aguardando")]
    algum_dia = [i.to_dict() for i in banco.listar_itens(estado="algum_dia")]

    resumo = (
        f"Revisao semanal: {len(itens_inbox)} itens na caixa de entrada "
        f"({len(itens_parados)} parados ha mais de 2 dias), "
        f"{len(projetos_sem_acao)} projetos ativos sem proxima acao, "
        f"{len(aguardando)} acoes aguardando e {len(algum_dia)} em algum dia."
    )

    return {
        "itens_inbox_total": len(itens_inbox),
        "itens_parados_inbox": itens_parados,
        "projetos_ativos_total": len(projetos_ativos),
        "projetos_sem_proxima_acao": projetos_sem_acao,
        "itens_aguardando": aguardando,
        "itens_algum_dia": algum_dia,
        "resumo": resumo,
    }
