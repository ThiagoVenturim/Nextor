"""Estudo ativo no NexRead: marcacoes, gravacoes, integracao com biblioteca de estudos e conversa com IA (Issue #55)."""
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .. import artigos_cientificos, estudos, qa_estudos
from .armazenamento import ArmazenamentoNexRead
from .modelos import ArtigoLido, BlocoPagina, GravacaoLeitura, Marcacao, MensagemChatArtigo
from .tradutor import reconstruir_html_layout


def marcar_trecho(
    artigo_id: str,
    trecho: str,
    nota: str = "",
    cor: str = "amarelo",
    bloco_id: str = "",
    trecho_traduzido: str = "",
    tags: Optional[List[str]] = None,
    db: Optional[ArmazenamentoNexRead] = None,
) -> Marcacao:
    """Destaca e anota um trecho do artigo, atualizando o HTML ao vivo com a marcacao."""
    trecho_limpo = (trecho or "").strip()
    if not trecho_limpo:
        raise ValueError("O trecho para marcacao nao pode ser vazio.")

    banco = db or ArmazenamentoNexRead()
    artigo = banco.obter_artigo(artigo_id)
    if not artigo:
        raise ValueError(f"Artigo '{artigo_id}' nao encontrado no NexRead.")

    bloco_resolvido = bloco_id.strip()
    traduzido_resolvido = trecho_traduzido.strip()

    if not bloco_resolvido:
        trecho_lower = trecho_limpo.lower()
        for b in artigo.blocos:
            if trecho_lower in b.texto_original.lower() or trecho_lower in b.texto_traduzido.lower():
                bloco_resolvido = b.id
                if not traduzido_resolvido:
                    traduzido_resolvido = b.texto_traduzido
                break

    marcacao = Marcacao(
        artigo_id=artigo.id,
        bloco_id=bloco_resolvido,
        trecho_original=trecho_limpo,
        trecho_traduzido=traduzido_resolvido,
        nota=nota.strip(),
        cor=cor,
        tags=tags or [],
    )
    banco.salvar_marcacao(marcacao)

    todas_marcacoes = banco.listar_marcacoes(artigo.id)
    artigo.html_traduzido = reconstruir_html_layout(
        artigo.blocos,
        modo_layout=artigo.modo_layout,
        marcacoes=todas_marcacoes,
    )
    banco.salvar_artigo(artigo)
    return marcacao


def gravar_nota_leitura(
    artigo_id: str,
    transcricao: str,
    titulo: str = "Nota de voz do estudo",
    caminho_audio: str = "",
    duracao_seg: int = 0,
    bloco_id: str = "",
    db: Optional[ArmazenamentoNexRead] = None,
) -> GravacaoLeitura:
    """Registra uma gravacao de voz ou reflexao falada vinculada ao artigo em estudo."""
    texto_transcricao = (transcricao or "").strip()
    if not texto_transcricao:
        raise ValueError("A transcricao ou conteudo da gravacao nao pode ser vazia.")

    banco = db or ArmazenamentoNexRead()
    artigo = banco.obter_artigo(artigo_id)
    if not artigo:
        raise ValueError(f"Artigo '{artigo_id}' nao encontrado no NexRead.")

    gravacao = GravacaoLeitura(
        artigo_id=artigo.id,
        titulo=(titulo or "Nota de voz do estudo").strip(),
        transcricao=texto_transcricao,
        caminho_audio=caminho_audio.strip(),
        duracao_seg=max(0, int(duracao_seg or 0)),
        bloco_id=bloco_id.strip(),
    )
    return banco.salvar_gravacao(gravacao)


def salvar_na_biblioteca_estudos(
    artigo_id: str,
    disciplina_nome: str,
    incluir_original: bool = True,
    db: Optional[ArmazenamentoNexRead] = None,
    base_dir_estudos: Optional[Path] = None,
    caminho_db_estudos: Optional[Path] = None,
) -> Dict[str, Any]:
    """Salva o artigo traduzido, marcacoes, notas e gravacoes na biblioteca do modo estudante."""
    disc_limpa = (disciplina_nome or "").strip()
    if not disc_limpa:
        raise ValueError("Nome da disciplina e obrigatorio para salvar na biblioteca de estudos.")

    banco = db or ArmazenamentoNexRead()
    artigo = banco.obter_artigo(artigo_id)
    if not artigo:
        raise ValueError(f"Artigo '{artigo_id}' nao encontrado no NexRead.")

    marcacoes = banco.listar_marcacoes(artigo.id)
    gravacoes = banco.listar_gravacoes(artigo.id)

    disc = estudos.obter_disciplina(disc_limpa, caminho_db=caminho_db_estudos)
    if not disc:
        disc = estudos.criar_disciplina(disc_limpa, base_dir=base_dir_estudos, caminho_db=caminho_db_estudos)

    pasta_disc = Path(disc["pasta"])
    pasta_disc.mkdir(parents=True, exist_ok=True)

    autores_lista = [a.strip() for a in artigo.autor.split(",") if a.strip()] if artigo.autor else []
    ano_ref = artigo.ano or datetime.now().year
    ref_abnt = artigos_cientificos.formatar_referencia_abnt(
        autores=autores_lista,
        titulo=artigo.titulo,
        veiculo_ou_periodico=artigo.veiculo or "NexRead Web",
        ano=ano_ref,
        url=artigo.url,
    )

    linhas: List[str] = [
        f"# {artigo.titulo_traduzido or artigo.titulo}",
        f"Titulo original: {artigo.titulo}",
        f"Referencia ABNT: {ref_abnt}",
    ]
    if artigo.url:
        linhas.append(f"URL: {artigo.url}")
    linhas.append(f"Idioma: {artigo.idioma_origem} -> {artigo.idioma_destino} (motor: {artigo.motor_traducao})")
    linhas.append("")
    linhas.append("## Traducao do Artigo")
    for b in artigo.blocos:
        prefixo = "### " if b.tag.startswith("h") else ("> " if b.tag == "blockquote" else "")
        linhas.append(f"{prefixo}[Bloco {b.indice}] {b.texto_traduzido or b.texto_original}")
        if incluir_original and b.texto_original and b.texto_original != b.texto_traduzido:
            linhas.append(f"Original: {b.texto_original}")
        linhas.append("")

    if marcacoes:
        linhas.append("## Marcacoes e Anotacoes")
        for idx_m, m in enumerate(marcacoes, 1):
            linhas.append(f"- Marcacao {idx_m} ({m.cor}): \"{m.trecho_original}\"")
            if m.trecho_traduzido:
                linhas.append(f"  Traducao: \"{m.trecho_traduzido}\"")
            if m.nota:
                linhas.append(f"  Nota do estudante: {m.nota}")

    if gravacoes:
        linhas.append("")
        linhas.append("## Gravacoes e Notas de Voz")
        for idx_g, g in enumerate(gravacoes, 1):
            dur_str = f" ({g.duracao_seg}s)" if g.duracao_seg else ""
            linhas.append(f"- Gravacao {idx_g} - {g.titulo}{dur_str}: {g.transcricao}")

    slug_arq = estudos.normalizar_slug(artigo.titulo_traduzido or artigo.titulo)
    caminho_md = pasta_disc / f"nexread_{slug_arq}.md"
    caminho_md.write_text("\n".join(linhas), encoding="utf-8")

    res_import = estudos.importar_material(
        disciplina_nome=disc["nome"],
        origem=caminho_md,
        titulo=f"NexRead: {artigo.titulo_traduzido or artigo.titulo}",
        tipo="markdown",
        base_dir=base_dir_estudos,
        caminho_db=caminho_db_estudos,
        pastas_autorizadas=[pasta_disc, pasta_disc.parent],
        canal="local",
    )

    artigo.disciplina = disc["nome"]
    artigo.material_id = res_import.get("id")
    banco.salvar_artigo(artigo)

    return {
        "ok": True,
        "artigo_id": artigo.id,
        "material_id": res_import.get("id"),
        "disciplina": disc["nome"],
        "titulo": artigo.titulo_traduzido or artigo.titulo,
        "caminho": str(caminho_md),
        "referencia_abnt": ref_abnt,
        "total_marcacoes": len(marcacoes),
        "total_gravacoes": len(gravacoes),
        "aviso": f"Artigo '{artigo.titulo_traduzido or artigo.titulo}' salvo na disciplina {disc['nome']}.",
    }


def _selecionar_blocos_relevantes(
    artigo: ArtigoLido,
    marcacoes: List[Marcacao],
    pergunta: str,
    limite: int = 4,
) -> List[Dict[str, Any]]:
    """Seleciona os blocos e marcacoes do proprio texto que melhor fundamentam a resposta."""
    termos = qa_estudos.extrair_termos_busca(pergunta)
    candidatos: List[Dict[str, Any]] = []

    for b in artigo.blocos:
        texto_busca = f"{b.texto_original} {b.texto_traduzido}".lower()
        score = sum(2 for t in termos if t in texto_busca)
        if b.tag in ("h1", "h2", "h3"):
            score += 1
        candidatos.append({
            "bloco": b,
            "fonte": f"{artigo.titulo_traduzido or artigo.titulo} [Bloco {b.indice} ({b.tag})]",
            "trecho": b.texto_traduzido or b.texto_original,
            "original": b.texto_original,
            "score": score,
        })

    for idx_m, m in enumerate(marcacoes, 1):
        texto_m = f"{m.trecho_original} {m.trecho_traduzido} {m.nota}".lower()
        score_m = sum(3 for t in termos if t in texto_m) + 1
        detalhe_nota = f" | Nota: {m.nota}" if m.nota else ""
        candidatos.append({
            "bloco": None,
            "fonte": f"{artigo.titulo_traduzido or artigo.titulo} [Marcacao {idx_m}]",
            "trecho": f"{m.trecho_traduzido or m.trecho_original}{detalhe_nota}",
            "original": m.trecho_original,
            "score": score_m,
        })

    if termos:
        com_match = [c for c in candidatos if c["score"] > 1]
        if com_match:
            com_match.sort(key=lambda x: x["score"], reverse=True)
            return com_match[:limite]

    # Para resumo ou discussao geral sem termos especificos, retorna os principais blocos
    return candidatos[:limite]


def conversar_sobre_artigo(
    artigo_id: str,
    pergunta: str = "",
    acao: str = "perguntar",
    buscar_fontes_cientificas: bool = False,
    cerebro_fn: Optional[Callable[[str, str], str]] = None,
    http_client_artigos: Optional[Callable[[str, Dict[str, str]], str]] = None,
    db: Optional[ArmazenamentoNexRead] = None,
) -> Dict[str, Any]:
    """Conversa com a IA sobre o tema do artigo (perguntar, resumir, discutir) citando fontes do texto."""
    banco = db or ArmazenamentoNexRead()
    artigo = banco.obter_artigo(artigo_id)
    if not artigo:
        raise ValueError(f"Artigo '{artigo_id}' nao encontrado no NexRead.")

    acao_norm = (acao or "perguntar").strip().lower()
    if acao_norm not in ("perguntar", "resumir", "discutir", "explicar"):
        acao_norm = "perguntar"

    pergunta_efetiva = (pergunta or "").strip()
    if not pergunta_efetiva:
        if acao_norm == "resumir":
            pergunta_efetiva = f"Resuma os pontos principais do artigo '{artigo.titulo}'."
        elif acao_norm == "discutir":
            pergunta_efetiva = f"Quais sao as principais contribuicoes e implicacoes de '{artigo.titulo}'?"
        else:
            raise ValueError("Informe uma pergunta ou topico para conversar sobre o artigo.")

    marcacoes = banco.listar_marcacoes(artigo.id)
    selecionados = _selecionar_blocos_relevantes(artigo, marcacoes, pergunta_efetiva, limite=4)
    fontes_citadas = [s["fonte"] for s in selecionados]

    artigos_rel: List[Dict[str, Any]] = []
    if buscar_fontes_cientificas:
        termo_pesquisa = pergunta.strip() or artigo.titulo
        try:
            artigos_rel = artigos_cientificos.buscar_artigos(
                termo_pesquisa,
                limite=3,
                http_client=http_client_artigos,
            )
            for ar in artigos_rel:
                if ar.get("referencia_abnt"):
                    fontes_citadas.append(ar["referencia_abnt"])
        except Exception:
            artigos_rel = []

    bloco_contexto = "\n\n".join(
        f"Fonte: {s['fonte']}\nTexto traduzido: {s['trecho']}\nTexto original: {s['original']}"
        for s in selecionados
    )
    if artigos_rel:
        bloco_artigos = "\n".join(
            f"- {a.get('titulo')}: {a.get('resumo', '')[:200]} (Ref: {a.get('referencia_abnt')})"
            for a in artigos_rel
        )
        bloco_contexto += f"\n\nArtigos cientificos relacionados:\n{bloco_artigos}"

    sistema = (
        "Voce e o tutor academico do NexRead (Nextor). "
        "Ajude o estudante a compreender, resumir ou discutir o artigo aberto, "
        "baseando-se estritamente nos blocos e marcacoes fornecidos e citando as fontes (ex: [Bloco 1]). "
        "Responda em portugues do Brasil de forma clara e objetiva."
    )
    prompt_usuario = (
        f"Artigo aberto: {artigo.titulo_traduzido} (Original: {artigo.titulo})\n"
        f"Acao solicitada: {acao_norm}\n"
        f"Pedido do estudante: {pergunta_efetiva}\n\n"
        f"Fontes extraidas do proprio texto:\n{bloco_contexto}"
    )

    # Registra mensagem do usuario no historico
    banco.salvar_mensagem_chat(
        MensagemChatArtigo(
            artigo_id=artigo.id,
            papel="usuario",
            conteudo=pergunta_efetiva,
            acao=acao_norm,
        )
    )

    resposta_ia = ""
    if cerebro_fn is not None:
        try:
            resposta_ia = (cerebro_fn(prompt_usuario, sistema) or "").strip()
        except Exception:
            resposta_ia = ""
    else:
        try:
            from .. import cerebro
            resposta_ia = (cerebro.responder(prompt_usuario, sistema=sistema, tokens=500) or "").strip()
        except Exception:
            resposta_ia = ""

    # Fallback deterministico offline com citacao explicita dos blocos do proprio texto
    if not resposta_ia:
        if not selecionados:
            resposta_ia = f"O artigo '{artigo.titulo_traduzido}' nao possui blocos suficientes para responder."
        elif acao_norm == "resumir":
            trechos_resumo = [f"- ({s['fonte']}) {s['trecho']}" for s in selecionados[:3]]
            resposta_ia = (
                f"Resumo com base nas fontes do proprio texto ('{artigo.titulo_traduzido}'):\n"
                + "\n".join(trechos_resumo)
            )
        else:
            principal = selecionados[0]
            resposta_ia = (
                f"Segundo {principal['fonte']}: \"{principal['trecho']}\"."
            )
            if len(selecionados) > 1:
                seg = selecionados[1]
                resposta_ia += f" Complementando com {seg['fonte']}: \"{seg['trecho']}\"."

    msg_assistente = banco.salvar_mensagem_chat(
        MensagemChatArtigo(
            artigo_id=artigo.id,
            papel="assistente",
            conteudo=resposta_ia,
            acao=acao_norm,
            fontes=fontes_citadas,
            artigos_relacionados=artigos_rel,
        )
    )

    return {
        "ok": True,
        "artigo_id": artigo.id,
        "acao": acao_norm,
        "pergunta": pergunta_efetiva,
        "resposta": resposta_ia,
        "fontes": fontes_citadas,
        "trechos_usados": [s["trecho"] for s in selecionados],
        "artigos_relacionados": artigos_rel,
        "mensagem_id": msg_assistente.id,
    }
