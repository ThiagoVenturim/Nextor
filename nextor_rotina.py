"""
Nextor - rotina matinal ("bom dia").

Fala uma saudacao, a agenda de hoje e um resumo das noticias do assunto escolhido.
Pensado para rodar sozinho todo dia em horario fixo (ver agendar_rotina.ps1).

Rodar manualmente:
    .venv/Scripts/python.exe nextor_rotina.py
"""
from nextor import falar

try:
    from settings import NOME, ROTINA_ASSUNTO, NOTICIAS_ASSUNTO
except ImportError:
    NOME, ROTINA_ASSUNTO, NOTICIAS_ASSUNTO = "", "", "inteligencia artificial generativa"


def montar_texto() -> str:
    nome = f", {NOME}" if NOME else ""
    partes = [f"Bom dia{nome}."]

    try:
        from nextor_agenda import eventos_hoje, resumo_falado
        partes.append("Sua agenda de hoje. " + resumo_falado(eventos_hoje()))
    except Exception:
        pass

    try:
        from nextor_noticias import resumir
        assunto = ROTINA_ASSUNTO or NOTICIAS_ASSUNTO
        partes.append(f"Noticias sobre {assunto}. " + resumir(assunto))
    except Exception:
        pass

    return " ".join(partes)


def bom_dia() -> str:
    texto = montar_texto()
    falar(texto)
    return texto


if __name__ == "__main__":
    print(bom_dia())
