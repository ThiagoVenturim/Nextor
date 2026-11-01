"""
Cerebro na nuvem: usa a API do Claude (Anthropic) para respostas melhores que o
modelo local. Opcional: so e usado se NEXTOR_CEREBRO=claude e houver chave de API.

Chave: defina ANTHROPIC_API_KEY no .env (a SDK le do ambiente). Nada de chave no git.
Modelo padrao: claude-haiku-5-5 (o mais barato; bom para respostas curtas faladas).
Troque em NEXTOR_CLAUDE_MODELO (ex.: claude-sonnet-5-5, claude-opus-5-5).
"""
from . import config

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

_cliente = None


def _get():
    global _cliente
    if Anthropic is None:
        raise RuntimeError("Falta a biblioteca anthropic (pip install anthropic).")
    if _cliente is None:
        _cliente = Anthropic()  # le ANTHROPIC_API_KEY do ambiente
    return _cliente


def responder(mensagem: str, sistema: str = "", max_tokens: int = 400) -> str:
    msg = _get().messages.create(
        model=config.CLAUDE_MODELO,
        max_tokens=max_tokens,
        system=sistema or "Voce e um assistente util. Responda em portugues do Brasil.",
        messages=[{"role": "user", "content": mensagem}],
    )
    return "".join(
        b.text for b in msg.content if getattr(b, "type", None) == "text"
    ).strip()
