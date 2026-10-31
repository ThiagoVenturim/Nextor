"""
Cerebro via agy / Maestri: encaminha a pergunta para um agente da canvas do Maestri
(ex.: "Claude Code") pela CLI 'maestri ask' e usa a resposta dele.

Experimental: depende do agente estar conectado e pode demorar. Use NEXTOR_CEREBRO=agy
e NEXTOR_AGY_AGENTE para escolher o agente.
"""
import subprocess

from . import config


def responder(mensagem: str, sistema: str = "", timeout: int = 90) -> str:
    pergunta = (f"{sistema}\n\n{mensagem}" if sistema else mensagem).strip()
    proc = subprocess.run(
        ["maestri", "ask", config.AGY_AGENTE, pergunta],
        capture_output=True, text=True, timeout=timeout,
    )
    saida = (proc.stdout or "").strip()
    if proc.returncode != 0 or not saida:
        raise RuntimeError((proc.stderr or "sem resposta do agy").strip())
    return saida
