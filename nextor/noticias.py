"""Noticias do Nextor: manchetes via Google News RSS e resumo com a IA local."""
import urllib.parse

from . import config

try:
    import feedparser
except ImportError:
    feedparser = None

RSS = "https://news.google.com/rss/search?q={q}&hl=pt-BR&gl=BR&ceid=BR:pt-419"


def manchetes(assunto: str = "", n: int = 6) -> list:
    if feedparser is None:
        return []
    assunto = assunto or config.NOTICIAS_ASSUNTO
    url = RSS.format(q=urllib.parse.quote(f"{assunto} when:1d"))
    feed = feedparser.parse(url)
    itens = []
    for e in feed.entries[:n]:
        bruto = e.get("title", "")
        titulo = bruto.split(" - ")[0].strip()
        fonte = bruto.rsplit(" - ", 1)[-1].strip() if " - " in bruto else ""
        if titulo:
            itens.append({"titulo": titulo, "fonte": fonte})
    return itens


def resumir(assunto: str = "", n: int = 6) -> str:
    itens = manchetes(assunto, n)
    if not itens:
        return "Nao encontrei noticias novas sobre esse assunto hoje."
    lista = "\n".join(f"- {i['titulo']}" for i in itens)
    try:
        from .cerebro import _chamar_ollama
        prompt = (
            "Resuma para serem lidas em voz alta, em portugues do Brasil, as manchetes abaixo "
            "sobre " + (assunto or config.NOTICIAS_ASSUNTO) + ". Em no maximo quatro frases "
            "curtas, diga os destaques do dia, sem listar uma por uma, sem emojis e sem "
            "markdown. Manchetes:\n" + lista
        )
        resumo = _chamar_ollama(prompt)
        if resumo:
            return resumo
    except Exception:
        pass
    tres = "; ".join(i["titulo"] for i in itens[:3])
    return f"Destaques de hoje: {tres}."


if __name__ == "__main__":
    print(resumir())
