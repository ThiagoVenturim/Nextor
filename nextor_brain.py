"""
Nextor - cerebro local.

Conversa com um modelo de IA rodando no proprio notebook (Ollama) e usa as
anotacoes como memoria. Sem nuvem: tudo fica na maquina.

Pre-requisito: Ollama rodando e o modelo baixado (ollama pull qwen2.5:3b).
"""
import json
import urllib.request
from pathlib import Path

try:
    from settings import MODELO
except ImportError:
    MODELO = "qwen2.5:3b"

PASTA = Path(__file__).resolve().parent
ARQUIVO_NOTAS = PASTA / "anotacoes.md"
OLLAMA_URL = "http://localhost:11434/api/chat"

PERSONA = (
    "Voce e o Nextor, o assistente pessoal do Thiago. Voce fala por um alto-falante "
    "Google Nest no quarto dele e ajuda no dia a dia de advogado e de programador. "
    "Voce e prestativo, direto e com bom humor leve. Fale sempre em portugues do Brasil, "
    "de forma curta e natural, como quem vai ser ouvido em voz alta: no maximo duas ou tres "
    "frases, sem listas, sem emojis, sem markdown. Voce conhece as anotacoes do Thiago e pode "
    "usa-las para lembrar de coisas. Se nao souber algo, diga com simplicidade."
)


def ultimas_notas(n: int = 20) -> str:
    if not ARQUIVO_NOTAS.exists():
        return "(ainda nao ha anotacoes)"
    linhas = [l.strip() for l in ARQUIVO_NOTAS.read_text(encoding="utf-8").splitlines() if l.strip()]
    return "\n".join(linhas[-n:]) if linhas else "(ainda nao ha anotacoes)"


def _agenda_texto() -> str:
    try:
        from nextor_agenda import eventos_proximos, resumo_falado
        evs = eventos_proximos(7)
        if not evs:
            return "(sem compromissos nos proximos 7 dias ou agenda nao configurada)"
        return resumo_falado(evs, prefixo_dia=True)
    except Exception:
        return "(agenda indisponivel)"


def _chamar_ollama(mensagem: str, sistema: str = "", num_predict: int = 120) -> str:
    corpo = {
        "model": MODELO,
        "messages": [
            {"role": "system", "content": sistema or PERSONA},
            {"role": "user", "content": mensagem},
        ],
        "stream": False,
        "options": {"temperature": 0.7, "num_predict": num_predict},
    }
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(corpo).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        dados = json.loads(resp.read().decode("utf-8"))
    return (dados.get("message", {}).get("content") or "").strip()


def conversar(mensagem: str) -> str:
    try:
        from settings import NOME
    except ImportError:
        NOME = ""
    nome = f"O nome do usuario e {NOME}; trate-o por esse nome. " if NOME else ""
    contexto = (
        f"{PERSONA} {nome}\n\nAnotacoes recentes (memoria):\n{ultimas_notas()}"
        f"\n\nProximos compromissos da agenda:\n{_agenda_texto()}"
    )
    return _chamar_ollama(mensagem, sistema=contexto)


if __name__ == "__main__":
    import sys
    msg = " ".join(sys.argv[1:]) or "Oi Nextor, tudo bem?"
    print(conversar(msg))
