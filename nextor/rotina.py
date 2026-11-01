"""Rotina matinal do Nextor: bom dia + agenda de hoje + resumo das noticias."""
from . import config
from .voz import falar


def montar_texto() -> str:
    nome = f", {config.NOME}" if config.NOME else ""
    partes = [f"Bom dia{nome}."]

    try:
        from .agenda import eventos_hoje, resumo_falado
        partes.append("Sua agenda de hoje. " + resumo_falado(eventos_hoje()))
    except Exception:
        pass

    try:
        from .noticias import resumir
        assunto = config.ROTINA_ASSUNTO or config.NOTICIAS_ASSUNTO
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
