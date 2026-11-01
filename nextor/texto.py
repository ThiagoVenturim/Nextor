"""
Skill de texto do Nextor: traduzir, resumir e escrever.

Usa o cerebro escolhido (local/Claude/agy). O texto completo e salvo em arquivo
(para ler no celular, ex.: numa pasta do Obsidian) e o Nest fala um aviso curto.
Pasta de saida: NEXTOR_TEXTOS_DIR no .env, ou a pasta textos/ do projeto.
"""
import re
from datetime import datetime
from pathlib import Path

from . import config
from .cerebro import responder


def _pasta() -> Path:
    destino = Path(config.TEXTOS_DIR) if config.TEXTOS_DIR else (config.RAIZ / "textos")
    destino.mkdir(parents=True, exist_ok=True)
    return destino


def _salvar(titulo: str, conteudo: str) -> Path:
    base = re.sub(r"[^a-z0-9]+", "-", titulo.lower()).strip("-")[:50] or "texto"
    carimbo = datetime.now().strftime("%Y%m%d-%H%M")
    caminho = _pasta() / f"{carimbo}-{base}.md"
    caminho.write_text(f"# {titulo}\n\n{conteudo}\n", encoding="utf-8")
    return caminho


def _preview(conteudo: str, frases: int = 2) -> str:
    partes = re.split(r"(?<=[.!?])\s+", conteudo.strip())
    return " ".join(partes[:frases])


def traduzir(texto: str, idioma: str = "ingles") -> dict:
    sistema = f"Voce traduz textos para {idioma} com fidelidade e naturalidade. Responda so com a traducao."
    traducao = responder(texto, sistema=sistema, tokens=1500)
    caminho = _salvar(f"traducao para {idioma}", traducao)
    return {"texto": traducao, "arquivo": str(caminho),
            "aviso": f"Traduzi para {idioma} e salvei o texto. Comeca assim: {_preview(traducao)}"}


def resumir_texto(texto: str) -> dict:
    sistema = "Voce resume textos em portugues do Brasil, claro e fiel, mantendo os pontos principais."
    resumo = responder(texto, sistema=sistema, tokens=800)
    caminho = _salvar("resumo", resumo)
    return {"texto": resumo, "arquivo": str(caminho),
            "aviso": f"Resumi e salvei. Em resumo: {_preview(resumo, 3)}"}


def escrever(pedido: str) -> dict:
    sistema = ("Voce escreve bem em portugues do Brasil (historias, textos, cartas) conforme o pedido. "
               "Escreva o texto completo, com um titulo na primeira linha.")
    conteudo = responder(pedido, sistema=sistema, tokens=1800)
    primeira = conteudo.strip().splitlines()[0] if conteudo.strip() else "texto"
    titulo = primeira.lstrip("# ").strip()[:60] or "texto"
    caminho = _salvar(titulo, conteudo)
    return {"texto": conteudo, "arquivo": str(caminho),
            "aviso": f"Escrevi e salvei em {caminho.name}. Comeca assim: {_preview(conteudo)}"}


if __name__ == "__main__":
    import sys
    print(escrever(" ".join(sys.argv[1:]) or "uma historia curta sobre um robo gentil")["aviso"])
