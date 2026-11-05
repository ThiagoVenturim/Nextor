"""Modulo de perguntas e respostas sobre materias com citacao estrita de fontes (Issue #5)."""
import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import config, estudos

STOP_WORDS = {
    "o", "a", "os", "as", "um", "uma", "uns", "umas", "de", "do", "da", "dos", "das",
    "em", "no", "na", "nos", "nas", "por", "pelo", "pela", "pelos", "pelas", "com",
    "para", "que", "e", "se", "ou", "como", "qual", "quais", "quem", "onde", "quando",
    "por que", "porque", "sobre", "me", "meu", "minha", "meus", "minhas", "segundo",
    "material", "materia", "disciplina", "diz", "explica", "explicar", "fala", "aula",
}


def extrair_termos_busca(pergunta: str) -> List[str]:
    """Extrai palavras-chave significativas da pergunta, removendo stop words comuns."""
    palavras = re.findall(r"\b[a-zA-Z0-9_\u00C0-\u00FF]+\b", pergunta.lower())
    termos = [p for p in palavras if p not in STOP_WORDS and len(p) >= 2]
    return termos


def _extrair_trecho_com_timestamp_ou_secao(conteudo: str, termos: List[str], titulo: str) -> Optional[Dict[str, str]]:
    """Localiza o segmento timestamped ou paragrafo mais relevante dentro do conteudo."""
    linhas = [l.strip() for l in conteudo.splitlines() if l.strip()]
    if not linhas:
        return None

    # 1. Procura em linhas timestamped de aula: [MM:SS - MM:SS] texto
    padrao_tempo = re.compile(r"\[(\d{2}:\d{2}(?::\d{2})?\s*-\s*\d{2}:\d{2}(?::\d{2})?)\]\s*(.+)")
    melhor_linha = ""
    melhor_tempo = ""
    melhor_score = 0

    for linha in linhas:
        m = padrao_tempo.match(linha)
        if m:
            tempo = m.group(1).strip()
            texto = m.group(2).strip()
            score = sum(1 for t in termos if t in texto.lower())
            if score > melhor_score:
                melhor_score = score
                melhor_linha = texto
                melhor_tempo = tempo

    if melhor_score > 0 and melhor_linha:
        return {
            "trecho": melhor_linha,
            "fonte": f"{titulo} [{melhor_tempo}]",
            "score": melhor_score,
        }

    # 2. Se nao for aula com timestamp, divide em paragrafos e pontua
    paragrafos = []
    bloco = []
    for l in linhas:
        if l.startswith("Aviso de consentimento:") or l.startswith("URL:"):
            continue
        bloco.append(l)
        if len(" ".join(bloco)) >= 150:
            paragrafos.append(" ".join(bloco))
            bloco = []
    if bloco:
        paragrafos.append(" ".join(bloco))

    melhor_p = ""
    idx_p = 0
    for i, p in enumerate(paragrafos, 1):
        score = sum(1 for t in termos if t in p.lower())
        if score > melhor_score:
            melhor_score = score
            melhor_p = p
            idx_p = i

    if melhor_score > 0 and melhor_p:
        trecho_resumido = melhor_p[:80] + "..." if len(melhor_p) > 80 else melhor_p
        return {
            "trecho": melhor_p,
            "fonte": f"{titulo} (secao {idx_p}: \"{trecho_resumido}\")",
            "score": melhor_score,
        }

    return None


def buscar_contexto_relevante(
    pergunta: str,
    disciplina_nome: str = "",
    limite: int = 4,
    caminho_db: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Busca trechos do material que respondam aos termos da pergunta."""
    termos = extrair_termos_busca(pergunta)
    if not termos:
        return []

    con = estudos.conectar_db(caminho_db)
    try:
        # Se disciplina for especificada, valida se existe
        disc_id = None
        disc_nome_real = ""
        if disciplina_nome.strip():
            disc = estudos.obter_disciplina(disciplina_nome, caminho_db=caminho_db)
            if not disc:
                return []
            disc_id = disc["id"]
            disc_nome_real = disc["nome"]

        # Busca materiais correspondentes
        if disc_id:
            cur = con.execute(
                "SELECT id, titulo, tipo, caminho_ou_url, conteudo FROM materiais WHERE disciplina_id = ?",
                (disc_id,),
            )
        else:
            cur = con.execute("SELECT id, titulo, tipo, caminho_ou_url, conteudo FROM materiais")

        candidatos = cur.fetchall()
        trechos_encontrados = []

        for row in candidatos:
            conteudo = row["conteudo"] or ""
            titulo = row["titulo"] or "Material"
            resultado = _extrair_trecho_com_timestamp_ou_secao(conteudo, termos, titulo)
            if resultado and resultado["score"] > 0:
                trechos_encontrados.append({
                    "material_id": row["id"],
                    "titulo": titulo,
                    "disciplina": disc_nome_real or "",
                    "trecho": resultado["trecho"],
                    "fonte": resultado["fonte"],
                    "score": resultado["score"],
                })

        # Ordena por relevância (score)
        trechos_encontrados.sort(key=lambda x: x["score"], reverse=True)
        return trechos_encontrados[:limite]
    finally:
        con.close()


def responder_com_material(
    pergunta: str,
    disciplina_nome: str = "",
    cerebro_fn: Optional[Callable[[str, str], str]] = None,
    caminho_db: Optional[Path] = None,
) -> Dict[str, Any]:
    """Responde a pergunta do usuario com base exclusiva no material de estudos cadastrado.
    
    Aplica a regra estrita anti-alucinacao: recusa responder e declara explicitamente
    a ausencia de informacao quando o material nao cobrir a pergunta.
    """
    disc_alvo = disciplina_nome.strip()

    # Se a disciplina nao veio explicitamente, tenta inferir de termos na pergunta
    if not disc_alvo:
        m_disc = re.search(r"(?:em|de|da|do)\s+([a-zA-Z0-9_\u00C0-\u00FF]+)\s*$", pergunta.strip(), flags=re.IGNORECASE)
        if m_disc:
            disc_candidata = m_disc.group(1).strip()
            disc = estudos.obter_disciplina(disc_candidata, caminho_db=caminho_db)
            if disc:
                disc_alvo = disc["nome"]

    trechos = buscar_contexto_relevante(
        pergunta=pergunta,
        disciplina_nome=disc_alvo,
        limite=4,
        caminho_db=caminho_db,
    )

    nome_disc_exibicao = disc_alvo or "seus estudos"

    # Regra estrita anti-alucinacao: se nao ha trechos relevantes nos materiais
    if not trechos:
        aviso_recusa = f"Essa informacao nao consta no seu material de {nome_disc_exibicao}."
        detalhe_recusa = (
            f"O seu material de {nome_disc_exibicao} nao contem informacoes sobre "
            f"a pergunta: '{pergunta}'. Nao invento informacoes que nao constem no seu material."
        )
        return {
            "ok": True,
            "encontrado": False,
            "disciplina": disc_alvo,
            "pergunta": pergunta,
            "resposta_fala": aviso_recusa,
            "resposta_detalhada": detalhe_recusa,
            "fontes": [],
            "trechos_usados": [],
        }

    # Prepara o contexto real extraido
    bloco_contexto = "\n\n".join([f"Fonte: {t['fonte']}\nTrecho: {t['trecho']}" for t in trechos])
    fontes_lista = [t["fonte"] for t in trechos]

    sistema = (
        "Voce e o assistente academico Nextor. "
        "Responda a pergunta do aluno BASEANDO-SE ESTRITAMENTE e EXCLUSIVAMENTE nos trechos fornecidos. "
        "Regras obrigatorias:\n"
        "1. Se os trechos nao responderem a pergunta com exatidao, recuse-se a responder e retorne "
        "'encontrado': false.\n"
        "2. NUNCA invente ou adicione conhecimento que nao conste nos trechos fornecidos.\n"
        "3. Responda ESTRITAMENTE em formato JSON sem markdown: "
        "{\"encontrado\": true|false, \"resposta_fala\": \"...\", \"resposta_detalhada\": \"...\", \"fontes\": [\"...\"]}\n"
        "4. 'resposta_fala' deve ser curta (1 a 2 frases) para leitura em voz alta no Nest, citando a fonte principal.\n"
        "5. 'resposta_detalhada' deve conter a explicacao completa acompanhada das citacoes das fontes."
    )

    mensagem = (
        f"Pergunta do aluno: {pergunta}\n"
        f"Disciplina: {nome_disc_exibicao}\n\n"
        f"Trechos do material:\n{bloco_contexto}\n\n"
        "Responda apenas com o JSON conforme instrucoes."
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
            resposta_texto = cerebro.responder(mensagem, sistema=sistema, tokens=600)
        except Exception:
            resposta_texto = ""

    # Parse do retorno LLM
    if resposta_texto:
        limpo = re.sub(r"^```(?:json)?\s*", "", resposta_texto.strip(), flags=re.IGNORECASE)
        limpo = re.sub(r"\s*```$", "", limpo).strip()
        try:
            dados = json.loads(limpo)
            if isinstance(dados, dict):
                encontrado = bool(dados.get("encontrado", True))
                if not encontrado:
                    return {
                        "ok": True,
                        "encontrado": False,
                        "disciplina": disc_alvo,
                        "pergunta": pergunta,
                        "resposta_fala": f"Essa informacao nao consta no seu material de {nome_disc_exibicao}.",
                        "resposta_detalhada": f"O seu material nao contem informacoes suficientes para responder '{pergunta}'.",
                        "fontes": [],
                        "trechos_usados": [],
                    }

                fala = str(dados.get("resposta_fala", "")).strip()
                detalhe = str(dados.get("resposta_detalhada", "")).strip()
                fontes_retornadas = dados.get("fontes") or fontes_lista

                if fala:
                    return {
                        "ok": True,
                        "encontrado": True,
                        "disciplina": disc_alvo,
                        "pergunta": pergunta,
                        "resposta_fala": fala,
                        "resposta_detalhada": detalhe or fala,
                        "fontes": fontes_retornadas,
                        "trechos_usados": [t["trecho"] for t in trechos],
                    }
        except Exception:
            pass

    # Fallback deterministico offline baseado estritamente no melhor trecho
    melhor = trechos[0]
    frase_curta = melhor["trecho"].split(".")[0].strip() or melhor["trecho"][:100].strip()
    fala_fallback = f"Segundo {melhor['fonte']}: {frase_curta}."
    detalhe_fallback = (
        f"Com base no seu material ({melhor['fonte']}):\n\n"
        f"\"{melhor['trecho']}\""
    )

    return {
        "ok": True,
        "encontrado": True,
        "disciplina": disc_alvo,
        "pergunta": pergunta,
        "resposta_fala": fala_fallback,
        "resposta_detalhada": detalhe_fallback,
        "fontes": [melhor["fonte"]],
        "trechos_usados": [melhor["trecho"]],
    }
