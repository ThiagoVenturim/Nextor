"""Extrator de conteudo estruturado para o NexRead mantendo o layout da pagina ou PDF (Issue #55)."""
import html
from html.parser import HTMLParser
from pathlib import Path
import re
from typing import Any, Callable, Dict, List, Optional, Tuple
import urllib.request

from .. import estudos
from .modelos import TAGS_BLOCO_PERMITIDAS, BlocoPagina

try:
    import trafilatura  # type: ignore
except ImportError:
    trafilatura = None

try:
    from readability import Document as ReadabilityDocument  # type: ignore
except ImportError:
    ReadabilityDocument = None

try:
    import pypdf
except ImportError:
    pypdf = None

TAGS_IGNORADAS = {"script", "style", "noscript", "iframe", "svg", "nav", "footer", "header"}
TAGS_BLOCO_CAPTURA = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "blockquote", "li", "pre", "figcaption"}


class _ParserLayoutHTML(HTMLParser):
    """Extrai blocos estruturais de HTML preservando a hierarquia de tags de leitura."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.titulo: str = ""
        self.autor: str = ""
        self.idioma: str = ""
        self.veiculo: str = ""
        self.blocos: List[BlocoPagina] = []

        self._pilha_ignorada: List[str] = []
        self._em_title: bool = False
        self._buffer_title: List[str] = []

        self._tag_bloco_atual: Optional[str] = None
        self._attrs_bloco_atual: Dict[str, str] = {}
        self._buffer_bloco: List[str] = []

    def _fechar_bloco_atual(self) -> None:
        if not self._tag_bloco_atual:
            return
        texto = "".join(self._buffer_bloco)
        if self._tag_bloco_atual != "pre":
            texto = re.sub(r"\s+", " ", texto).strip()
        else:
            texto = texto.strip("\r\n")
        if texto:
            indice = len(self.blocos) + 1
            self.blocos.append(
                BlocoPagina(
                    id=f"b-{indice}",
                    indice=indice,
                    tag=self._tag_bloco_atual,
                    texto_original=texto,
                    atributos=dict(self._attrs_bloco_atual),
                )
            )
        self._tag_bloco_atual = None
        self._attrs_bloco_atual = {}
        self._buffer_bloco = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        t = tag.lower()
        attrs_dict = {k.lower(): (v or "") for k, v in attrs if k}

        if t == "html" and not self.idioma:
            self.idioma = attrs_dict.get("lang", "").strip()

        if t == "meta":
            nome = (attrs_dict.get("name") or attrs_dict.get("property") or "").lower()
            conteudo = attrs_dict.get("content", "").strip()
            if conteudo:
                if nome in ("author", "article:author", "dc.creator") and not self.autor:
                    self.autor = conteudo
                elif nome in ("og:site_name", "application-name") and not self.veiculo:
                    self.veiculo = conteudo
                elif nome in ("og:title", "twitter:title") and not self.titulo:
                    self.titulo = conteudo

        if t in TAGS_IGNORADAS:
            self._pilha_ignorada.append(t)
            return

        if self._pilha_ignorada:
            return

        if t == "title":
            self._em_title = True
            self._buffer_title = []
            return

        if t in TAGS_BLOCO_CAPTURA:
            self._fechar_bloco_atual()
            self._tag_bloco_atual = t
            atributos_seguros = {}
            if "id" in attrs_dict and attrs_dict["id"]:
                atributos_seguros["id"] = attrs_dict["id"][:64]
            if "class" in attrs_dict and attrs_dict["class"]:
                atributos_seguros["class"] = attrs_dict["class"][:120]
            self._attrs_bloco_atual = atributos_seguros
        elif t == "br" and self._tag_bloco_atual:
            self._buffer_bloco.append("\n")

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if self._pilha_ignorada:
            if self._pilha_ignorada[-1] == t:
                self._pilha_ignorada.pop()
            elif t in self._pilha_ignorada:
                self._pilha_ignorada.remove(t)
            return

        if t == "title" and self._em_title:
            self._em_title = False
            tit = re.sub(r"\s+", " ", "".join(self._buffer_title)).strip()
            if tit:
                self.titulo = tit
            return

        if t == self._tag_bloco_atual:
            self._fechar_bloco_atual()

    def handle_data(self, data: str) -> None:
        if self._pilha_ignorada:
            return
        if self._em_title:
            self._buffer_title.append(data)
            return
        if self._tag_bloco_atual:
            self._buffer_bloco.append(data)


def validar_pagina_aberta_pelo_usuario(aberta_pelo_usuario: bool) -> None:
    """Garante a regra de privacidade: o NexRead so traduz a pagina que a pessoa abriu."""
    if not aberta_pelo_usuario:
        raise ValueError(
            "Operacao recusada: o NexRead traduz apenas a pagina ou documento que a pessoa abriu ativamente."
        )


def _isolar_html_artigo(conteudo_html: str) -> str:
    """Usa Readability ou Trafilatura se disponiveis para focar no corpo do artigo sem perder tags."""
    if ReadabilityDocument is not None:
        try:
            doc = ReadabilityDocument(conteudo_html)
            resumo_html = doc.summary()
            if resumo_html and len(resumo_html.strip()) > 40:
                return resumo_html
        except Exception:
            pass

    if trafilatura is not None:
        try:
            extraido_xml = trafilatura.extract(
                conteudo_html,
                output_format="html",
                include_formatting=True,
                include_links=False,
            )
            if extraido_xml and len(extraido_xml.strip()) > 40:
                return extraido_xml
        except Exception:
            pass

    return conteudo_html


def extrair_blocos_html(conteudo_html: str) -> Dict[str, Any]:
    """Extrai metadados e blocos de layout de um documento HTML."""
    html_texto = (conteudo_html or "").strip()
    if not html_texto:
        return {
            "titulo": "Pagina sem titulo",
            "autor": "",
            "veiculo": "",
            "idioma_origem": "auto",
            "blocos": [],
        }

    # Primeiro passa no HTML original para capturar <title> e <meta>
    parser_meta = _ParserLayoutHTML()
    try:
        parser_meta.feed(html_texto)
        parser_meta._fechar_bloco_atual()
    except Exception:
        pass

    # Tenta isolar o miolo de leitura se houver bibliotecas opcionais instaladas
    html_focado = _isolar_html_artigo(html_texto)
    if html_focado != html_texto:
        parser_corpo = _ParserLayoutHTML()
        try:
            parser_corpo.feed(html_focado)
            parser_corpo._fechar_bloco_atual()
        except Exception:
            parser_corpo.blocos = []
        blocos = parser_corpo.blocos or parser_meta.blocos
    else:
        blocos = parser_meta.blocos

    # Se o HTML nao tinha tags de bloco explicitas (ex: texto solto em div/body), divide em paragrafos
    if not blocos:
        _, texto_limpo = estudos.extrair_texto_html(html_texto)
        paragrafos = [p.strip() for p in re.split(r"\n+", texto_limpo) if p.strip()]
        for idx, p in enumerate(paragrafos, 1):
            blocos.append(BlocoPagina(id=f"b-{idx}", indice=idx, tag="p", texto_original=p))

    titulo = parser_meta.titulo
    if not titulo and blocos:
        primeiro_h1 = next((b.texto_original for b in blocos if b.tag in ("h1", "h2")), "")
        titulo = primeiro_h1 or blocos[0].texto_original[:80]

    return {
        "titulo": titulo or "Pagina sem titulo",
        "autor": parser_meta.autor,
        "veiculo": parser_meta.veiculo,
        "idioma_origem": parser_meta.idioma or "auto",
        "blocos": blocos,
    }


def extrair_blocos_texto(texto: str, titulo: str = "") -> Dict[str, Any]:
    """Converte texto puro ou Markdown em blocos preservando titulos, listas e paragrafos."""
    linhas = (texto or "").splitlines()
    blocos: List[BlocoPagina] = []
    paragrafo_atual: List[str] = []

    def descarregar_paragrafo() -> None:
        if not paragrafo_atual:
            return
        conteudo_p = " ".join(paragrafo_atual).strip()
        if conteudo_p:
            idx = len(blocos) + 1
            blocos.append(BlocoPagina(id=f"b-{idx}", indice=idx, tag="p", texto_original=conteudo_p))
        paragrafo_atual.clear()

    for linha in linhas:
        limpa = linha.strip()
        if not limpa:
            descarregar_paragrafo()
            continue

        m_head = re.match(r"^(#{1,6})\s+(.+)$", limpa)
        if m_head:
            descarregar_paragrafo()
            nivel = len(m_head.group(1))
            idx = len(blocos) + 1
            blocos.append(
                BlocoPagina(
                    id=f"b-{idx}",
                    indice=idx,
                    tag=f"h{nivel}",
                    texto_original=m_head.group(2).strip(),
                )
            )
            continue

        if limpa.startswith(("> ", ">>")):
            descarregar_paragrafo()
            idx = len(blocos) + 1
            blocos.append(
                BlocoPagina(
                    id=f"b-{idx}",
                    indice=idx,
                    tag="blockquote",
                    texto_original=limpa.lstrip("> ").strip(),
                )
            )
            continue

        if re.match(r"^([-*+]|\d+\.)\s+", limpa):
            descarregar_paragrafo()
            idx = len(blocos) + 1
            item_txt = re.sub(r"^([-*+]|\d+\.)\s+", "", limpa).strip()
            blocos.append(BlocoPagina(id=f"b-{idx}", indice=idx, tag="li", texto_original=item_txt))
            continue

        paragrafo_atual.append(limpa)

    descarregar_paragrafo()

    titulo_final = titulo.strip()
    if not titulo_final and blocos:
        primeiro_h = next((b.texto_original for b in blocos if b.tag.startswith("h")), "")
        titulo_final = primeiro_h or blocos[0].texto_original[:70]

    return {
        "titulo": titulo_final or "Artigo sem titulo",
        "autor": "",
        "veiculo": "",
        "idioma_origem": "auto",
        "blocos": blocos,
    }


def extrair_blocos_pdf(
    caminho_pdf: Path | str,
    titulo: str = "",
    pastas_autorizadas: Optional[List[Path]] = None,
) -> Dict[str, Any]:
    """Extrai blocos de leitura de um arquivo PDF preservando numeracao de pagina (skill de PDF)."""
    caminho_validado = estudos.validar_caminho_local(caminho_pdf, pastas_autorizadas=pastas_autorizadas)
    blocos: List[BlocoPagina] = []

    if pypdf is not None:
        try:
            reader = pypdf.PdfReader(str(caminho_validado))
            for num_pag, pagina in enumerate(reader.pages, 1):
                texto_pag = (pagina.extract_text() or "").strip()
                if not texto_pag:
                    continue
                paragrafos = [
                    re.sub(r"\s+", " ", p).strip()
                    for p in re.split(r"\n\s*\n|\r\n\s*\r\n", texto_pag)
                    if p.strip()
                ]
                if len(paragrafos) == 1 and "\n" in texto_pag:
                    paragrafos = [l.strip() for l in texto_pag.splitlines() if l.strip()]

                for i_p, p in enumerate(paragrafos):
                    idx = len(blocos) + 1
                    tag = "h1" if (num_pag == 1 and i_p == 0 and len(p) < 120) else "p"
                    blocos.append(
                        BlocoPagina(
                            id=f"b-{idx}",
                            indice=idx,
                            tag=tag,
                            texto_original=p,
                            pagina_pdf=num_pag,
                        )
                    )
        except Exception:
            blocos = []

    if not blocos:
        texto_fallback = estudos.extrair_texto_pdf(caminho_validado)
        extraido = extrair_blocos_texto(texto_fallback, titulo=titulo or caminho_validado.stem)
        blocos = extraido["blocos"]

    titulo_final = titulo.strip()
    if not titulo_final:
        if blocos and blocos[0].tag == "h1":
            titulo_final = blocos[0].texto_original
        else:
            titulo_final = caminho_validado.stem

    return {
        "titulo": titulo_final,
        "autor": "",
        "veiculo": "PDF Local",
        "idioma_origem": "auto",
        "tipo_origem": "pdf",
        "blocos": blocos,
    }


def extrair_pagina_aberta(
    conteudo_html: str = "",
    texto: str = "",
    url: str = "",
    caminho_pdf: Optional[Path | str] = None,
    titulo: str = "",
    aberta_pelo_usuario: bool = True,
    pastas_autorizadas: Optional[List[Path]] = None,
    http_fetcher: Optional[Callable[[str], str]] = None,
) -> Dict[str, Any]:
    """Extrai os blocos estruturados da pagina ou PDF que o usuario abriu."""
    validar_pagina_aberta_pelo_usuario(aberta_pelo_usuario)

    if caminho_pdf:
        res_pdf = extrair_blocos_pdf(caminho_pdf, titulo=titulo, pastas_autorizadas=pastas_autorizadas)
        res_pdf["url"] = str(caminho_pdf)
        return res_pdf

    if conteudo_html and conteudo_html.strip():
        res_html = extrair_blocos_html(conteudo_html)
        if titulo.strip():
            res_html["titulo"] = titulo.strip()
        res_html["url"] = url.strip()
        res_html["tipo_origem"] = "html"
        return res_html

    if texto and texto.strip():
        eh_html_provavel = bool(re.search(r"<(html|body|article|h1|h2|p|div|blockquote)\b", texto, re.IGNORECASE))
        if eh_html_provavel:
            res_h = extrair_blocos_html(texto)
            if titulo.strip():
                res_h["titulo"] = titulo.strip()
            res_h["url"] = url.strip()
            res_h["tipo_origem"] = "html"
            return res_h
        res_txt = extrair_blocos_texto(texto, titulo=titulo)
        res_txt["url"] = url.strip()
        res_txt["tipo_origem"] = "texto"
        return res_txt

    if url and url.strip():
        url_limpa = url.strip()
        estudos.validar_url_segura(url_limpa)
        if http_fetcher is not None:
            html_baixado = http_fetcher(url_limpa)
        else:
            req = urllib.request.Request(
                url_limpa,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Nextor-NexRead/1.0"},
            )
            with estudos.abrir_url_segura(req, timeout=10.0) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                raw_bytes = resp.read(estudos.LIMITE_DOWNLOAD_BYTES)
                html_baixado = raw_bytes.decode(charset, errors="replace")

        res_url = extrair_blocos_html(html_baixado)
        if titulo.strip():
            res_url["titulo"] = titulo.strip()
        res_url["url"] = url_limpa
        res_url["tipo_origem"] = "html"
        return res_url

    raise ValueError("Nenhum conteudo (HTML, texto, PDF ou URL da pagina aberta) foi informado.")
