"""Entende como a pessoa chama o assistente: "ei Nextor", "fala Nextor", "meu bom Nextor",
"meu amigo Nextor", "ola Claude", "ei agy"... inclusive com erros de digitacao ou de
reconhecimento de voz ("nexto", "enxtor", "nestor").

entender("Ei, meu amigo nexto, modo estudo")
    -> {"chamado": True, "nome": "nextor", "comando": "modo estudo"}
"""
import difflib
import re
import unicodedata

# Nome que a pessoa usa -> identidade do assistente.
NOMES = {
    "nextor": "nextor", "nexto": "nextor", "nextr": "nextor", "enxtor": "nextor", "nestor": "nextor",
    "nector": "nextor", "nectar": "nextor", "nexter": "nextor", "nexdor": "nextor", "nexor": "nextor",
    "claude": "claude", "claudio": "claude", "clode": "claude", "cloud": "claude",
    "agy": "agy", "agi": "agy", "antigravity": "agy", "ajy": "agy",
}
# Palavras que podem vir antes do nome e nao fazem parte do comando.
SAUDACOES = {"ei", "hey", "oi", "ola", "opa", "fala", "e", "ai", "alo", "bom", "boa", "dia", "tarde", "noite",
             "meu", "minha", "querido", "caro", "amigo", "amigao", "parceiro"}
SIMILARIDADE_MINIMA = 0.75


def _normaliza(texto: str) -> str:
    sem_acento = "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
    return sem_acento.lower()


def _qual_nome(palavra: str) -> str | None:
    if palavra in NOMES:
        return NOMES[palavra]
    if len(palavra) < 5:
        return None
    melhor = difflib.get_close_matches(palavra, [n for n in NOMES if len(n) >= 5], n=1, cutoff=SIMILARIDADE_MINIMA)
    return NOMES[melhor[0]] if melhor else None


def entender(frase: str) -> dict:
    """Procura o nome do assistente no comeco da frase (depois de saudacoes) e separa o comando."""
    original = frase.strip()
    tokens = list(re.finditer(r"[a-z0-9]+", _normaliza(original)))
    for i, tok in enumerate(tokens[:6]):
        palavra = tok.group(0)
        nome = _qual_nome(palavra)
        if nome:
            antes = [t.group(0) for t in tokens[:i]]
            if all(p in SAUDACOES for p in antes):
                resto = original[tok.end():].lstrip(" ,.:;!?-")
                return {"chamado": True, "nome": nome, "comando": resto}
            break
        if palavra not in SAUDACOES:
            break
    return {"chamado": False, "nome": None, "comando": original}
