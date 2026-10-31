"""
Nextor - noticias.

Busca manchetes recentes sobre um assunto (via Google News RSS, sem chave de API) e
resume em poucas frases para o Nest falar. O resumo usa o cerebro local (Ollama).

Exemplo: todo dia trazer e resumir noticias de IA generativa.
"""
import urllib.parse
from datetime import datetime

try:
    import feedparser
except ImportError:
    feedparser = None

try:
    from settings import NOTICIAS_ASSUNTO
except ImportError:
    NOTICIAS_ASSUNTO = "inteligencia artificial generativa"

RSS = "https://news.google.com/rss/search?q={q}&hl=pt-BR&gl=BR&ceid=BR:pt-419"


def manchetes(assunto: str = "", n: int = 6) -> list:
    if feedparser is None:
        return []
    assunto = assunto or NOTICIAS_ASSUNTO
    url = RSS.format(q=urllib.parse.quote(f"{assunto} when:1d"))
    feed = feedparser.parse(url)
    itens = []
    for e in feed.entries[:n]:
        titulo = e.get("title", "").split(" - ")[0].strip()
        fonte = ""
        if " - " in e.get("title", ""):
            fonte = e.get("title", "").rsplit(" - ", 1)[-1].strip()
        if titulo:
            itens.append({"titulo": titulo, "fonte": fonte})
    return itens


def resumir(assunto: str = "", n: int = 6) -> str:
    itens = manchetes(assunto, n)
    if not itens:
        return "Nao encontrei noticias novas sobre esse assunto hoje."
    lista = "\n".join(f"- {i['titulo']}" for i in itens)
    try:
        from nextor_brain import _chamar_ollama  # reaproveita o cliente do cerebro
        prompt = (
            "Resuma para serem lidas em voz alta, em portugues do Brasil, as manchetes "
            "abaixo sobre " + (assunto or NOTICIAS_ASSUNTO) + ". Em no maximo quatro frases "
            "curtas, diga os destaques do dia, sem listar uma por uma, sem emojis e sem "
            "markdown. Manchetes:\n" + lista
        )
        resumo = _chamar_ollama(prompt)
        if resumo:
            return resumo
    except Exception:
        pass
    # Sem IA disponivel: le as tres primeiras manchetes.
    tres = "; ".join(i["titulo"] for i in itens[:3])
    return f"Destaques de hoje: {tres}."


if __name__ == "__main__":
    print(resumir())
