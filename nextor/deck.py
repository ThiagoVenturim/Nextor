"""Ponte com o NexDeck: aperta botoes do deck do PC por voz ("no computador, bloquear").

Precisa de NEXTOR_DECK_URL e NEXTOR_DECK_TOKEN (token de data/secret.json do NexDeck).
"""
import json
import unicodedata
import urllib.error
import urllib.request

from . import config


def _normaliza(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return " ".join(s.lower().replace("+", " mais ").replace("-", " menos ").split())


def _chamar(metodo: str, caminho: str, corpo: dict | None = None) -> dict:
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(
        f"{config.DECK_URL}/api{caminho}",
        data=dados,
        method=metodo,
        headers={"Authorization": f"Bearer {config.DECK_TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310 - URL vem do .env
        return json.loads(r.read() or b"{}")


def configurado() -> bool:
    return bool(config.DECK_URL and config.DECK_TOKEN)


def botoes() -> list[dict]:
    deck = _chamar("GET", "/deck")
    return [b for pagina in deck.get("pages", []) for b in pagina.get("buttons", [])]


def achar(nome: str, lista: list[dict]) -> dict | None:
    alvo = _normaliza(nome)
    if not alvo:
        return None
    exatos = [b for b in lista if _normaliza(b["label"]) == alvo]
    if exatos:
        return exatos[0]
    parciais = [b for b in lista if alvo in _normaliza(b["label"]) or _normaliza(b["label"]) in alvo]
    return parciais[0] if len(parciais) == 1 else None


def apertar(nome: str) -> str:
    """Aperta o botao do deck com esse nome e devolve a frase para falar."""
    if not configurado():
        return "O NexDeck nao esta configurado."
    try:
        botao = achar(nome, botoes())
        if botao is None:
            return f"Nao achei o botao {nome} no deck."
        _chamar("POST", f"/buttons/{botao['id']}/run", {})
        return f"Feito: {botao['label']}."
    except urllib.error.HTTPError as e:
        if e.code == 409:
            return "Essa acao precisa de confirmacao no celular."
        if e.code == 401:
            return "O token do NexDeck esta errado."
        return "O NexDeck nao conseguiu executar."
    except (urllib.error.URLError, TimeoutError, OSError):
        return "O NexDeck esta fora do ar."
