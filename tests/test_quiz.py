"""Testes unitarios offline do modulo de quiz com repeticao espacada. Sem rede nem microfone real."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ["NEXTOR_VOZ_SAIDA"] = "nenhuma"

from nextor import config, estudos, quiz, roteador, servico


class BaseQuizTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.tmp.name) / "estudos"
        self.db_path = self.base_dir / "test_quiz.db"
        self.token_teste = "token-mestre-super-seguro-com-mais-de-24-caracteres"

        self.p_dir = mock.patch.object(config, "ESTUDOS_DIR", self.base_dir)
        self.p_db = mock.patch.object(config, "ESTUDOS_DB", self.db_path)
        self.p_edir = mock.patch.object(estudos.config, "ESTUDOS_DIR", self.base_dir)
        self.p_edb = mock.patch.object(estudos.config, "ESTUDOS_DB", self.db_path)
        self.p_token = mock.patch.object(config, "TOKEN", self.token_teste)
        self.p_env_importar = mock.patch.dict(os.environ, {"NEXTOR_ESTUDOS_IMPORTAR_DE": str(self.tmp.name)})
        self.p_cerebro = mock.patch("nextor.cerebro.responder", side_effect=RuntimeError("offline"))

        self.p_dir.start()
        self.p_db.start()
        self.p_edir.start()
        self.p_edb.start()
        self.p_token.start()
        self.p_env_importar.start()
        self.p_cerebro.start()

        self.client = servico.app.test_client()
        self.headers = {"X-Nextor-Token": self.token_teste}

        quiz.sessao_quiz.limpar()

        # Cria disciplina base para testes
        res_disc = estudos.criar_disciplina("Calculo", base_dir=self.base_dir, caminho_db=self.db_path)
        self.disc_id = res_disc["id"]

        # Adiciona material de estudo
        self.origem_mat = Path(self.tmp.name) / "limites.txt"
        self.origem_mat.write_text(
            "Capitulo sobre limites e continuidade.\n"
            "O limite descreve o comportamento de uma funcao proximo a um ponto.\n"
            "Uma funcao e continua se o limite for igual ao valor da funcao no ponto.\n"
            "O Teorema do Confronto permite limitar funcoes complexas por duas conhecidas.",
            encoding="utf-8",
        )
        estudos.importar_material(
            "Calculo",
            self.origem_mat,
            titulo="Limites e Continuidade",
            tipo="txt",
            base_dir=self.base_dir,
            caminho_db=self.db_path,
        )

    def tearDown(self):
        quiz.sessao_quiz.limpar()
        self.p_cerebro.stop()
        self.p_env_importar.stop()
        self.p_token.stop()
        self.p_edb.stop()
        self.p_edir.stop()
        self.p_db.stop()
        self.p_dir.stop()
        self.tmp.cleanup()


class TestPersistenciaEOrdenacaoSpacedRepetition(BaseQuizTestCase):
    def test_salvar_e_recuperar_questao(self):
        opcoes = [
            "A) Comportamento proximo a um ponto",
            "B) Valor exato no infinito",
            "C) Area sob a curva",
            "D) Derivada segunda",
        ]
        q_id = quiz.salvar_questao(
            disciplina_id=self.disc_id,
            tipo="multipla_escolha",
            pergunta="O que descreve um limite?",
            opcoes=opcoes,
            resposta_correta="A",
            explicacao="O limite analisa a aproximacao em torno do ponto.",
            fonte="Limites e Continuidade",
            caminho_db=self.db_path,
        )
        self.assertTrue(q_id > 0)

        questoes = quiz.obter_questoes_repeticao_espacada(self.disc_id, limite=10, caminho_db=self.db_path)
        self.assertEqual(len(questoes), 1)
        q = questoes[0]
        self.assertEqual(q["id"], q_id)
        self.assertEqual(q["pergunta"], "O que descreve um limite?")
        self.assertEqual(q["resposta_correta"], "A")
        self.assertEqual(q["opcoes"], opcoes)
        self.assertEqual(q["acertos"], 0)
        self.assertEqual(q["erros"], 0)
        self.assertEqual(q["repeticoes"], 0)

    def test_ordenacao_prioridade_repeticao_espacada(self):
        # Questao 1: Nunca revisada (repeticoes=0) -> prioridade maxima (999.0)
        q1_id = quiz.salvar_questao(
            disciplina_id=self.disc_id,
            tipo="multipla_escolha",
            pergunta="Questao nunca revisada",
            opcoes=["A) 1", "B) 2"],
            resposta_correta="A",
            explicacao="Exp 1",
            fonte="Fonte 1",
            caminho_db=self.db_path,
        )

        # Questao 2: Com alta taxa de erros (3 repeticoes, 3 erros)
        q2_id = quiz.salvar_questao(
            disciplina_id=self.disc_id,
            tipo="multipla_escolha",
            pergunta="Questao dificil com erros",
            opcoes=["A) 1", "B) 2"],
            resposta_correta="A",
            explicacao="Exp 2",
            fonte="Fonte 2",
            caminho_db=self.db_path,
        )
        # Simula 3 erros
        quiz.registrar_tentativa(q2_id, "B", caminho_db=self.db_path)
        quiz.registrar_tentativa(q2_id, "B", caminho_db=self.db_path)
        quiz.registrar_tentativa(q2_id, "B", caminho_db=self.db_path)

        # Questao 3: Dominada com 100% de acertos (5 repeticoes, 5 acertos)
        q3_id = quiz.salvar_questao(
            disciplina_id=self.disc_id,
            tipo="multipla_escolha",
            pergunta="Questao facil dominada",
            opcoes=["A) 1", "B) 2"],
            resposta_correta="A",
            explicacao="Exp 3",
            fonte="Fonte 3",
            caminho_db=self.db_path,
        )
        for _ in range(5):
            quiz.registrar_tentativa(q3_id, "A", caminho_db=self.db_path)

        questoes = quiz.obter_questoes_repeticao_espacada(self.disc_id, limite=10, caminho_db=self.db_path)
        ids_ordenados = [q["id"] for q in questoes]

        # Prioridade esperada: Nunca revisada (q1) > Erros frequentes (q2) > Dominada (q3)
        self.assertEqual(ids_ordenados, [q1_id, q2_id, q3_id])


class TestCorrecaoTentativas(BaseQuizTestCase):
    def test_correcao_multipla_escolha_letra_e_texto(self):
        opcoes = [
            "A) Taxa instantanea de variacao",
            "B) Area sob a reta",
            "C) Raiz quadrada",
        ]
        q_id = quiz.salvar_questao(
            disciplina_id=self.disc_id,
            tipo="multipla_escolha",
            pergunta="O que e derivada?",
            opcoes=opcoes,
            resposta_correta="A",
            explicacao="A derivada mede a inclinacao instantanea.",
            fonte="Capitulo Derivadas",
            caminho_db=self.db_path,
        )

        # Acerto por letra maiuscula
        r1 = quiz.registrar_tentativa(q_id, "A", caminho_db=self.db_path)
        self.assertTrue(r1["ok"])
        self.assertTrue(r1["correto"])
        self.assertEqual(r1["acertos"], 1)
        self.assertEqual(r1["erros"], 0)
        self.assertEqual(r1["repeticoes"], 1)
        self.assertIn("Correto!", r1["mensagem"])
        self.assertIn("(Fonte: Capitulo Derivadas)", r1["mensagem"])

        # Acerto por letra minuscula
        r2 = quiz.registrar_tentativa(q_id, "a", caminho_db=self.db_path)
        self.assertTrue(r2["correto"])
        self.assertEqual(r2["acertos"], 2)

        # Acerto pelo texto da alternativa
        r3 = quiz.registrar_tentativa(q_id, "taxa instantanea de variacao", caminho_db=self.db_path)
        self.assertTrue(r3["correto"])
        self.assertEqual(r3["acertos"], 3)

        # Erro por outra letra
        r4 = quiz.registrar_tentativa(q_id, "B", caminho_db=self.db_path)
        self.assertFalse(r4["correto"])
        self.assertEqual(r4["erros"], 1)
        self.assertEqual(r4["repeticoes"], 4)
        self.assertIn("Incorreto.", r4["mensagem"])
        self.assertIn("A resposta certa e A", r4["mensagem"])

    def test_correcao_verdadeiro_ou_falso(self):
        q_vf = quiz.salvar_questao(
            disciplina_id=self.disc_id,
            tipo="verdadeiro_falso",
            pergunta="Toda funcao derivavel e continua.",
            opcoes=["Verdadeiro", "Falso"],
            resposta_correta="Verdadeiro",
            explicacao="Diferenciabilidade implica continuidade.",
            fonte="Teoremas de Continuidade",
            caminho_db=self.db_path,
        )

        # Acerto com 'V' e 'Verdadeiro'
        res_v = quiz.registrar_tentativa(q_vf, "V", caminho_db=self.db_path)
        self.assertTrue(res_v["correto"])

        res_verdadeiro = quiz.registrar_tentativa(q_vf, "Verdadeiro", caminho_db=self.db_path)
        self.assertTrue(res_verdadeiro["correto"])

        # Erro com 'F'
        res_f = quiz.registrar_tentativa(q_vf, "F", caminho_db=self.db_path)
        self.assertFalse(res_f["correto"])
        self.assertEqual(res_f["erros"], 1)

    def test_questao_inexistente_retorna_erro(self):
        res = quiz.registrar_tentativa(99999, "A", caminho_db=self.db_path)
        self.assertFalse(res["ok"])
        self.assertIn("Questao nao encontrada", res["erro"])


class TestGeracaoQuestoes(BaseQuizTestCase):
    def test_geracao_com_mock_cerebro_json(self):
        fake_json = """
        [
            {
                "tipo": "multipla_escolha",
                "pergunta": "Qual o limite de sin(x)/x quando x tende a 0?",
                "opcoes": ["A) 1", "B) 0", "C) Infinito", "D) Inexistente"],
                "resposta_correta": "A",
                "explicacao": "E o limite fundamental trigonometrico.",
                "fonte": "Limites e Continuidade"
            },
            {
                "tipo": "verdadeiro_falso",
                "pergunta": "O Teorema do Confronto tambem e conhecido como Teorema do Sanduiche.",
                "opcoes": ["Verdadeiro", "Falso"],
                "resposta_correta": "Verdadeiro",
                "explicacao": "Sao sinonimos tradicionais.",
                "fonte": "Limites e Continuidade"
            }
        ]
        """
        questoes = quiz.gerar_questoes_com_cerebro(
            disciplina_id=self.disc_id,
            disciplina_nome="Calculo",
            conteudo_amostra="Texto sobre limites.",
            quantidade=2,
            cerebro_fn=lambda msg, sist: fake_json,
            caminho_db=self.db_path,
        )
        self.assertEqual(len(questoes), 2)
        self.assertEqual(questoes[0]["resposta_correta"], "A")
        self.assertEqual(questoes[1]["resposta_correta"], "Verdadeiro")

    def test_geracao_com_markdown_json(self):
        fake_bloco = """```json
        [
            {
                "tipo": "multipla_escolha",
                "pergunta": "Pergunta em bloco markdown",
                "opcoes": ["A) Sim", "B) Nao"],
                "resposta_correta": "A",
                "explicacao": "Explicacao bloco",
                "fonte": "Material"
            }
        ]
        ```"""
        questoes = quiz.gerar_questoes_com_cerebro(
            disciplina_id=self.disc_id,
            disciplina_nome="Calculo",
            conteudo_amostra="Texto.",
            quantidade=1,
            cerebro_fn=lambda msg, sist: fake_bloco,
            caminho_db=self.db_path,
        )
        self.assertEqual(len(questoes), 1)
        self.assertEqual(questoes[0]["pergunta"], "Pergunta em bloco markdown")

    def test_fallback_deterministico_offline(self):
        # Fallback deriva questoes a partir dos flashcards e topicos dos materiais
        questoes = quiz._derivar_questoes_deterministicas(
            disciplina_id=self.disc_id,
            disciplina_nome="Calculo",
            caminho_db=self.db_path,
            quantidade=2,
        )
        self.assertTrue(len(questoes) >= 1)
        for q in questoes:
            self.assertTrue(len(q["pergunta"]) > 0)
            self.assertTrue(len(q["opcoes"]) >= 2)
            self.assertTrue(len(q["fonte"]) > 0)
            self.assertIn("Limites", q["fonte"])

    def test_obter_ou_gerar_questoes_prioriza_existentes(self):
        # Salva 3 questoes previas
        for i in range(3):
            quiz.salvar_questao(
                disciplina_id=self.disc_id,
                tipo="multipla_escolha",
                pergunta=f"Pergunta previa {i}",
                opcoes=["A) 1", "B) 2"],
                resposta_correta="A",
                explicacao=f"Exp {i}",
                fonte="Fonte",
                caminho_db=self.db_path,
            )

        res = quiz.obter_ou_gerar_questoes_quiz("Calculo", quantidade=3, caminho_db=self.db_path)
        self.assertTrue(res["ok"])
        self.assertEqual(len(res["questoes"]), 3)
        self.assertEqual(res["questoes"][0]["pergunta"], "Pergunta previa 0")


class TestHistoricoEEstatisticas(BaseQuizTestCase):
    def test_estatisticas_desempenho(self):
        q1 = quiz.salvar_questao(
            self.disc_id, "multipla_escolha", "P1", ["A) Sim"], "A", "E1", "F1", self.db_path
        )
        q2 = quiz.salvar_questao(
            self.disc_id, "multipla_escolha", "P2", ["A) Sim"], "A", "E2", "F2", self.db_path
        )

        quiz.registrar_tentativa(q1, "A", self.db_path)  # Acerto
        quiz.registrar_tentativa(q1, "A", self.db_path)  # Acerto
        quiz.registrar_tentativa(q2, "B", self.db_path)  # Erro

        hist = quiz.obter_historico_quiz("Calculo", caminho_db=self.db_path)
        self.assertTrue(hist["ok"])
        self.assertEqual(hist["total_questoes"], 2)
        self.assertEqual(hist["total_respostas"], 3)
        self.assertEqual(hist["acertos"], 2)
        self.assertEqual(hist["erros"], 1)
        self.assertEqual(hist["taxa_acerto"], 0.67)

    def test_historico_disciplina_inexistente(self):
        hist = quiz.obter_historico_quiz("Inexistente", caminho_db=self.db_path)
        self.assertFalse(hist["ok"])
        self.assertEqual(hist["total_questoes"], 0)


class TestSessaoAtivaEQuizDoDia(BaseQuizTestCase):
    def test_ciclo_sessao_interativa(self):
        questao = {
            "id": 1,
            "tipo": "multipla_escolha",
            "pergunta": "Qual a derivada de x^2?",
            "opcoes": ["A) 2x", "B) x", "C) 1", "D) 0"],
            "resposta_correta": "A",
            "explicacao": "Pela regra do tombo.",
            "fonte": "Calculo 1",
        }
        enunciado = quiz.sessao_quiz.iniciar("Calculo", questao)
        self.assertIn("Quiz de Calculo", enunciado)
        self.assertIn("A) 2x", enunciado)
        self.assertIn("Qual e a sua resposta: A, B, C ou D?", enunciado)

        # Sessao esta ativa
        ativa = quiz.sessao_quiz.obter_ativa()
        self.assertIsNotNone(ativa)
        self.assertEqual(ativa["disciplina"], "Calculo")

        # Mock de persistencia para registrar tentativa
        with mock.patch("nextor.quiz.registrar_tentativa", return_value={"ok": True, "correto": True, "mensagem": "Correto!"}) as m:
            res_resp = quiz.sessao_quiz.responder("A")
            self.assertTrue(res_resp["correto"])
            m.assert_called_once_with(1, "A", caminho_db=None)

        # Sessao foi limpa apos responder
        self.assertIsNone(quiz.sessao_quiz.obter_ativa())

    def test_quiz_do_dia(self):
        res = quiz.quiz_do_dia(caminho_db=self.db_path)
        self.assertTrue(res["ok"])
        self.assertEqual(res["disciplina"], "Calculo")
        self.assertIn("Quiz do dia!", res["aviso"])
        self.assertIsNotNone(quiz.sessao_quiz.obter_ativa())

    def test_quiz_do_dia_sem_disciplinas(self):
        # Limpa disciplinas
        con = estudos.conectar_db(self.db_path)
        with con:
            con.execute("DELETE FROM disciplinas")
        con.close()

        res = quiz.quiz_do_dia(caminho_db=self.db_path)
        self.assertFalse(res["ok"])
        self.assertIn("nao cadastrou nenhuma disciplina", res["aviso"])

    def test_iniciar_quiz_por_voz(self):
        fala = quiz.iniciar_quiz_por_voz("Calculo", caminho_db=self.db_path)
        self.assertIn("Quiz de Calculo", fala)
        self.assertIsNotNone(quiz.sessao_quiz.obter_ativa())


class TestRoteadorQuiz(BaseQuizTestCase):
    def test_rotear_quiz_do_dia(self):
        frases = [
            "quiz do dia",
            "quiz de hoje",
            "fazer o quiz do dia",
            "iniciar quiz do dia",
            "quiz diario",
        ]
        for frase in frases:
            with self.subTest(frase=frase):
                with mock.patch("nextor.roteador._fazer_estudos_quiz_do_dia", return_value="Quiz do dia iniciado.") as m:
                    r = roteador.rotear(frase)
                    self.assertEqual(r["intencao"], "estudos_quiz_do_dia")
                    self.assertEqual(r["resposta"], "Quiz do dia iniciado.")
                    m.assert_called_once()

    def test_rotear_iniciar_quiz(self):
        frases = [
            ("quiz de Calculo", "Calculo"),
            ("fazer quiz de Algebra", "Algebra"),
            ("quero um quiz de Fisica", "Fisica"),
            ("iniciar o quiz da materia Quimica", "materia Quimica"),
        ]
        for frase, disc_esperada in frases:
            with self.subTest(frase=frase):
                with mock.patch("nextor.roteador._fazer_estudos_iniciar_quiz", return_value="Enunciado da questao.") as m:
                    r = roteador.rotear(frase)
                    self.assertEqual(r["intencao"], "estudos_quiz")
                    self.assertEqual(r["resposta"], "Enunciado da questao.")
                    m.assert_called_once_with(disc_esperada)

    def test_rotear_resposta_com_sessao_ativa(self):
        questao = {
            "id": 42,
            "tipo": "multipla_escolha",
            "pergunta": "P?",
            "opcoes": ["A) 1", "B) 2"],
            "resposta_correta": "A",
            "explicacao": "Exp",
            "fonte": "Fonte",
        }
        quiz.sessao_quiz.iniciar("Calculo", questao)

        respostas = ["A", "letra B", "opcao c", "D", "verdadeiro", "falso", "v", "f"]
        for resp in respostas:
            with self.subTest(resp=resp):
                # Recarrega a sessao para cada subteste
                quiz.sessao_quiz.iniciar("Calculo", questao)
                with mock.patch("nextor.quiz.sessao_quiz.responder", return_value={"ok": True, "mensagem": "Correto!"}) as m:
                    r = roteador.rotear(resp)
                    self.assertEqual(r["intencao"], "estudos_quiz_resposta")
                    self.assertEqual(r["resposta"], "Correto!")
                    m.assert_called_once()

    def test_rotear_resposta_sem_sessao_ativa(self):
        # Sem sessao ativa, a letra 'A' nao e interceptada como resposta de quiz
        quiz.sessao_quiz.limpar()
        r = roteador.rotear("A")
        self.assertNotEqual(r["intencao"], "estudos_quiz_resposta")


class TestServicoQuizEndpoints(BaseQuizTestCase):
    def test_endpoints_exigem_token(self):
        self.assertEqual(self.client.post("/estudos/quiz/gerar").status_code, 401)
        self.assertEqual(self.client.post("/estudos/quiz/responder").status_code, 401)
        self.assertEqual(self.client.get("/estudos/quiz/historico").status_code, 401)

    def test_endpoint_gerar_questoes(self):
        # Sem disciplina
        r_sem = self.client.post("/estudos/quiz/gerar", json={"disciplina": ""}, headers=self.headers)
        self.assertEqual(r_sem.status_code, 400)

        # Disciplina inexistente
        r_inex = self.client.post("/estudos/quiz/gerar", json={"disciplina": "Inexistente"}, headers=self.headers)
        self.assertEqual(r_inex.status_code, 404)

        # Sucesso
        r_ok = self.client.post("/estudos/quiz/gerar", json={"disciplina": "Calculo", "quantidade": 2}, headers=self.headers)
        self.assertEqual(r_ok.status_code, 200)
        dados = r_ok.get_json()
        self.assertTrue(dados["ok"])
        self.assertTrue(len(dados["questoes"]) >= 1)

    def test_endpoint_responder_questao(self):
        q_id = quiz.salvar_questao(
            self.disc_id, "multipla_escolha", "P", ["A) Sim", "B) Nao"], "A", "Exp", "Fonte", self.db_path
        )

        # Sem questao_id ou sem resposta
        self.assertEqual(self.client.post("/estudos/quiz/responder", json={}, headers=self.headers).status_code, 400)
        self.assertEqual(self.client.post("/estudos/quiz/responder", json={"questao_id": "invalido", "resposta": "A"}, headers=self.headers).status_code, 400)

        # Questao inexistente
        r_inex = self.client.post("/estudos/quiz/responder", json={"questao_id": 99999, "resposta": "A"}, headers=self.headers)
        self.assertEqual(r_inex.status_code, 404)

        # Sucesso
        r_ok = self.client.post("/estudos/quiz/responder", json={"questao_id": q_id, "resposta": "A"}, headers=self.headers)
        self.assertEqual(r_ok.status_code, 200)
        dados = r_ok.get_json()
        self.assertTrue(dados["ok"])
        self.assertTrue(dados["correto"])
        self.assertEqual(dados["acertos"], 1)

    def test_endpoint_historico(self):
        r = self.client.get("/estudos/quiz/historico?disciplina=Calculo", headers=self.headers)
        self.assertEqual(r.status_code, 200)
        dados = r.get_json()
        self.assertTrue(dados["ok"])
        self.assertEqual(dados["disciplina"], "Calculo")
        self.assertIn("taxa_acerto", dados)


if __name__ == "__main__":
    unittest.main()
