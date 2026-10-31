"""
Nextor - roteador de intencoes.

Recebe uma frase livre (ex.: "ei Nextor, anota comprar pao" ou "o que tenho amanha")
e decide o que o usuario quer: anotar, ver agenda, ouvir noticias ou conversar.
Primeiro por regras simples; se ficar em duvida, pergunta ao proprio modelo.

Retorna um dict: {"intencao": ..., "resposta": <texto para falar>}.
"""
import re
import unicodedata
from datetime import datetime
from pathlib import Path

PASTA = Path(__file__).resolve().parent
LOG = PASTA / "comandos.log"

# Saudacoes + nome que podem vir antes do comando (sao removidas).
PREFIXOS = r"^(ei|ola|oi|opa|fala|bom dia|boa tarde|boa noite|e ai)?[, ]*(nextor|nestor)?[,: ]*"

PALAVRAS_AGENDA = ("agenda", "compromisso", "reuniao", "audiencia", "prazo", "calendario")
PALAVRAS_NOTICIA = ("noticia", "noticias", "novidade", "novidades", "manchete", "manchetes")
PALAVRAS_ANOTAR = ("anota", "anotar", "anote", "lembra", "lembrar", "lembrete", "escreve", "escrever")


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower()


def _limpa(frase: str) -> str:
    return re.sub(PREFIXOS, "", frase.strip(), flags=re.IGNORECASE).strip()


def _registra(frase: str, intencao: str) -> None:
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')}\t{intencao}\t{frase}\n")
    except Exception:
        pass


def rotear(frase: str) -> dict:
    limpa = _limpa(frase)
    base = _sem_acento(limpa)

    # Anotar: pega o texto depois da palavra-gatilho.
    for p in PALAVRAS_ANOTAR:
        if base.startswith(p) or f" {p} " in f" {base} ":
            texto = re.sub(rf".*\b{p}\b( que| o que| para)?", "", limpa, count=1, flags=re.IGNORECASE).strip(" ,:")
            intencao = "anotar"
            resposta = _fazer_anotar(texto or limpa)
            _registra(frase, intencao)
            return {"intencao": intencao, "resposta": resposta}

    if any(w in base for w in PALAVRAS_NOTICIA):
        assunto = ""
        m = re.search(r"sobre (.+)$", limpa, flags=re.IGNORECASE)
        if m:
            assunto = m.group(1).strip(" ?.")
        _registra(frase, "noticias")
        return {"intencao": "noticias", "resposta": _fazer_noticias(assunto)}

    if any(w in base for w in PALAVRAS_AGENDA) or "o que tenho" in base or "o que eu tenho" in base:
        quando = "proximos" if any(k in base for k in ("amanha", "semana", "proxim")) else "hoje"
        _registra(frase, "agenda")
        return {"intencao": "agenda", "resposta": _fazer_agenda(quando)}

    _registra(frase, "conversar")
    return {"intencao": "conversar", "resposta": _fazer_conversar(limpa or frase)}


# --- acoes (importes tardios para o modulo carregar mesmo sem dependencias) ---

def _fazer_anotar(texto: str) -> str:
    carimbo = datetime.now().strftime("%Y-%m-%d %H:%M")
    (PASTA / "anotacoes.md").open("a", encoding="utf-8").write(f"- [{carimbo}] {texto}\n")
    return f"Anotei: {texto}"


def _fazer_agenda(quando: str) -> str:
    try:
        from nextor_agenda import eventos_hoje, eventos_proximos, resumo_falado
        if quando == "proximos":
            return resumo_falado(eventos_proximos(7), prefixo_dia=True)
        return "Hoje: " + resumo_falado(eventos_hoje())
    except Exception:
        return "Nao consegui ler a agenda agora."


def _fazer_noticias(assunto: str) -> str:
    try:
        from nextor_noticias import resumir
        return resumir(assunto)
    except Exception:
        return "Nao consegui buscar as noticias agora."


def _fazer_conversar(frase: str) -> str:
    try:
        from nextor_brain import conversar
        return conversar(frase)
    except Exception:
        return "Estou aqui, mas meu cerebro esta fora do ar agora."


if __name__ == "__main__":
    import sys
    frase = " ".join(sys.argv[1:]) or "ei Nextor, o que tenho amanha?"
    r = rotear(frase)
    print(f"[{r['intencao']}] {r['resposta']}")
