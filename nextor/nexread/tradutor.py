"""Tradutor de artigo/pagina ao vivo para o NexRead, preferindo modelo local e preservando layout (Issue #55)."""
import html
import json
from pathlib import Path
import re
from typing import Any, Callable, Dict, List, Optional
import urllib.request

from .. import config
from .armazenamento import ArmazenamentoNexRead
from .extrator import extrair_pagina_aberta, validar_pagina_aberta_pelo_usuario
from .modelos import MODOS_LAYOUT, ArtigoLido, BlocoPagina, Marcacao

MOTORES_SUPORTADOS = ("local", "libretranslate", "nllb", "opus_mt", "faccoder", "claude")

# Glossario local leve para fallback deterministico offline quando nenhum servidor externo estiver rodando
_GLOSSARIO_FALLBACK_PT: Dict[str, str] = {
    "abstract": "resumo",
    "introduction": "introducao",
    "conclusion": "conclusao",
    "methods": "metodos",
    "results": "resultados",
    "discussion": "discussao",
    "references": "referencias",
    "machine learning": "aprendizado de maquina",
    "deep learning": "aprendizado profundo",
    "artificial intelligence": "inteligencia artificial",
    "neural networks": "redes neurais",
    "neural network": "rede neural",
    "natural language processing": "processamento de linguagem natural",
    "large language models": "grandes modelos de linguagem",
    "attention mechanism": "mecanismo de atencao",
    "study": "estudo",
    "paper": "artigo",
    "research": "pesquisa",
    "data": "dados",
    "model": "modelo",
    "training": "treinamento",
    "performance": "desempenho",
}


def _traduzir_fallback_offline(texto: str, idioma_destino: str = "pt-BR") -> str:
    """Fallback deterministico offline para ambientes sem Ollama/LibreTranslate ativo."""
    limpo = (texto or "").strip()
    if not limpo:
        return ""
    destino_norm = (idioma_destino or "pt-BR").lower()
    if destino_norm.startswith("pt"):
        traduzido = limpo
        for termo_en, termo_pt in _GLOSSARIO_FALLBACK_PT.items():
            padrao = re.compile(rf"\b{re.escape(termo_en)}\b", flags=re.IGNORECASE)

            def _substituir(m: re.Match, alvo: str = termo_pt) -> str:
                orig = m.group(0)
                if orig.isupper():
                    return alvo.upper()
                if orig[0].isupper():
                    return alvo.capitalize()
                return alvo

            traduzido = padrao.sub(_substituir, traduzido)
        if traduzido == limpo:
            return f"[PT-BR] {limpo}"
        return traduzido
    return f"[{idioma_destino}] {limpo}"


def _traduzir_via_libretranslate(
    texto: str,
    idioma_origem: str = "auto",
    idioma_destino: str = "pt",
    url_api: Optional[str] = None,
) -> str:
    endpoint = url_api or getattr(config, "LIBRETRANSLATE_URL", "http://localhost:5000/translate")
    alvo = "pt" if idioma_destino.lower().startswith("pt") else idioma_destino.split("-")[0].lower()
    origem = "auto" if not idioma_origem or idioma_origem == "auto" else idioma_origem.split("-")[0].lower()
    payload = json.dumps({
        "q": texto,
        "source": origem,
        "target": alvo,
        "format": "text",
    }).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        dados = json.loads(resp.read().decode("utf-8"))
    return (dados.get("translatedText") or "").strip()


def _traduzir_via_huggingface_local(
    texto: str,
    motor: str = "nllb",
    idioma_destino: str = "pt-BR",
) -> str:
    """Usa pipeline local HuggingFace (NLLB-200 ou Opus-MT Helsinki-NLP) se instalado."""
    from transformers import pipeline  # type: ignore
    if motor == "opus_mt":
        modelo_hf = "Helsinki-NLP/opus-mt-tc-big-en-pt"
        pipe = pipeline("translation", model=modelo_hf)
        res = pipe(texto)
    else:
        modelo_hf = "facebook/nllb-200-distilled-600M"
        tgt_lang = "por_Latn" if idioma_destino.lower().startswith("pt") else "eng_Latn"
        pipe = pipeline("translation", model=modelo_hf, src_lang="eng_Latn", tgt_lang=tgt_lang)
        res = pipe(texto)
    if isinstance(res, list) and res and isinstance(res[0], dict):
        return (res[0].get("translation_text") or "").strip()
    return ""


def _traduzir_via_faccoder(texto: str, idioma_destino: str = "pt-BR") -> str:
    """Usa LLM via faccoder-core (tier small) se o pacote estiver instalado no ambiente."""
    from faccoder_core import get_chat_model  # type: ignore
    modelo = get_chat_model("small")
    prompt = (
        f"Traduza fielmente o trecho abaixo para {idioma_destino} mantendo o tom academico/tecnico. "
        f"Responda apenas com a traducao:\n\n{texto}"
    )
    if hasattr(modelo, "invoke"):
        resp = modelo.invoke(prompt)
        return (getattr(resp, "content", None) or str(resp)).strip()
    if callable(modelo):
        return str(modelo(prompt)).strip()
    return ""


def traduzir_texto_bloco(
    texto: str,
    idioma_destino: str = "pt-BR",
    idioma_origem: str = "auto",
    motor: Optional[str] = None,
    tradutor_fn: Optional[Callable[[str, str], str]] = None,
) -> str:
    """Traduz um bloco de texto preferindo modelo local."""
    limpo = (texto or "").strip()
    if not limpo:
        return ""

    if tradutor_fn is not None:
        try:
            res_custom = tradutor_fn(limpo, idioma_destino)
            if res_custom and res_custom.strip():
                return res_custom.strip()
        except Exception:
            pass

    motor_escolhido = (motor or getattr(config, "NEXREAD_TRADUTOR", "local") or "local").strip().lower()
    sistema = (
        f"Voce e o tradutor academico NexRead. Traduza o texto do usuario para {idioma_destino} "
        "com precisao e naturalidade, sem adicionar comentarios extras. Responda apenas com a traducao."
    )

    # 1. LibreTranslate self-hosted local
    if motor_escolhido == "libretranslate":
        try:
            res_lt = _traduzir_via_libretranslate(limpo, idioma_origem=idioma_origem, idioma_destino=idioma_destino)
            if res_lt:
                return res_lt
        except Exception:
            pass

    # 2. NLLB-200 ou Opus-MT local
    if motor_escolhido in ("nllb", "opus_mt"):
        try:
            res_hf = _traduzir_via_huggingface_local(limpo, motor=motor_escolhido, idioma_destino=idioma_destino)
            if res_hf:
                return res_hf
        except Exception:
            pass

    # 3. faccoder-core
    if motor_escolhido == "faccoder":
        try:
            res_fc = _traduzir_via_faccoder(limpo, idioma_destino=idioma_destino)
            if res_fc:
                return res_fc
        except Exception:
            pass

    # 4. Claude (apenas se explicitamente pedido, caindo para local se falhar)
    if motor_escolhido == "claude":
        try:
            from .. import claude_cerebro
            res_cl = claude_cerebro.responder(limpo, sistema=sistema, max_tokens=800)
            if res_cl:
                return res_cl.strip()
        except Exception:
            pass

    # 5. Padrao: Modelo local (Ollama via cerebro)
    try:
        from .. import cerebro
        res_local = cerebro._chamar_ollama(limpo, sistema=sistema, num_predict=600)
        if res_local:
            return res_local.strip()
    except Exception:
        pass

    # 6. Fallback deterministico offline
    return _traduzir_fallback_offline(limpo, idioma_destino=idioma_destino)


def _aplicar_marcacoes_no_texto(texto_escapado: str, bloco_id: str, marcacoes: List[Marcacao]) -> str:
    """Envolve trechos destacados pelo estudante com tags <mark> seguras."""
    resultado = texto_escapado
    for m in marcacoes:
        if m.bloco_id and m.bloco_id != bloco_id:
            continue
        for trecho in (m.trecho_traduzido, m.trecho_original):
            if not trecho or len(trecho.strip()) < 2:
                continue
            alvo_esc = html.escape(trecho.strip())
            if alvo_esc in resultado:
                nota_attr = f' title="{html.escape(m.nota)}"' if m.nota else ""
                tag_mark = (
                    f'<mark class="nexread-mark cor-{html.escape(m.cor)}" '
                    f'data-marcacao-id="{html.escape(m.id)}"{nota_attr}>{alvo_esc}</mark>'
                )
                resultado = resultado.replace(alvo_esc, tag_mark, 1)
                break
    return resultado


def reconstruir_html_layout(
    blocos: List[BlocoPagina],
    modo_layout: str = "bilingue",
    marcacoes: Optional[List[Marcacao]] = None,
) -> str:
    """Reconstroi o HTML do artigo mantendo o layout estrutural das tags e aplicando marcacoes."""
    modo = modo_layout if modo_layout in MODOS_LAYOUT else "bilingue"
    lista_marcacoes = marcacoes or []
    partes: List[str] = [f'<article class="nexread-artigo modo-{modo}">']

    for b in blocos:
        tag = b.tag
        orig_esc = html.escape(b.texto_original)
        trad_esc = html.escape(b.texto_traduzido or b.texto_original)

        orig_marcado = _aplicar_marcacoes_no_texto(orig_esc, b.id, lista_marcacoes)
        trad_marcado = _aplicar_marcacoes_no_texto(trad_esc, b.id, lista_marcacoes)

        pag_badge = f' data-pagina-pdf="{b.pagina_pdf}"' if b.pagina_pdf else ""
        bloco_attrs = f'data-nexread-bloco="{html.escape(b.id)}" data-indice="{b.indice}"{pag_badge}'

        if modo == "substituir":
            partes.append(f'<{tag} class="nexread-bloco" {bloco_attrs}>{trad_marcado}</{tag}>')
        elif modo == "lado_a_lado":
            partes.append(
                f'<div class="nexread-linha-paralela" {bloco_attrs}>'
                f'<{tag} class="nexread-col-original" lang="auto">{orig_marcado}</{tag}>'
                f'<{tag} class="nexread-col-traduzido">{trad_marcado}</{tag}>'
                f'</div>'
            )
        else:
            # bilingue: mantem a tag semantica com original e traducao empilhados
            partes.append(
                f'<{tag} class="nexread-bloco nexread-bilingue" {bloco_attrs}>'
                f'<span class="nexread-texto-traduzido">{trad_marcado}</span>'
                f'<span class="nexread-texto-original">{orig_marcado}</span>'
                f'</{tag}>'
            )

    partes.append("</article>")
    return "\n".join(partes)


def traduzir_pagina_ao_vivo(
    conteudo_html: str = "",
    texto: str = "",
    url: str = "",
    caminho_pdf: Optional[Path | str] = None,
    titulo: str = "",
    autor: str = "",
    idioma_destino: Optional[str] = None,
    idioma_origem: str = "auto",
    motor: Optional[str] = None,
    modo_layout: str = "bilingue",
    disciplina: str = "",
    aberta_pelo_usuario: bool = True,
    pastas_autorizadas: Optional[List[Path]] = None,
    tradutor_fn: Optional[Callable[[str, str], str]] = None,
    http_fetcher: Optional[Callable[[str], str]] = None,
    db: Optional[ArmazenamentoNexRead] = None,
) -> ArtigoLido:
    """Extrai e traduz ao vivo a pagina ou PDF aberto pelo usuario, salvando a sessao no NexRead."""
    validar_pagina_aberta_pelo_usuario(aberta_pelo_usuario)

    destino = (idioma_destino or getattr(config, "NEXREAD_IDIOMA_PADRAO", "pt-BR") or "pt-BR").strip()
    motor_final = (motor or getattr(config, "NEXREAD_TRADUTOR", "local") or "local").strip().lower()
    if motor_final not in MOTORES_SUPORTADOS:
        motor_final = "local"

    extraido = extrair_pagina_aberta(
        conteudo_html=conteudo_html,
        texto=texto,
        url=url,
        caminho_pdf=caminho_pdf,
        titulo=titulo,
        aberta_pelo_usuario=aberta_pelo_usuario,
        pastas_autorizadas=pastas_autorizadas,
        http_fetcher=http_fetcher,
    )

    blocos: List[BlocoPagina] = extraido.get("blocos") or []
    origem_detectada = idioma_origem if idioma_origem != "auto" else (extraido.get("idioma_origem") or "auto")

    for bloco in blocos:
        if bloco.tag == "code":
            bloco.texto_traduzido = bloco.texto_original
        else:
            bloco.texto_traduzido = traduzir_texto_bloco(
                bloco.texto_original,
                idioma_destino=destino,
                idioma_origem=origem_detectada,
                motor=motor_final,
                tradutor_fn=tradutor_fn,
            )

    titulo_orig = extraido.get("titulo") or titulo or "Artigo sem titulo"
    titulo_trad = traduzir_texto_bloco(
        titulo_orig,
        idioma_destino=destino,
        idioma_origem=origem_detectada,
        motor=motor_final,
        tradutor_fn=tradutor_fn,
    )

    html_renderizado = reconstruir_html_layout(blocos, modo_layout=modo_layout)

    artigo = ArtigoLido(
        titulo=titulo_orig,
        url=extraido.get("url") or url,
        titulo_traduzido=titulo_trad or titulo_orig,
        autor=autor.strip() or extraido.get("autor", ""),
        veiculo=extraido.get("veiculo", ""),
        idioma_origem=origem_detectada,
        idioma_destino=destino,
        motor_traducao=motor_final,
        modo_layout=modo_layout if modo_layout in MODOS_LAYOUT else "bilingue",
        tipo_origem=extraido.get("tipo_origem", "html"),
        blocos=blocos,
        html_traduzido=html_renderizado,
        disciplina=disciplina.strip(),
        aberta_pelo_usuario=True,
    )

    banco = db or ArmazenamentoNexRead()
    return banco.salvar_artigo(artigo)
