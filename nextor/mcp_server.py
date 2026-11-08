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

from mcp.server.mcpserver import MCPServer

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
            return "Nenhuma leitura ativa cadastrada no momento."
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


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
