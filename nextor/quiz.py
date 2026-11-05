"""Modulo de quizzes com repeticao espacada para o modo Estudos."""
import json
import random
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import config, estudos, resumos


def garantir_tabelas_quiz(con) -> None:
    """Garante a criacao das tabelas de quiz e historico de repeticao espacada."""
    with con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS quiz_questoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                disciplina_id INTEGER NOT NULL,
                tipo TEXT NOT NULL,
                pergunta TEXT NOT NULL,
                opcoes_json TEXT NOT NULL,
                resposta_correta TEXT NOT NULL,
                explicacao TEXT NOT NULL,
                fonte TEXT NOT NULL,
                acertos INTEGER DEFAULT 0,
                erros INTEGER DEFAULT 0,
                repeticoes INTEGER DEFAULT 0,
                ultima_revisao TEXT,
                criado_em TEXT NOT NULL,
                FOREIGN KEY (disciplina_id) REFERENCES disciplinas(id) ON DELETE CASCADE
            )
            """
        )


def salvar_questao(
    disciplina_id: int,
    tipo: str,
    pergunta: str,
    opcoes: List[str],
    resposta_correta: str,
    explicacao: str,
    fonte: str,
    caminho_db: Optional[Path] = None,
) -> int:
    con = estudos.conectar_db(caminho_db)
    try:
        garantir_tabelas_quiz(con)
        criado_em = datetime.now().isoformat(timespec="seconds")
        with con:
            cur = con.execute(
                """
                INSERT INTO quiz_questoes (
                    disciplina_id, tipo, pergunta, opcoes_json, resposta_correta,
                    explicacao, fonte, acertos, erros, repeticoes, ultima_revisao, criado_em
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 0, NULL, ?)
                """,
                (
                    disciplina_id,
                    tipo,
                    pergunta.strip(),
                    json.dumps(opcoes, ensure_ascii=False),
                    resposta_correta.strip(),
                    explicacao.strip(),
                    fonte.strip(),
                    criado_em,
                ),
            )
            return cur.lastrowid
    finally:
        con.close()


def obter_questoes_repeticao_espacada(
    disciplina_id: int,
    limite: int = 5,
    caminho_db: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Recupera questoes priorizando questoes com maior taxa de erro ou sem revisao recente."""
    con = estudos.conectar_db(caminho_db)
    try:
        garantir_tabelas_quiz(con)
        cur = con.execute(
            """
            SELECT id, disciplina_id, tipo, pergunta, opcoes_json, resposta_correta,
                   explicacao, fonte, acertos, erros, repeticoes, ultima_revisao, criado_em,
                   (CASE 
                       WHEN repeticoes = 0 THEN 999.0 
                       ELSE (erros * 2.0 / repeticoes) + (julianday('now') - julianday(COALESCE(ultima_revisao, criado_em)))
                    END) AS prioridade
            FROM quiz_questoes
            WHERE disciplina_id = ?
            ORDER BY prioridade DESC, id ASC
            LIMIT ?
            """,
            (disciplina_id, limite),
        )
        resultados = []
        for r in cur.fetchall():
            row = dict(r)
            row["opcoes"] = json.loads(row["opcoes_json"]) if row.get("opcoes_json") else []
            resultados.append(row)
        return resultados
    finally:
        con.close()


def registrar_tentativa(
    questao_id: int,
    resposta_usuario: str,
    caminho_db: Optional[Path] = None,
) -> Dict[str, Any]:
    """Corrige a resposta do usuario, atualiza acertos/erros e carimbo da repeticao espacada."""
    con = estudos.conectar_db(caminho_db)
    try:
        garantir_tabelas_quiz(con)
        cur = con.execute(
            """
            SELECT id, disciplina_id, tipo, pergunta, opcoes_json, resposta_correta,
                   explicacao, fonte, acertos, erros, repeticoes, ultima_revisao
            FROM quiz_questoes
            WHERE id = ?
            """,
            (questao_id,),
        )
        row = cur.fetchone()
        if not row:
            return {"ok": False, "erro": "Questao nao encontrada."}

        q = dict(row)
        opcoes = json.loads(q["opcoes_json"]) if q.get("opcoes_json") else []
        gabarito = q["resposta_correta"].strip().upper()
        resposta_limpa = resposta_usuario.strip().upper()

        # Identifica se acertou por letra (A, B, C, D) ou por texto
        correto = False
        if resposta_limpa == gabarito:
            correto = True
        elif gabarito in ("VERDADEIRO", "FALSO") and resposta_limpa in ("V", "VERDADEIRO", "VERDADE") and gabarito == "VERDADEIRO":
            correto = True
        elif gabarito in ("VERDADEIRO", "FALSO") and resposta_limpa in ("F", "FALSO") and gabarito == "FALSO":
            correto = True
        else:
            # Checa se o usuario falou o texto correspondente a opcao correta
            for op in opcoes:
                op_upper = op.strip().upper()
                if op_upper.startswith(f"{gabarito})") or op_upper.startswith(f"{gabarito}:"):
                    texto_opcao = re.sub(rf"^{gabarito}[\):]\s*", "", op_upper).strip()
                    if resposta_limpa == texto_opcao or resposta_limpa in texto_opcao:
                        correto = True
                        break

        novo_acertos = q["acertos"] + (1 if correto else 0)
        novo_erros = q["erros"] + (0 if correto else 1)
        novo_repeticoes = q["repeticoes"] + 1
        agora = datetime.now().isoformat(timespec="seconds")

        with con:
            con.execute(
                """
                UPDATE quiz_questoes
                SET acertos = ?, erros = ?, repeticoes = ?, ultima_revisao = ?
                WHERE id = ?
                """,
                (novo_acertos, novo_erros, novo_repeticoes, agora, questao_id),
            )

        # Monta explicacao falada
        if correto:
            msg = f"Correto! A resposta e {q['resposta_correta']}. {q['explicacao']} (Fonte: {q['fonte']})"
        else:
            msg = f"Incorreto. A resposta certa e {q['resposta_correta']}. {q['explicacao']} (Fonte: {q['fonte']})"

        return {
            "ok": True,
            "correto": correto,
            "questao_id": questao_id,
            "resposta_usuario": resposta_usuario,
            "resposta_correta": q["resposta_correta"],
            "explicacao": q["explicacao"],
            "fonte": q["fonte"],
            "acertos": novo_acertos,
            "erros": novo_erros,
            "repeticoes": novo_repeticoes,
            "mensagem": msg,
        }
    finally:
        con.close()


def obter_historico_quiz(
    disciplina_nome: str = "",
    caminho_db: Optional[Path] = None,
) -> Dict[str, Any]:
    """Retorna estatisticas de desempenho e questoes para revisao."""
    con = estudos.conectar_db(caminho_db)
    try:
        garantir_tabelas_quiz(con)
        filtros = []
        params = []
        disc_nome_resolvido = "Todas"

        if disciplina_nome.strip():
            disc = estudos.obter_disciplina(disciplina_nome, caminho_db=caminho_db)
            if not disc:
                return {
                    "ok": False,
                    "erro": f"Disciplina '{disciplina_nome}' nao encontrada.",
                    "total_questoes": 0,
                    "acertos": 0,
                    "erros": 0,
                    "questoes": [],
                }
            filtros.append("q.disciplina_id = ?")
            params.append(disc["id"])
            disc_nome_resolvido = disc["nome"]

        where_clause = f"WHERE {' AND '.join(filtros)}" if filtros else ""

        cur = con.execute(
            f"""
            SELECT q.id, q.disciplina_id, d.nome AS disciplina_nome, q.tipo, q.pergunta,
                   q.opcoes_json, q.resposta_correta, q.explicacao, q.fonte,
                   q.acertos, q.erros, q.repeticoes, q.ultima_revisao
            FROM quiz_questoes q
            JOIN disciplinas d ON d.id = q.disciplina_id
            {where_clause}
            ORDER BY q.erros DESC, q.repeticoes ASC
            """,
            params,
        )
        questoes = []
        total_acertos = 0
        total_erros = 0
        for r in cur.fetchall():
            row = dict(r)
            row["opcoes"] = json.loads(row["opcoes_json"]) if row.get("opcoes_json") else []
            total_acertos += row["acertos"]
            total_erros += row["erros"]
            questoes.append(row)

        total_respostas = total_acertos + total_erros
        taxa_acerto = round(total_acertos / total_respostas, 2) if total_respostas > 0 else 0.0

        return {
            "ok": True,
            "disciplina": disc_nome_resolvido,
            "total_questoes": len(questoes),
            "total_respostas": total_respostas,
            "acertos": total_acertos,
            "erros": total_erros,
            "taxa_acerto": taxa_acerto,
            "questoes": questoes,
        }
    finally:
        con.close()


def _derivar_questoes_deterministicas(
    disciplina_id: int,
    disciplina_nome: str,
    caminho_db: Optional[Path] = None,
    quantidade: int = 3,
) -> List[Dict[str, Any]]:
    """Gera questoes de multipla escolha e verdadeiro/falso deterministicamente a partir de flashcards e materias."""
    questoes = []
    materiais = estudos.listar_materiais(disciplina_nome, caminho_db=caminho_db)
    if not materiais:
        return []

    # Coleta trechos e flashcards
    flashcards_coletados = []
    topicos_coletados = []

    con = estudos.conectar_db(caminho_db)
    try:
        cur = con.execute(
            "SELECT id, titulo, conteudo FROM materiais WHERE disciplina_id = ? ORDER BY criado_em DESC LIMIT 5",
            (disciplina_id,),
        )
        for mat in cur.fetchall():
            res = resumos.gerar_resumo_e_flashcards(
                conteudo=mat["conteudo"],
                titulo=mat["titulo"],
                disciplina=disciplina_nome,
                gerar_cards=True,
            )
            for fc in res.get("flashcards", []):
                flashcards_coletados.append(fc)
            for tp in res.get("topicos", []):
                topicos_coletados.append(tp)
    finally:
        con.close()

    # 1. Gera questoes a partir de flashcards
    if flashcards_coletados:
        random.seed(42)  # determinismo para testes
        for idx, card in enumerate(flashcards_coletados[:quantidade]):
            pergunta = card.get("pergunta", "")
            resposta_certa = card.get("resposta", "")
            fonte = card.get("fonte", disciplina_nome)

            if idx % 2 == 0:
                # Questao de multipla escolha
                outros = [c.get("resposta", "") for c in flashcards_coletados if c.get("resposta") != resposta_certa]
                distratores = outros[:3]
                while len(distratores) < 3:
                    distratores.append(f"Conceito alternativo {len(distratores) + 1}")

                opcoes = [
                    f"A) {resposta_certa}",
                    f"B) {distratores[0]}",
                    f"C) {distratores[1]}",
                    f"D) {distratores[2]}",
                ]
                q_id = salvar_questao(
                    disciplina_id=disciplina_id,
                    tipo="multipla_escolha",
                    pergunta=pergunta,
                    opcoes=opcoes,
                    resposta_correta="A",
                    explicacao=f"A resposta correta e '{resposta_certa}'.",
                    fonte=fonte,
                    caminho_db=caminho_db,
                )
                questoes.append({
                    "id": q_id,
                    "disciplina_id": disciplina_id,
                    "tipo": "multipla_escolha",
                    "pergunta": pergunta,
                    "opcoes": opcoes,
                    "resposta_correta": "A",
                    "explicacao": f"A resposta correta e '{resposta_certa}'.",
                    "fonte": fonte,
                })
            else:
                # Questao de Verdadeiro ou Falso
                afirmacao = f"{pergunta.replace('?', '')}: {resposta_certa}."
                q_id = salvar_questao(
                    disciplina_id=disciplina_id,
                    tipo="verdadeiro_falso",
                    pergunta=afirmacao,
                    opcoes=["Verdadeiro", "Falso"],
                    resposta_correta="Verdadeiro",
                    explicacao=f"A afirmacao e verdadeira conforme estudado em {fonte}.",
                    fonte=fonte,
                    caminho_db=caminho_db,
                )
                questoes.append({
                    "id": q_id,
                    "disciplina_id": disciplina_id,
                    "tipo": "verdadeiro_falso",
                    "pergunta": afirmacao,
                    "opcoes": ["Verdadeiro", "Falso"],
                    "resposta_correta": "Verdadeiro",
                    "explicacao": f"A afirmacao e verdadeira conforme estudado em {fonte}.",
                    "fonte": fonte,
                })

    elif topicos_coletados:
        for idx, tp in enumerate(topicos_coletados[:quantidade]):
            ponto = tp.get("ponto", "")
            fonte = tp.get("fonte", disciplina_nome)
            afirmacao = f"Em {disciplina_nome}, o seguinte conceito e valido: {ponto}."
            q_id = salvar_questao(
                disciplina_id=disciplina_id,
                tipo="verdadeiro_falso",
                pergunta=afirmacao,
                opcoes=["Verdadeiro", "Falso"],
                resposta_correta="Verdadeiro",
                explicacao=f"Correto conforme registrado na fonte {fonte}.",
                fonte=fonte,
                caminho_db=caminho_db,
            )
            questoes.append({
                "id": q_id,
                "disciplina_id": disciplina_id,
                "tipo": "verdadeiro_falso",
                "pergunta": afirmacao,
                "opcoes": ["Verdadeiro", "Falso"],
                "resposta_correta": "Verdadeiro",
                "explicacao": f"Correto conforme registrado na fonte {fonte}.",
                "fonte": fonte,
            })

    return questoes


def gerar_questoes_com_cerebro(
    disciplina_id: int,
    disciplina_nome: str,
    conteudo_amostra: str,
    quantidade: int = 3,
    cerebro_fn: Optional[Callable[[str, str], str]] = None,
    caminho_db: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Gera questoes via LLM (Ollama/Claude) com injeção de mock para testes."""
    sistema = (
        "Voce e o assistente de quiz academico Nextor. "
        "Responda ESTRITAMENTE em formato JSON contendo uma lista de questoes sem markdown. "
        "Estrutura de cada questao: "
        "{\"tipo\": \"multipla_escolha\"|\"verdadeiro_falso\", \"pergunta\": \"...\", "
        "\"opcoes\": [\"A) ...\", \"B) ...\", \"C) ...\", \"D) ...\"] ou [\"Verdadeiro\", \"Falso\"], "
        "\"resposta_correta\": \"A\"|\"Verdadeiro\", \"explicacao\": \"...\", \"fonte\": \"...\"}"
    )
    mensagem = (
        f"Gere {quantidade} questoes academicas (misturando multipla escolha e verdadeiro/falso) "
        f"para a disciplina '{disciplina_nome}' baseando-se no conteudo abaixo:\n\n"
        f"{conteudo_amostra[:3000]}"
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
            resposta_texto = cerebro.responder(mensagem, sistema=sistema, tokens=700)
        except Exception:
            resposta_texto = ""

    questoes_geradas = []
    if resposta_texto:
        limpo = re.sub(r"^```(?:json)?\s*", "", resposta_texto.strip(), flags=re.IGNORECASE)
        limpo = re.sub(r"\s*```$", "", limpo).strip()
        try:
            lista = json.loads(limpo)
            if isinstance(lista, list):
                for item in lista:
                    if isinstance(item, dict) and "pergunta" in item and "resposta_correta" in item:
                        tipo = item.get("tipo") or "multipla_escolha"
                        opcoes = item.get("opcoes") or ["A) Correta", "B) Incorreta"]
                        resp_certa = item.get("resposta_correta")
                        exp = item.get("explicacao") or f"Resposta correta: {resp_certa}"
                        fonte = item.get("fonte") or disciplina_nome
                        q_id = salvar_questao(
                            disciplina_id=disciplina_id,
                            tipo=tipo,
                            pergunta=item["pergunta"],
                            opcoes=opcoes,
                            resposta_correta=resp_certa,
                            explicacao=exp,
                            fonte=fonte,
                            caminho_db=caminho_db,
                        )
                        questoes_geradas.append({
                            "id": q_id,
                            "disciplina_id": disciplina_id,
                            "tipo": tipo,
                            "pergunta": item["pergunta"],
                            "opcoes": opcoes,
                            "resposta_correta": resp_certa,
                            "explicacao": exp,
                            "fonte": fonte,
                        })
        except Exception:
            pass

    return questoes_geradas


def obter_ou_gerar_questoes_quiz(
    disciplina_nome: str,
    quantidade: int = 3,
    cerebro_fn: Optional[Callable[[str, str], str]] = None,
    caminho_db: Optional[Path] = None,
) -> Dict[str, Any]:
    """Obtem questoes existentes priorizando repeticao espacada ou gera novas com fallback."""
    disc = estudos.obter_disciplina(disciplina_nome, caminho_db=caminho_db)
    if not disc:
        return {
            "ok": False,
            "erro": f"Disciplina '{disciplina_nome}' nao existe.",
            "questoes": [],
        }

    disc_id = disc["id"]
    existentes = obter_questoes_repeticao_espacada(disc_id, limite=quantidade, caminho_db=caminho_db)
    if len(existentes) >= quantidade:
        return {
            "ok": True,
            "disciplina": disc["nome"],
            "questoes": existentes[:quantidade],
        }

    # Se precisa de mais questoes, tenta gerar
    qtd_faltante = quantidade - len(existentes)
    novas = []

    # Tenta com cerebro se houver material
    con = estudos.conectar_db(caminho_db)
    conteudo_amostra = ""
    try:
        cur = con.execute("SELECT conteudo FROM materiais WHERE disciplina_id = ? LIMIT 1", (disc_id,))
        row = cur.fetchone()
        if row:
            conteudo_amostra = row["conteudo"]
    finally:
        con.close()

    if conteudo_amostra and cerebro_fn is not None:
        novas = gerar_questoes_com_cerebro(
            disciplina_id=disc_id,
            disciplina_nome=disc["nome"],
            conteudo_amostra=conteudo_amostra,
            quantidade=qtd_faltante,
            cerebro_fn=cerebro_fn,
            caminho_db=caminho_db,
        )

    # Fallback deterministico se cerebro nao gerou o suficiente
    if len(novas) < qtd_faltante:
        deterministicas = _derivar_questoes_deterministicas(
            disciplina_id=disc_id,
            disciplina_nome=disc["nome"],
            caminho_db=caminho_db,
            quantidade=qtd_faltante - len(novas),
        )
        novas.extend(deterministicas)

    todas = existentes + novas
    return {
        "ok": True,
        "disciplina": disc["nome"],
        "questoes": todas[:quantidade],
    }


class GerenciadorSessaoQuiz:
    """Gerencia a sessao ativa do quiz interativo por voz."""

    def __init__(self):
        self._lock = threading.Lock()
        self._sessao: Optional[Dict[str, Any]] = None

    def iniciar(self, disciplina_nome: str, questao: Dict[str, Any]) -> str:
        with self._lock:
            self._sessao = {
                "disciplina": disciplina_nome,
                "questao": questao,
                "iniciado_em": datetime.now().isoformat(),
            }

        # Formata enunciado para reproducao falada
        opcoes = questao.get("opcoes", [])
        linhas = [f"Quiz de {disciplina_nome}: {questao['pergunta']}"]
        if questao.get("tipo") == "multipla_escolha":
            for op in opcoes:
                linhas.append(op)
            linhas.append("Qual e a sua resposta: A, B, C ou D?")
        else:
            linhas.append("Verdadeiro ou Falso?")

        return "\n".join(linhas)

    def obter_ativa(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._sessao

    def responder(self, resposta_usuario: str, caminho_db: Optional[Path] = None) -> Optional[Dict[str, Any]]:
        with self._lock:
            if not self._sessao:
                return None
            questao = self._sessao["questao"]
            self._sessao = None

        return registrar_tentativa(questao["id"], resposta_usuario, caminho_db=caminho_db)

    def limpar(self) -> None:
        with self._lock:
            self._sessao = None


sessao_quiz = GerenciadorSessaoQuiz()


def quiz_do_dia(caminho_db: Optional[Path] = None) -> Dict[str, Any]:
    """Seleciona a disciplina com mais revisoes pendentes ou a primeira cadastrada para a rotina diária."""
    disciplinas = estudos.listar_disciplinas(caminho_db=caminho_db)
    if not disciplinas:
        return {
            "ok": False,
            "erro": "Nenhuma disciplina cadastrada para o quiz do dia.",
            "aviso": "Voce ainda nao cadastrou nenhuma disciplina para o quiz do dia.",
        }

    # Procura disciplina com questoes pendentes
    con = estudos.conectar_db(caminho_db)
    disciplina_escolhida = disciplinas[0]["nome"]
    try:
        garantir_tabelas_quiz(con)
        cur = con.execute(
            """
            SELECT d.nome, COUNT(q.id) as total, SUM(q.erros) as erros
            FROM quiz_questoes q
            JOIN disciplinas d ON d.id = q.disciplina_id
            GROUP BY d.nome
            ORDER BY erros DESC, total DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
        if row and row["nome"]:
            disciplina_escolhida = row["nome"]
    finally:
        con.close()

    res = obter_ou_gerar_questoes_quiz(disciplina_escolhida, quantidade=1, caminho_db=caminho_db)
    if not res.get("ok") or not res.get("questoes"):
        return {
            "ok": False,
            "erro": f"Nao ha questoes disponiveis para {disciplina_escolhida}.",
            "aviso": f"Nao consegui preparar questoes para o quiz de {disciplina_escolhida}.",
        }

    questao = res["questoes"][0]
    enunciado = sessao_quiz.iniciar(disciplina_escolhida, questao)
    return {
        "ok": True,
        "disciplina": disciplina_escolhida,
        "questao": questao,
        "aviso": f"Quiz do dia! {enunciado}",
    }


def iniciar_quiz_por_voz(
    disciplina_nome: str,
    caminho_db: Optional[Path] = None,
    cerebro_fn: Optional[Callable[[str, str], str]] = None,
) -> str:
    """Inicia uma rodada de quiz por voz para a disciplina especificada."""
    res = obter_ou_gerar_questoes_quiz(
        disciplina_nome=disciplina_nome,
        quantidade=1,
        cerebro_fn=cerebro_fn,
        caminho_db=caminho_db,
    )
    if not res.get("ok") or not res.get("questoes"):
        return res.get("erro") or f"Nao encontrei questoes ou materiais para {disciplina_nome}."

    questao = res["questoes"][0]
    return sessao_quiz.iniciar(disciplina_nome, questao)
