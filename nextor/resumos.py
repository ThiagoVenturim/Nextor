"""Modulo de resumos e geracao de flashcards para Anki do modo Estudos."""
import csv
import io
import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import config, estudos


def normalizar_slug(texto: str) -> str:
    return estudos.normalizar_slug(texto)


def localizar_material_para_resumo(
    disciplina_nome: str,
    alvo: str = "",
    caminho_db: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """Localiza o material correspondente ao pedido (ex: 'ultima aula', 'capitulo 3', etc.)."""
    disc = estudos.obter_disciplina(disciplina_nome, caminho_db=caminho_db)
    if not disc:
        return None

    con = estudos.conectar_db(caminho_db)
    try:
        disc_id = disc["id"]
        alvo_limpo = (alvo or "").strip().lower()

        # Caso 1: alvo e "ultima aula", "aula", "ultima" ou vazio -> busca aula mais recente ou material mais recente
        if not alvo_limpo or "ultima aula" in alvo_limpo or alvo_limpo in ("aula", "ultima"):
            cur = con.execute(
                """
                SELECT id, disciplina_id, titulo, tipo, caminho_ou_url, conteudo, criado_em
                FROM materiais
                WHERE disciplina_id = ? AND (tipo = 'aula' OR lower(titulo) LIKE '%aula%')
                ORDER BY criado_em DESC LIMIT 1
                """,
                (disc_id,),
            )
            row = cur.fetchone()
            if row:
                res = dict(row)
                res["disciplina_nome"] = disc["nome"]
                return res

            # Fallback para o material mais recente qualquer
            cur = con.execute(
                """
                SELECT id, disciplina_id, titulo, tipo, caminho_ou_url, conteudo, criado_em
                FROM materiais
                WHERE disciplina_id = ?
                ORDER BY criado_em DESC LIMIT 1
                """,
                (disc_id,),
            )
            row = cur.fetchone()
            if row:
                res = dict(row)
                res["disciplina_nome"] = disc["nome"]
                return res
            return None

        # Caso 2: busca por capitulo ou titulo direto
        cur = con.execute(
            """
            SELECT id, disciplina_id, titulo, tipo, caminho_ou_url, conteudo, criado_em
            FROM materiais
            WHERE disciplina_id = ? AND lower(titulo) LIKE ?
            ORDER BY criado_em DESC LIMIT 1
            """,
            (disc_id, f"%{alvo_limpo}%"),
        )
        row = cur.fetchone()
        if row:
            res = dict(row)
            res["disciplina_nome"] = disc["nome"]
            return res

        # Caso 3: busca textual FTS
        resultados_fts = estudos.buscar_materiais(alvo_limpo, disciplina_nome=disc["nome"], limite=1, caminho_db=caminho_db)
        if resultados_fts:
            mat_id = resultados_fts[0]["material_id"]
            cur = con.execute(
                """
                SELECT id, disciplina_id, titulo, tipo, caminho_ou_url, conteudo, criado_em
                FROM materiais
                WHERE id = ?
                """,
                (mat_id,),
            )
            row = cur.fetchone()
            if row:
                res = dict(row)
                res["disciplina_nome"] = disc["nome"]
                return res

        return None
    finally:
        con.close()


def _extrair_trechos_heuristicos(conteudo: str, titulo: str, max_trechos: int = 5) -> List[Dict[str, str]]:
    """Divide o conteudo em trechos significativos com marcacao de fonte."""
    linhas = [l.strip() for l in conteudo.splitlines() if l.strip()]
    if not linhas:
        return []

    # Verifica se ha marcadores de aula no formato [MM:SS - MM:SS] ou [HH:MM:SS - HH:MM:SS]
    trechos = []
    padrao_tempo = re.compile(r"\[(\d{2}:\d{2}(?::\d{2})?\s*-\s*\d{2}:\d{2}(?::\d{2})?)\]\s*(.+)")
    for linha in linhas:
        m = padrao_tempo.match(linha)
        if m:
            tempo = m.group(1).strip()
            texto = m.group(2).strip()
            if len(texto) >= 15:
                trechos.append({
                    "texto": texto,
                    "fonte": f"{titulo} [{tempo}]",
                })
        if len(trechos) >= max_trechos:
            break

    if trechos:
        return trechos

    # Se nao for aula gravada com timestamps, agrupa paragrafos
    paragrafos = []
    bloco_atual = []
    for l in linhas:
        if l.startswith("Aviso de consentimento:") or l.startswith("URL:"):
            continue
        bloco_atual.append(l)
        if len(" ".join(bloco_atual)) >= 180:
            paragrafos.append(" ".join(bloco_atual))
            bloco_atual = []
        if len(paragrafos) >= max_trechos:
            break
    if bloco_atual and len(paragrafos) < max_trechos:
        paragrafos.append(" ".join(bloco_atual))

    resultado = []
    for i, p in enumerate(paragrafos, 1):
        trecho_curto = p[:60] + "..." if len(p) > 60 else p
        resultado.append({
            "texto": p,
            "fonte": f"{titulo} (secao {i}: \"{trecho_curto}\")",
        })
    return resultado


def _gerar_fallback_deterministico(
    conteudo: str,
    titulo: str,
    disciplina: str,
    gerar_cards: bool = True,
) -> Dict[str, Any]:
    """Gera resumo em topicos e flashcards de forma deterministica sem depender de LLM."""
    trechos = _extrair_trechos_heuristicos(conteudo, titulo, max_trechos=5)
    slug_disc = normalizar_slug(disciplina)

    if not trechos:
        ponto_geral = conteudo.strip()[:200] or "Conteudo do material registrado."
        trechos = [{"texto": ponto_geral, "fonte": titulo}]

    topicos = []
    flashcards = []

    for t in trechos:
        texto = t["texto"]
        fonte = t["fonte"]
        # Extrai primeiro ponto ou frase
        frase = texto.split(".")[0].strip() or texto[:120].strip()
        topicos.append({
            "ponto": frase,
            "fonte": fonte,
        })
        if gerar_cards:
            pergunta = f"Qual o conceito abordado em {titulo} sobre '{frase[:40]}...'?"
            resposta = frase
            flashcards.append({
                "pergunta": pergunta,
                "resposta": resposta,
                "fonte": fonte,
                "tag": f"estudos::{slug_disc}",
            })

    resumo_geral = f"Resumo dos pontos centrais de {titulo} ({disciplina}): " + " | ".join(t["ponto"] for t in topicos)

    return {
        "resumo_geral": resumo_geral,
        "topicos": topicos,
        "flashcards": flashcards,
    }


def gerar_resumo_e_flashcards(
    conteudo: str,
    titulo: str,
    disciplina: str,
    cerebro_fn: Optional[Callable[[str, str], str]] = None,
    gerar_cards: bool = True,
) -> Dict[str, Any]:
    """Gera resumo estruturado em topicos com fontes e flashcards para Anki.
    
    Tenta utilizar o cerebro configurado (Ollama/Claude) e cai de forma graciosa
    para o extrator deterministico se o cerebro estiver indisponivel ou falhar.
    """
    if not conteudo or not conteudo.strip():
        return {
            "resumo_geral": "Nenhum conteudo disponivel para resumir.",
            "topicos": [],
            "flashcards": [],
        }

    slug_disc = normalizar_slug(disciplina)
    trecho_amostra = conteudo[:4000]

    sistema = (
        "Voce e o assistente de estudos Nextor. Responda ESTRITAMENTE em formato JSON valido, "
        "sem markdown, sem introducao ou explicacao adicional. "
        "Estrutura esperada: "
        "{\"resumo_geral\": \"...\", \"topicos\": [{\"ponto\": \"...\", \"fonte\": \"...\"}], "
        "\"flashcards\": [{\"pergunta\": \"...\", \"resposta\": \"...\", \"fonte\": \"...\", \"tag\": \"...\"}]}"
    )

    mensagem = (
        f"Material: {titulo}\n"
        f"Disciplina: {disciplina}\n"
        f"Tag sugerida: estudos::{slug_disc}\n\n"
        f"Conteudo:\n{trecho_amostra}\n\n"
        f"Instrucoes:\n"
        f"1. Crie entre 3 e 5 topicos com o ponto central e a fonte exata (arquivo ou trecho).\n"
        f"2. Se gerar flashcards: crie entre 3 e 6 perguntas e respostas concisas e objetivas.\n"
        f"3. Cada topico e cada flashcard DEVE ter o campo 'fonte' indicando de onde a informacao veio."
    )

    resposta_texto = ""
    if cerebro_fn is not None:
        try:
            resposta_texto = cerebro_fn(mensagem, sistema)
        except Exception:
            resposta_texto = ""
    else:
        try:
            from . import cerebro
            resposta_texto = cerebro.responder(mensagem, sistema=sistema, tokens=500)
        except Exception:
            resposta_texto = ""

    if resposta_texto:
        # Limpa eventuais marcadores ```json ... ```
        limpo = re.sub(r"^```(?:json)?\s*", "", resposta_texto.strip(), flags=re.IGNORECASE)
        limpo = re.sub(r"\s*```$", "", limpo).strip()
        try:
            dados = json.loads(limpo)
            if isinstance(dados, dict) and "topicos" in dados:
                topicos_validos = []
                for tp in dados.get("topicos", []):
                    if isinstance(tp, dict) and "ponto" in tp:
                        topicos_validos.append({
                            "ponto": str(tp.get("ponto", "")).strip(),
                            "fonte": str(tp.get("fonte", "")).strip() or titulo,
                        })

                cards_validos = []
                for fc in dados.get("flashcards", []):
                    if isinstance(fc, dict) and "pergunta" in fc and "resposta" in fc:
                        cards_validos.append({
                            "pergunta": str(fc.get("pergunta", "")).strip(),
                            "resposta": str(fc.get("resposta", "")).strip(),
                            "fonte": str(fc.get("fonte", "")).strip() or titulo,
                            "tag": str(fc.get("tag", "")).strip() or f"estudos::{slug_disc}",
                        })

                if topicos_validos:
                    return {
                        "resumo_geral": str(dados.get("resumo_geral", "")).strip() or f"Resumo de {titulo}.",
                        "topicos": topicos_validos,
                        "flashcards": cards_validos if gerar_cards else [],
                    }
        except Exception:
            pass

    # Fallback deterministico com fontes reais
    return _gerar_fallback_deterministico(conteudo, titulo, disciplina, gerar_cards=gerar_cards)


def exportar_flashcards_anki(flashcards: List[Dict[str, str]], formato: str = "csv") -> str:
    """Exporta lista de flashcards no formato CSV ou TSV compativel com importacao do Anki.
    
    Campos exportados: Pergunta, Resposta, Fonte, Tag.
    """
    buffer = io.StringIO()
    separador = "\t" if formato.lower() == "tsv" else ","
    writer = csv.writer(buffer, delimiter=separador, lineterminator="\n")

    # Cabecalho compativel com Anki (#tags column:4)
    if formato.lower() == "tsv":
        buffer.write("#separator:Tab\n#html:false\n#tags column:4\n")
    else:
        buffer.write("#separator:Comma\n#html:false\n#tags column:4\n")

    for card in flashcards:
        pergunta = card.get("pergunta", "").replace("\n", " ").strip()
        resposta = card.get("resposta", "").replace("\n", " ").strip()
        fonte = card.get("fonte", "").replace("\n", " ").strip()
        tag = card.get("tag", "").replace("\n", " ").strip()
        writer.writerow([pergunta, resposta, fonte, tag])

    return buffer.getvalue()


def salvar_flashcards_disco(
    disciplina_nome: str,
    titulo_material: str,
    flashcards: List[Dict[str, str]],
    base_dir: Optional[Path] = None,
    formato: str = "csv",
) -> Path:
    """Salva os flashcards no disco na pasta da disciplina."""
    pasta = estudos.obter_pasta_disciplina(disciplina_nome, base_dir=base_dir)
    slug_mat = normalizar_slug(titulo_material)
    ext = "tsv" if formato.lower() == "tsv" else "csv"
    arquivo = pasta / f"flashcards_{slug_mat}.{ext}"

    conteudo_export = exportar_flashcards_anki(flashcards, formato=formato)
    arquivo.write_text(conteudo_export, encoding="utf-8")
    return arquivo


def resumir_estudos(
    disciplina_nome: str,
    alvo: str = "",
    cerebro_fn: Optional[Callable[[str, str], str]] = None,
    caminho_db: Optional[Path] = None,
    base_dir: Optional[Path] = None,
    gerar_cards: bool = True,
    formato_exportacao: str = "csv",
) -> Dict[str, Any]:
    """Fluxo completo de resumo de estudos com localizacao do material e geracao de flashcards."""
    material = localizar_material_para_resumo(disciplina_nome, alvo=alvo, caminho_db=caminho_db)
    if not material:
        return {
            "ok": False,
            "erro": f"Nao encontrei nenhum material para '{alvo or 'aula'}' na disciplina {disciplina_nome}.",
            "aviso": f"Nao encontrei material sobre {alvo or 'aula'} em {disciplina_nome}.",
        }

    titulo = material["titulo"]
    conteudo = material.get("conteudo", "")
    disc_nome = material.get("disciplina_nome", disciplina_nome)

    dados = gerar_resumo_e_flashcards(
        conteudo=conteudo,
        titulo=titulo,
        disciplina=disc_nome,
        cerebro_fn=cerebro_fn,
        gerar_cards=gerar_cards,
    )

    flashcards = dados.get("flashcards", [])
    caminho_arquivo = ""
    if flashcards:
        try:
            arq = salvar_flashcards_disco(
                disciplina_nome=disc_nome,
                titulo_material=titulo,
                flashcards=flashcards,
                base_dir=base_dir,
                formato=formato_exportacao,
            )
            caminho_arquivo = str(arq)
        except Exception:
            pass

    # Formatar resposta falada amigavel para o assistente
    topicos = dados.get("topicos", [])
    linhas_fala = [f"Resumo de {disc_nome} ({titulo}):"]
    for t in topicos:
        linhas_fala.append(f"- {t['ponto']} (Fonte: {t['fonte']})")

    if flashcards:
        linhas_fala.append(f"Foram gerados {len(flashcards)} flashcards para o Anki.")

    aviso_falado = "\n".join(linhas_fala)

    return {
        "ok": True,
        "disciplina": disc_nome,
        "titulo": titulo,
        "tipo": material.get("tipo", ""),
        "caminho_ou_url": material.get("caminho_ou_url", ""),
        "resumo_geral": dados.get("resumo_geral", ""),
        "topicos": topicos,
        "flashcards": flashcards,
        "arquivo_flashcards": caminho_arquivo,
        "aviso": aviso_falado,
    }
