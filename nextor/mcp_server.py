"""
Servidor MCP do Nextor.

Expoe as habilidades do Nextor como ferramentas MCP, para que o Claude (ou outro
assistente/agente compativel com MCP) se conecte e use: anotar, ler notas, agenda,
noticias e falar no Nest.

Rodar (stdio, para clientes como o Claude Desktop / claude code):
    .venv/Scripts/python.exe -m nextor.mcp_server

Exemplo de configuracao num cliente MCP (stdio):
    command: <caminho>/.venv/Scripts/python.exe
    args: ["-m", "nextor.mcp_server"]
    cwd: <pasta do projeto>
"""
from datetime import datetime

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:
    class MCPServer:
        """Fallback leve quando a biblioteca mcp nao esta instalada no ambiente."""
        def __init__(self, name: str):
            self.name = name

        def tool(self, description: str = ""):
            def decorator(fn):
                return fn
            return decorator

        def run(self, *args, **kwargs):
            pass

from . import config

mcp = MCPServer("nextor")


@mcp.tool(description="Salva uma anotacao do usuario e confirma falando no Nest.")
def anotar(texto: str) -> str:
    carimbo = datetime.now().strftime("%Y-%m-%d %H:%M")
    with config.ANOTACOES.open("a", encoding="utf-8") as f:
        f.write(f"- [{carimbo}] {texto}\n")
    try:
        from .voz import falar
        falar(f"Anotei: {texto}")
    except Exception:
        pass
    return f"Anotado em {carimbo}: {texto}"


@mcp.tool(description="Devolve as ultimas anotacoes do usuario.")
def listar_notas() -> str:
    if not config.ANOTACOES.exists():
        return "Nenhuma nota ainda."
    return config.ANOTACOES.read_text(encoding="utf-8")


@mcp.tool(description="Compromissos da agenda. quando: 'hoje' ou 'proximos' (7 dias).")
def agenda(quando: str = "hoje") -> str:
    from .agenda import eventos_hoje, eventos_proximos, resumo_falado
    if quando.startswith("prox") or quando == "semana":
        return resumo_falado(eventos_proximos(7), prefixo_dia=True)
    return resumo_falado(eventos_hoje())


@mcp.tool(description="Agenda do dia detalhada com compromissos, reunioes, blocos livres e alertas de sobrecarga.")
def agenda_dia(quando: str = "hoje") -> str:
    from .agenda import eventos_dia, analisar_dia
    evs = eventos_dia()
    analise = analisar_dia(evs)

    partes = []
    if evs:
        partes.append(f"Compromissos de hoje ({len(evs)}):")
        for e in evs:
            hora = e["inicio"].strftime("%H:%M") if hasattr(e["inicio"], "strftime") else "Dia todo"
            tipo = " (Reuniao)" if e.get("eh_reuniao") else ""
            link = f" - Link: {e['link_video']}" if e.get("link_video") else ""
            partes.append(f"- {hora}: {e['titulo']}{tipo}{link}")
    else:
        partes.append("Nenhum compromisso marcado para hoje.")

    if analise.get("dia_cheio"):
        partes.append(f"\nAlerta de dia cheio: {analise.get('motivo_dia_cheio')}")

    blocos = analise.get("blocos_livres", [])
    if blocos:
        partes.append(f"\nEspacos livres ({analise.get('horas_livres', 0)}h total):")
        for b in blocos:
            partes.append(f"- {b['inicio_str']} as {b['fim_str']} ({b['duracao_minutos']} min)")

    sugestoes = analise.get("sugestoes_timeboxing", [])
    if sugestoes:
        partes.append("\nSugestoes de timeboxing:")
        for s in sugestoes:
            partes.append(f"- {s['inicio_str']} as {s['fim_str']}: {s['titulo']} ({s['contexto']})")

    return "\n".join(partes)


@mcp.tool(description="Informa a proxima reuniao agendada com horario e link de acesso.")
def proxima_reuniao() -> str:
    from .agenda import proxima_reuniao as _proxima_reuniao
    prox = _proxima_reuniao()
    if not prox:
        return "Nenhuma reuniao agendada para os proximos dias."

    ini = prox["inicio"]
    hora_str = ini.strftime("%H:%M") if hasattr(ini, "strftime") else str(ini)
    data_str = ini.strftime("%d/%m") if hasattr(ini, "strftime") else ""
    link = f" Link: {prox['link_video']}" if prox.get("link_video") else " (sem link de video)"
    return f"Proxima reuniao: '{prox['titulo']}' em {data_str} as {hora_str}.{link}"


@mcp.tool(description="Lista os blocos de tempo livres do dia com sugestoes de foco e descanso.")
def blocos_livres(quando: str = "hoje") -> str:
    from .agenda import eventos_dia, calcular_blocos_livres, sugerir_timeboxing
    evs = eventos_dia()
    blocos = calcular_blocos_livres(evs)
    if not blocos:
        return "Nenhum bloco livre disponivel no horario de expediente hoje."

    sugestoes = sugerir_timeboxing(blocos)
    linhas = ["Blocos livres de hoje:"]
    for b in blocos:
        linhas.append(f"- {b['inicio_str']} as {b['fim_str']} ({b['duracao_minutos']} minutos)")

    if sugestoes:
        linhas.append("\nSugestoes de foco:")
        for s in sugestoes:
            linhas.append(f"- {s['inicio_str']} as {s['fim_str']}: {s['titulo']} ({s['contexto']})")

    return "\n".join(linhas)


@mcp.tool(description="Resumo das noticias recentes de um assunto (padrao: o do .env).")
def noticias(assunto: str = "") -> str:
    from .noticias import resumir
    return resumir(assunto)


@mcp.tool(description="Fala um texto em voz alta no Google Nest do usuario.")
def falar(texto: str) -> str:
    from .voz import falar as _falar
    _falar(texto)
    return "Falado no Nest."


@mcp.tool(description="Captura uma nova tarefa ou ideia para a caixa de entrada (Inbox) do GTD.")
def gtd_capturar(titulo: str, nota: str = "", contexto: str = "@qualquer") -> str:
    from .gtd import capturar
    item = capturar(titulo=titulo, nota=nota, contexto=contexto)
    return f"Capturado no GTD: {item.titulo} ({item.contexto})"


@mcp.tool(description="Consulta a agenda do dia completa do GTD (eventos, tarefas prioritarias e meta de leitura).")
def gtd_dia() -> str:
    from .gtd import agenda_do_dia
    res = agenda_do_dia()
    return res.get("resumo_falado", "Agenda do dia indisponivel.")


@mcp.tool(description="Processa um item do GTD mudando seu destino (proxima, aguardando, algum_dia, feito, lixo, projeto ou leitura).")
def gtd_processar(item_id: str, destino: str, contexto: str = "") -> str:
    from .gtd import processar
    resultado = processar(item_id=item_id, novo_estado=destino, novo_contexto=contexto or None)
    if resultado is None:
        return f"Item {item_id} descartado."
    return f"Item {item_id} movido para {resultado.estado}."


@mcp.tool(description="Registra paginas lidas e atualiza o progresso da meta diaria de leitura.")
def leitura_progresso(paginas: int, leitura_id: str = "") -> str:
    from .gtd import atualizar_progresso, listar_leituras
    id_alvo = leitura_id
    if not id_alvo:
        leituras_ativas = listar_leituras(estado="lendo")
        if not leituras_ativas:
            leituras_ativas = listar_leituras(estado="quero_ler")
        if not leituras_ativas:
            from .gtd.armazenamento import ArmazenamentoGTD
            banco = ArmazenamentoGTD()
            total = banco.registrar_progresso_leitura("geral", paginas)
            meta = getattr(config, "LEITURA_META_DIARIA", 20)
            status = "Meta batida!" if total >= meta else f"Faltam {max(0, meta - total)} paginas."
            return f"Registradas {paginas} paginas. Total hoje: {total}/{meta}. {status}"
        id_alvo = leituras_ativas[0].id

    res = atualizar_progresso(id_alvo, paginas)
    status_meta = "Meta batida!" if res["meta_atingida"] else f"Faltam {res['faltam_paginas']} paginas para a meta."
    return f"Registradas {paginas} paginas. Total hoje: {res['paginas_lidas_hoje']}/{res['meta_diaria']}. {status_meta}"


@mcp.tool(description="Troca o metodo ativo de produtividade (gtd, para, eisenhower, kanban).")
def gtd_trocar_metodo(metodo: str) -> str:
    from .gtd.configuracao import salvar_config
    from .gtd.metodos import obter_metodo
    m = obter_metodo(metodo)
    salvar_config({"metodo_ativo": m.slug})
    return f"Metodo alterado para {m.nome}."


@mcp.tool(description="Inicia uma sessao Pomodoro de foco.")
def pomodoro_iniciar(minutos: int = 25, item_id: str = "") -> str:
    from .gtd.metodos import pomodoro
    res = pomodoro.iniciar(item_id=item_id or None, duracao_min=minutos)
    return f"Pomodoro iniciado: {res['tempo_formatado']} minutos de foco."


@mcp.tool(description="Interrompe a sessao Pomodoro ativa.")
def pomodoro_parar() -> str:
    from .gtd.metodos import pomodoro
    pomodoro.parar()
    return "Pomodoro interrompido."


@mcp.tool(description="Consulta o status atual do Pomodoro.")
def pomodoro_estado() -> str:
    from .gtd.metodos import pomodoro
    res = pomodoro.obter_estado()
    if not res["ativo"]:
        return "Nenhum Pomodoro ativo no momento."
    return f"Pomodoro em andamento ({res['modo']}): {res['tempo_formatado']} restantes."


@mcp.tool(description="Envia notificacao de teste pelos canais de notificacao.")
def notificacao_teste(canal: str = "", mensagem: str = "Teste de notificacao Nextor") -> str:
    from .notificacoes import notificar
    from .gtd.configuracao import carregar_config
    cfg = carregar_config()
    canais_especificos = [canal] if canal else None
    res = notificar(
        evento="lembrete",
        titulo="Teste Nextor",
        corpo=mensagem,
        canais_especificos=canais_especificos,
        config_usuario=cfg,
    )
    if res["silenciado"]:
        return "Notificacao silenciada pelo horario de silencio."
    if res["despachados"]:
        return f"Notificacao enviada com sucesso para: {', '.join(res['despachados'])}."
    return "Nenhum canal ativo ou configurado para envio."


@mcp.tool(description="Consulta a acao de estudo do dia recomendada pelo Coach de Estudos.")
def coach_acao_do_dia(plano_id: str = "") -> str:
    import json
    from .coach import ArmazenamentoCoach, acao_do_dia, obter_ou_criar_plano_padrao
    banco = ArmazenamentoCoach()
    plano = banco.obter_plano(plano_id) if plano_id else obter_ou_criar_plano_padrao(banco)
    if not plano:
        return "Nenhum plano de estudos ativo encontrado."
    acao = acao_do_dia(plano, db=banco)
    if not acao:
        # Verifica se o dia esta saturado ou se tudo foi concluido
        res = banco.listar_acoes(plano.id, estado="pendente")
        if not res:
            return "Parabens! Todas as acoes da sua trilha de estudos estao concluidas."
        return "Sua agenda hoje possui compromissos prioritarios ou esta cheia. Recomendado descansar ou focar nas entregas."
    rec = banco.obter_recurso(acao.recurso_id)
    titulo_rec = rec.titulo if rec else "Estudo do dia"
    tipo = rec.tipo if rec else "aula"
    duracao = rec.duracao_min if rec else 15
    link = f" Link: {rec.url}" if (rec and rec.url) else ""
    return f"Acao de estudo de hoje: {titulo_rec} ({duracao} min, tipo: {tipo}).{link}"


@mcp.tool(description="Conclui uma acao de estudo, ganha XP, avanca streak e atualiza o nivel no Coach.")
def coach_concluir(recurso_id: str = "", plano_id: str = "") -> str:
    from .coach import ArmazenamentoCoach, acao_do_dia, concluir, obter_ou_criar_plano_padrao
    banco = ArmazenamentoCoach()
    plano = banco.obter_plano(plano_id) if plano_id else obter_ou_criar_plano_padrao(banco)
    if not plano:
        return "Nenhum plano de estudos ativo encontrado."

    r_id = recurso_id
    if not r_id:
        acao_pend = acao_do_dia(plano, db=banco, verificar_dia_saturado=False)
        if not acao_pend:
            return "Nenhuma acao de estudo pendente para concluir hoje."
        r_id = acao_pend.recurso_id

    res = concluir(plano=plano.id, recurso=r_id, db=banco)
    rec = banco.obter_recurso(r_id)
    titulo = rec.titulo if rec else "Licao"
    msg = (
        f"Licao '{titulo}' concluida com sucesso! "
        f"+{res['xp_ganho']} XP. Total: {res['xp_total']} XP (Nivel {res['nivel']}). "
        f"Sequencia (streak): {res['streak']} dias."
    )
    if res.get("subiu_de_nivel"):
        msg += f" Parabens! Voce subiu para o nivel {res['nivel']}!"
    return msg


@mcp.tool(description="Consulta o progresso geral, XP, nivel, streak e proximas licoes do plano de estudos.")
def coach_progresso(plano_id: str = "") -> str:
    from .coach import ArmazenamentoCoach, obter_ou_criar_plano_padrao, resumo
    banco = ArmazenamentoCoach()
    plano = banco.obter_plano(plano_id) if plano_id else obter_ou_criar_plano_padrao(banco)
    if not plano:
        return "Nenhum plano de estudos ativo encontrado."
    r = resumo(plano, db=banco)
    trilha_tit = r.get("trilha", {}).get("titulo", "Trilha") if r.get("trilha") else "Trilha"
    return (
        f"Trilha '{trilha_tit}': {r['concluidas']}/{r['total_acoes']} licoes feitas ({r['percentual']}%). "
        f"Nivel {r['nivel']} com {r['xp_total']} XP acumulados. "
        f"Sequencia de estudo: {r['streak']} dias consecutivos."
    )


@mcp.tool(description="Cria uma nova trilha de estudos personalizada no Coach.")
def coach_criar_trilha(
    titulo: str,
    habilidade: str,
    nivel: str = "iniciante",
    descricao: str = "",
    recursos_json: str = "[]",
) -> str:
    import json
    from .coach import criar_trilha
    recs = []
    if recursos_json:
        try:
            recs = json.loads(recursos_json)
        except Exception:
            recs = []
    t = criar_trilha(
        id_trilha="",
        titulo=titulo,
        habilidade=habilidade,
        nivel=nivel,
        descricao=descricao,
        recursos=recs,
    )
    return f"Trilha '{t.titulo}' criada com sucesso (ID: {t.id}) com {len(t.recursos)} recursos."


@mcp.tool(description="Traduz ao vivo um artigo ou pagina aberta pelo usuario no NexRead mantendo os blocos de layout.")
def nexread_traduzir_pagina(
    conteudo_ou_html: str,
    idioma_destino: str = "pt-BR",
    titulo: str = "",
    url: str = "",
    modo_layout: str = "bilingue",
) -> str:
    from .nexread import traduzir_pagina_ao_vivo
    artigo = traduzir_pagina_ao_vivo(
        conteudo_html=conteudo_ou_html,
        url=url,
        titulo=titulo,
        idioma_destino=idioma_destino,
        modo_layout=modo_layout,
        aberta_pelo_usuario=True,
    )
    resumo_blocos = " ".join(b.texto_traduzido for b in artigo.blocos[:2])
    return (
        f"Artigo traduzido no NexRead (ID: {artigo.id}): '{artigo.titulo_traduzido}' "
        f"({len(artigo.blocos)} blocos). Trecho inicial: {resumo_blocos}"
    )


@mcp.tool(description="Marca e anota um trecho de um artigo aberto no NexRead.")
def nexread_marcar_trecho(
    artigo_id: str,
    trecho: str,
    nota: str = "",
    cor: str = "amarelo",
) -> str:
    from .nexread import marcar_trecho
    m = marcar_trecho(artigo_id=artigo_id, trecho=trecho, nota=nota, cor=cor)
    detalhe_nota = f" com nota '{m.nota}'" if m.nota else ""
    return f"Trecho marcado em {m.cor} no artigo {artigo_id} (ID: {m.id}){detalhe_nota}: \"{m.trecho_original}\""


@mcp.tool(description="Registra uma nota de voz ou gravacao de estudo vinculada a um artigo no NexRead.")
def nexread_gravar_nota(
    artigo_id: str,
    transcricao: str,
    titulo: str = "Nota de voz do estudo",
    duracao_seg: int = 0,
) -> str:
    from .nexread import gravar_nota_leitura
    g = gravar_nota_leitura(
        artigo_id=artigo_id,
        transcricao=transcricao,
        titulo=titulo,
        duracao_seg=duracao_seg,
    )
    return f"Gravacao '{g.titulo}' salva no artigo {artigo_id} (ID: {g.id}): {g.transcricao}"


@mcp.tool(description="Salva o artigo traduzido, marcacoes e gravacoes do NexRead na biblioteca do modo estudante.")
def nexread_salvar_estudos(artigo_id: str, disciplina: str) -> str:
    from .nexread import salvar_na_biblioteca_estudos
    res = salvar_na_biblioteca_estudos(artigo_id=artigo_id, disciplina_nome=disciplina)
    return res.get("aviso") or f"Artigo salvo na disciplina {disciplina}."


@mcp.tool(description="Conversa com a IA sobre o tema do artigo no NexRead (perguntar, resumir, discutir) citando as fontes do texto.")
def nexread_conversar(
    artigo_id: str,
    pergunta: str = "",
    acao: str = "perguntar",
    buscar_fontes_cientificas: bool = False,
) -> str:
    from .nexread import conversar_sobre_artigo
    res = conversar_sobre_artigo(
        artigo_id=artigo_id,
        pergunta=pergunta,
        acao=acao,
        buscar_fontes_cientificas=buscar_fontes_cientificas,
    )
    fontes_str = "; ".join(res.get("fontes") or [])
    return f"{res.get('resposta', '')} (Fontes: {fontes_str})"


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
