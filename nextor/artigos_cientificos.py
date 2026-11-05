"""Modulo de busca de artigos cientificos (OpenAlex e arXiv) com referencias ABNT (Issue #7)."""
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import config, estudos

MESES_ABNT = {
    1: "jan.", 2: "fev.", 3: "mar.", 4: "abr.", 5: "mai.", 6: "jun.",
    7: "jul.", 8: "ago.", 9: "set.", 10: "out.", 11: "nov.", 12: "dez."
}

SUFIXOS_SOBRENOME = {"filho", "junior", "júnior", "neto", "sobrinho"}


def formatar_autor_abnt(nome: str) -> str:
    """Formata um nome de autor no padrao ABNT NBR 6023 (ex: 'Albert Einstein' -> 'EINSTEIN, Albert')."""
    partes = [p.strip() for p in nome.strip().split() if p.strip()]
    if not partes:
        return ""
    if len(partes) == 1:
        return partes[0].upper()

    ultimo = partes[-1]
    if len(partes) >= 3 and ultimo.lower() in SUFIXOS_SOBRENOME:
        sobrenome = f"{partes[-2]} {ultimo}".upper()
        prenomes = " ".join(partes[:-2])
        return f"{sobrenome}, {prenomes}"

    sobrenome = ultimo.upper()
    prenomes = " ".join(partes[:-1])
    return f"{sobrenome}, {prenomes}"


def formatar_referencia_abnt(
    autores: List[str],
    titulo: str,
    veiculo_ou_periodico: str,
    ano: int | str,
    url: str = "",
    data_acesso: Optional[datetime] = None,
) -> str:
    """Gera referencia bibliografica formatada em ABNT NBR 6023."""
    autores_formatados = [formatar_autor_abnt(a) for a in autores if a.strip()]
    if not autores_formatados:
        bloco_autores = "AUTOR DESCONHECIDO."
    elif len(autores_formatados) == 1:
        bloco_autores = f"{autores_formatados[0]}."
    elif len(autores_formatados) in (2, 3):
        bloco_autores = f"{'; '.join(autores_formatados)}."
    else:
        bloco_autores = f"{autores_formatados[0]} et al."

    titulo_limpo = titulo.strip().rstrip(".")
    veiculo = veiculo_ou_periodico.strip().rstrip(",") or "Repositorio Cientifico"
    ano_str = str(ano).strip()

    ref = f"{bloco_autores} {titulo_limpo}. {veiculo}, {ano_str}."
    if url.strip():
        dt = data_acesso or datetime.now()
        mes_abnt = MESES_ABNT.get(dt.month, f"{dt.month:02d}.")
        ref += f" Disponivel em: <{url.strip()}>. Acesso em: {dt.day} {mes_abnt} {dt.year}."

    return ref


def reconstruir_abstract_openalex(abstract_inverted_index: Optional[Dict[str, List[int]]]) -> str:
    """Reconstroi o texto corrido do resumo a partir do indice invertido fornecido pelo OpenAlex."""
    if not abstract_inverted_index or not isinstance(abstract_inverted_index, dict):
        return ""
    posicoes = []
    for palavra, pos_list in abstract_inverted_index.items():
        for pos in pos_list:
            posicoes.append((pos, palavra))
    posicoes.sort(key=lambda x: x[0])
    return " ".join(p[1] for p in posicoes)


def _executar_requisicao(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    http_client: Optional[Callable[[str, Dict[str, str]], str]] = None,
) -> str:
    """Executa a requisicao HTTP utilizando urllib ou mock injetado nos testes unitarios."""
    cabecalhos = headers or {"User-Agent": "Nextor-Estudos/1.0 (assistente academico)"}
    if http_client is not None:
        return http_client(url, cabecalhos)

    req = urllib.request.Request(url, headers=cabecalhos)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8")


def buscar_openalex(
    termo: str,
    limite: int = 5,
    url_api: Optional[str] = None,
    http_client: Optional[Callable[[str, Dict[str, str]], str]] = None,
) -> List[Dict[str, Any]]:
    """Busca artigos na API publica do OpenAlex."""
    termo_limpo = termo.strip()
    if not termo_limpo:
        return []

    base_url = url_api or getattr(config, "OPENALEX_API_URL", "https://api.openalex.org/works")
    params = urllib.parse.urlencode({"search": termo_limpo, "per-page": limite})
    url = f"{base_url}?{params}"

    try:
        dados_raw = _executar_requisicao(
            url,
            headers={"User-Agent": "Nextor-Estudos/1.0 (mailto:estudos@nextor.local)"},
            http_client=http_client,
        )
        dados = json.loads(dados_raw)
    except Exception:
        return []

    resultados = []
    works = dados.get("results") or []
    for w in works[:limite]:
        if not isinstance(w, dict):
            continue
        titulo = (w.get("title") or "").strip()
        if not titulo:
            continue

        ano = w.get("publication_year") or datetime.now().year
        autores = []
        for authorship in w.get("authorships") or []:
            nome_autor = authorship.get("author", {}).get("display_name")
            if nome_autor:
                autores.append(nome_autor)

        resumo = reconstruir_abstract_openalex(w.get("abstract_inverted_index"))
        if not resumo:
            resumo = "Resumo nao disponibilizado pelo repositorio."

        # Identifica fontes, links e PDF aberto
        primary = w.get("primary_location") or {}
        source = primary.get("source") or {}
        veiculo = source.get("display_name") or "OpenAlex"

        landing_url = w.get("doi") or primary.get("landing_page_url") or w.get("id") or ""
        pdf_url = (w.get("open_access") or {}).get("oa_url") or primary.get("pdf_url") or ""

        ref_abnt = formatar_referencia_abnt(
            autores=autores,
            titulo=titulo,
            veiculo_ou_periodico=veiculo,
            ano=ano,
            url=landing_url,
        )

        resultados.append({
            "id": w.get("id") or landing_url,
            "fonte_api": "OpenAlex",
            "titulo": titulo,
            "autores": autores,
            "ano": ano,
            "resumo": resumo,
            "veiculo": veiculo,
            "url": landing_url,
            "pdf_url": pdf_url,
            "referencia_abnt": ref_abnt,
        })

    return resultados


def buscar_arxiv(
    termo: str,
    limite: int = 5,
    url_api: Optional[str] = None,
    http_client: Optional[Callable[[str, Dict[str, str]], str]] = None,
) -> List[Dict[str, Any]]:
    """Busca preprints e artigos na API publica do arXiv (Atom Feed)."""
    termo_limpo = termo.strip()
    if not termo_limpo:
        return []

    base_url = url_api or getattr(config, "ARXIV_API_URL", "http://export.arxiv.org/api/query")
    query_str = f"all:{termo_limpo}"
    params = urllib.parse.urlencode({"search_query": query_str, "max_results": limite, "sortBy": "relevance"})
    url = f"{base_url}?{params}"

    try:
        dados_raw = _executar_requisicao(url, http_client=http_client)
        root = ET.fromstring(dados_raw)
    except Exception:
        return []

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    resultados = []

    for entry in root.findall("atom:entry", ns)[:limite]:
        tit_elem = entry.find("atom:title", ns)
        if tit_elem is None or not tit_elem.text:
            continue
        titulo = re.sub(r"\s+", " ", tit_elem.text).strip()

        id_elem = entry.find("atom:id", ns)
        artigo_id = id_elem.text.strip() if id_elem is not None and id_elem.text else ""

        sum_elem = entry.find("atom:summary", ns)
        resumo = re.sub(r"\s+", " ", sum_elem.text).strip() if sum_elem is not None and sum_elem.text else "Resumo nao disponibilizado."

        pub_elem = entry.find("atom:published", ns)
        ano = int(pub_elem.text[:4]) if pub_elem is not None and pub_elem.text and len(pub_elem.text) >= 4 else datetime.now().year

        autores = []
        for author in entry.findall("atom:author", ns):
            name_elem = author.find("atom:name", ns)
            if name_elem is not None and name_elem.text:
                autores.append(name_elem.text.strip())

        # Procura link do artigo e do PDF
        landing_url = artigo_id
        pdf_url = ""
        for link in entry.findall("atom:link", ns):
            rel = link.get("rel")
            href = link.get("href", "")
            title = link.get("title", "")
            if title.lower() == "pdf" or link.get("type") == "application/pdf":
                pdf_url = href
            elif rel == "alternate" and href:
                landing_url = href

        if not pdf_url and "/abs/" in landing_url:
            pdf_url = landing_url.replace("/abs/", "/pdf/")

        ref_abnt = formatar_referencia_abnt(
            autores=autores,
            titulo=titulo,
            veiculo_ou_periodico="arXiv",
            ano=ano,
            url=landing_url,
        )

        resultados.append({
            "id": artigo_id,
            "fonte_api": "arXiv",
            "titulo": titulo,
            "autores": autores,
            "ano": ano,
            "resumo": resumo,
            "veiculo": "arXiv",
            "url": landing_url,
            "pdf_url": pdf_url,
            "referencia_abnt": ref_abnt,
        })

    return resultados


def buscar_artigos(
    termo: str,
    fonte: str = "todos",
    limite: int = 5,
    url_openalex: Optional[str] = None,
    url_arxiv: Optional[str] = None,
    http_client: Optional[Callable[[str, Dict[str, str]], str]] = None,
) -> List[Dict[str, Any]]:
    """Busca artigos cientificos unificando OpenAlex e arXiv."""
    fonte_norm = fonte.lower().strip()
    if fonte_norm == "openalex":
        return buscar_openalex(termo, limite=limite, url_api=url_openalex, http_client=http_client)
    if fonte_norm == "arxiv":
        return buscar_arxiv(termo, limite=limite, url_api=url_arxiv, http_client=http_client)

    # Busca em ambos e intercala/combina
    res_openalex = buscar_openalex(termo, limite=limite, url_api=url_openalex, http_client=http_client)
    res_arxiv = buscar_arxiv(termo, limite=limite, url_api=url_arxiv, http_client=http_client)

    combinados = []
    max_len = max(len(res_openalex), len(res_arxiv))
    for i in range(max_len):
        if i < len(res_openalex):
            combinados.append(res_openalex[i])
        if i < len(res_arxiv):
            combinados.append(res_arxiv[i])
        if len(combinados) >= limite:
            break

    return combinados[:limite]


def salvar_artigo_na_disciplina(
    artigo: Dict[str, Any],
    disciplina_nome: str,
    base_dir: Optional[Path] = None,
    caminho_db: Optional[Path] = None,
) -> Dict[str, Any]:
    """Salva a ficha e o resumo do artigo cientifico com sua referencia ABNT como material da disciplina."""
    disc = estudos.obter_disciplina(disciplina_nome, caminho_db=caminho_db)
    if not disc:
        disc = estudos.criar_disciplina(disciplina_nome, base_dir=base_dir, caminho_db=caminho_db)

    pasta = Path(disc["pasta"])
    pasta.mkdir(parents=True, exist_ok=True)

    titulo = artigo.get("titulo", "Artigo Sem Titulo").strip()
    slug_tit = estudos.normalizar_slug(titulo)
    arquivo_txt = pasta / f"artigo_{slug_tit}.txt"

    ref_abnt = artigo.get("referencia_abnt") or formatar_referencia_abnt(
        autores=artigo.get("autores", []),
        titulo=titulo,
        veiculo_ou_periodico=artigo.get("veiculo", "Repositorio"),
        ano=artigo.get("ano", datetime.now().year),
        url=artigo.get("url", ""),
    )

    autores_str = ", ".join(artigo.get("autores", [])) or "Autor desconhecido"
    linhas_conteudo = [
        f"Artigo Cientifico: {titulo}",
        f"Referencia ABNT: {ref_abnt}",
        f"Autores: {autores_str}",
        f"Ano: {artigo.get('ano', '')}",
        f"Fonte / Veiculo: {artigo.get('veiculo', '')}",
        f"URL: {artigo.get('url', '')}",
    ]
    if artigo.get("pdf_url"):
        linhas_conteudo.append(f"PDF Aberto: {artigo.get('pdf_url')}")

    linhas_conteudo.append("\nResumo (Abstract):")
    linhas_conteudo.append(artigo.get("resumo", "Sem resumo."))

    texto_final = "\n".join(linhas_conteudo)
    arquivo_txt.write_text(texto_final, encoding="utf-8")

    # Importa no indice SQLite FTS5 da disciplina
    resultado_import = estudos.importar_material(
        disciplina_nome=disc["nome"],
        origem=arquivo_txt,
        titulo=f"Artigo: {titulo}",
        tipo="artigo_cientifico",
        base_dir=base_dir,
        caminho_db=caminho_db,
        pastas_autorizadas=[pasta, pasta.parent],
        canal="local",
    )

    return {
        "ok": True,
        "material_id": resultado_import.get("id"),
        "disciplina": disc["nome"],
        "titulo": titulo,
        "caminho": str(arquivo_txt),
        "referencia_abnt": ref_abnt,
        "aviso": f"Artigo '{titulo}' salvo com sucesso em {disc['nome']}.",
    }


def resumo_artigos_falado(artigos: List[Dict[str, Any]], termo: str) -> str:
    """Gera resumo falado amigavel para transmissao no assistente."""
    if not artigos:
        return f"Nao encontrei artigos cientificos sobre {termo} nas fontes abertas."

    qtd = len(artigos)
    primeiro = artigos[0]
    autor_destaque = primeiro["autores"][0] if primeiro.get("autores") else "autor desconhecido"
    ano_destaque = primeiro.get("ano", "")

    if qtd == 1:
        return (
            f"Encontrei 1 artigo sobre {termo}: '{primeiro['titulo']}', "
            f"publicado por {autor_destaque} em {ano_destaque}."
        )

    return (
        f"Encontrei {qtd} artigos sobre {termo}. O principal e '{primeiro['titulo']}', "
        f"de {autor_destaque} ({ano_destaque}). Deseja que eu salve na sua biblioteca?"
    )
