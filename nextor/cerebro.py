"""Cerebro do Nextor: conversa com um modelo local (Ollama), com persona e memoria."""
import json
import urllib.request

from . import config
from .personas import persona


def _chamar_ollama(mensagem: str, sistema: str = "", num_predict: int = 120) -> str:
    corpo = {
        "model": config.MODELO,
        "messages": [
            {"role": "system", "content": sistema or persona(config.PERSONA, config.NOME)},
            {"role": "user", "content": mensagem},
        ],
        "stream": False,
        "options": {"temperature": 0.7, "num_predict": num_predict},
    }
    req = urllib.request.Request(
        config.OLLAMA_URL,
        data=json.dumps(corpo).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        dados = json.loads(resp.read().decode("utf-8"))
    return (dados.get("message", {}).get("content") or "").strip()


def ultimas_notas(n: int = 20) -> str:
    if not config.ANOTACOES.exists():
        return "(ainda nao ha anotacoes)"
    linhas = [l.strip() for l in config.ANOTACOES.read_text(encoding="utf-8").splitlines() if l.strip()]
    return "\n".join(linhas[-n:]) if linhas else "(ainda nao ha anotacoes)"


def _agenda_texto() -> str:
    try:
        from .agenda import eventos_proximos, resumo_falado
        evs = eventos_proximos(7)
        if not evs:
            return "(sem compromissos nos proximos 7 dias ou agenda nao configurada)"
        return resumo_falado(evs, prefixo_dia=True)
    except Exception:
        return "(agenda indisponivel)"


def conversar(mensagem: str) -> str:
    contexto = (
        f"{persona(config.PERSONA, config.NOME)}\n\nAnotacoes recentes (memoria):\n{ultimas_notas()}"
        f"\n\nProximos compromissos da agenda:\n{_agenda_texto()}"
    )
    return _chamar_ollama(mensagem, sistema=contexto)


if __name__ == "__main__":
    import sys
    print(conversar(" ".join(sys.argv[1:]) or "Oi Nextor, tudo bem?"))
