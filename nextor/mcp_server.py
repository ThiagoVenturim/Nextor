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


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
