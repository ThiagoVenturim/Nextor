"""Testes unitarios offline do modulo de perguntas sobre a materia com citacao de fontes (Issue #5)."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ["NEXTOR_VOZ_SAIDA"] = "nenhuma"

from nextor import config, estudos, qa_estudos, roteador, servico


class BaseQAEstudosTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.tmp.name) / "estudos"
        self.db_path = self.base_dir / "test_qa.db"
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

        # Cria disciplina de teste
        estudos.criar_disciplina("Calculo", base_dir=self.base_dir, caminho_db=self.db_path)

        # 1. Aula com marcadores de timestamp
        self.origem_aula = Path(self.tmp.name) / "aula_calculo_transcricao.txt"
        self.origem_aula.write_text(
            "# Aula de Calculo\n"
            "Data: 01/11/2026\n\n"
            "## Transcricao\n"
            "[00:00 - 00:15] Introducao ao estudo de limites e continuidade de funcoes reais.\n"
            "[00:15 - 00:30] O Teorema do Confronto ou Teorema do Sanduiche permite calcular limites complexos delimitando a funcao.\n"
            "[00:30 - 00:45] A derivada de uma funcao no ponto mede a taxa instantanea de variacao da variavel dependente.",
            encoding="utf-8",
        )
        estudos.importar_material(
            "Calculo",
            self.origem_aula,
            titulo="Aula Calculo - Limites e Derivadas",
            tipo="aula",
            base_dir=self.base_dir,
            caminho_db=self.db_path,
        )

        # 2. Capitulo em texto plano com paragrafos
        self.origem_cap = Path(self.tmp.name) / "integrais.txt"
        self.origem_cap.write_text(
            "Capitulo sobre integracao definida e indefinida.\n"
            "O Teorema Fundamental do Calculo estabelece a conexao fundamental e elegante entre derivacao e integracao.\n"
            "A integral definida de Riemann calcula o acumulo de grandezas e a area exata sob curvas continuas.\n"
            "Metodos de integracao por partes e por substituicao simplificam o calculo de integrais complexas.",
            encoding="utf-8",
        )
        estudos.importar_material(
            "Calculo",
            self.origem_cap,
            titulo="Capitulo de Integracao",
            tipo="txt",
            base_dir=self.base_dir,
            caminho_db=self.db_path,
        )

    def tearDown(self):
        self.p_cerebro.stop()
        self.p_env_importar.stop()
        self.p_token.stop()
        self.p_edb.stop()
        self.p_edir.stop()
        self.p_db.stop()
        self.p_dir.stop()
        self.tmp.cleanup()


class TestExtracaoTermosEContexto(BaseQAEstudosTestCase):
    def test_extrair_termos_busca(self):
        frase = "O que o meu material diz sobre o Teorema do Confronto em Calculo?"
        termos = qa_estudos.extrair_termos_busca(frase)
        self.assertIn("teorema", termos)
        self.assertIn("confronto", termos)
        self.assertNotIn("o", termos)
        self.assertNotIn("meu", termos)
        self.assertNotIn("material", termos)
        self.assertNotIn("sobre", termos)

    def test_extrair_trecho_timestamped_aula(self):
        trechos = qa_estudos.buscar_contexto_relevante(
            pergunta="O que e Teorema do Confronto?",
            disciplina_nome="Calculo",
            caminho_db=self.db_path,
        )
        self.assertTrue(len(trechos) >= 1)
        melhor = trechos[0]
        self.assertIn("Teorema do Confronto", melhor["trecho"])
        self.assertIn("Aula Calculo - Limites e Derivadas [00:15 - 00:30]", melhor["fonte"])

    def test_extrair_trecho_secao_texto(self):
        trechos = qa_estudos.buscar_contexto_relevante(
            pergunta="Como funciona a integral de Riemann?",
            disciplina_nome="Calculo",
            caminho_db=self.db_path,
        )
        self.assertTrue(len(trechos) >= 1)
        melhor = trechos[0]
        self.assertIn("Riemann", melhor["trecho"])
        self.assertIn("Capitulo de Integracao", melhor["fonte"])
        self.assertIn("secao", melhor["fonte"])

    def test_buscar_contexto_relevante_disciplina_inexistente(self):
        trechos = qa_estudos.buscar_contexto_relevante(
            pergunta="O que e limite?",
            disciplina_nome="FisicaQuantica",
            caminho_db=self.db_path,
        )
        self.assertEqual(trechos, [])


class TestRespostasDuasCamadasEFallback(BaseQAEstudosTestCase):
    def test_resposta_duas_camadas_com_mock_llm(self):
        fake_json = json.dumps({
            "encontrado": True,
            "resposta_fala": "Segundo a aula de Calculo: O Teorema do Confronto delimita funcoes para calcular limites.",
            "resposta_detalhada": (
                "O Teorema do Confronto estabelece que se uma funcao f(x) estiver delimitada por g(x) e h(x), "
                "e ambas tenderem ao mesmo limite L, entao f(x) tambem converge para L.\n\n"
                "Citacao: 'O Teorema do Confronto ou Teorema do Sanduiche permite calcular limites complexos delimitando a funcao.' "
                "(Fonte: Aula Calculo - Limites e Derivadas [00:15 - 00:30])"
            ),
            "fontes": ["Aula Calculo - Limites e Derivadas [00:15 - 00:30]"],
        })

        res = qa_estudos.responder_com_material(
            pergunta="O que diz o Teorema do Confronto?",
            disciplina_nome="Calculo",
            cerebro_fn=lambda msg, sist: fake_json,
            caminho_db=self.db_path,
        )

        self.assertTrue(res["ok"])
        self.assertTrue(res["encontrado"])
        self.assertEqual(res["disciplina"], "Calculo")
        # Camada falada concisa para o Nest
        self.assertIn("Segundo a aula de Calculo", res["resposta_fala"])
        # Camada detalhada com explicacao e citacoes literais
        self.assertIn("Teorema do Sanduiche", res["resposta_detalhada"])
        self.assertIn("Aula Calculo - Limites e Derivadas [00:15 - 00:30]", res["fontes"])
        self.assertTrue(len(res["trechos_usados"]) >= 1)

    def test_resposta_com_bloco_markdown_json(self):
        fake_bloco = """```json
        {
            "encontrado": true,
            "resposta_fala": "Segundo o material: A derivada e a taxa instantanea de variacao.",
            "resposta_detalhada": "Explicacao completa.",
            "fontes": ["Aula Calculo [00:30 - 00:45]"]
        }
        ```"""

        res = qa_estudos.responder_com_material(
            pergunta="O que e derivada?",
            disciplina_nome="Calculo",
            cerebro_fn=lambda msg, sist: fake_bloco,
            caminho_db=self.db_path,
        )
        self.assertTrue(res["ok"])
        self.assertTrue(res["encontrado"])
        self.assertIn("taxa instantanea", res["resposta_fala"])

    def test_fallback_deterministico_em_falha_do_cerebro(self):
        def cerebro_offline(msg, sist):
            raise RuntimeError("Ollama indisponivel")

        res = qa_estudos.responder_com_material(
            pergunta="Explica a integral de Riemann",
            disciplina_nome="Calculo",
            cerebro_fn=cerebro_offline,
            caminho_db=self.db_path,
        )

        self.assertTrue(res["ok"])
        self.assertTrue(res["encontrado"])
        # Fallback monta resposta curta citando fonte
        self.assertTrue(res["resposta_fala"].startswith("Segundo Capitulo de Integracao"))
        self.assertIn("Riemann", res["resposta_fala"])
        # Fallback detalhado cita o texto literal entre aspas
        self.assertIn("Com base no seu material", res["resposta_detalhada"])
        self.assertIn('"', res["resposta_detalhada"])
        self.assertTrue(len(res["fontes"]) >= 1)


class TestRegraAntiAlucinacao(BaseQAEstudosTestCase):
    def test_pergunta_nao_coberta_pelo_material_recusa_explicitamente(self):
        # Pergunta sobre assunto que nao existe no material de Calculo
        res = qa_estudos.responder_com_material(
            pergunta="Qual e a velocidade de escape de um buraco negro supermassivo?",
            disciplina_nome="Calculo",
            caminho_db=self.db_path,
        )

        self.assertTrue(res["ok"])
        self.assertFalse(res["encontrado"])
        # Afirmacao explicita de que a informacao nao consta no material
        self.assertIn("Essa informacao nao consta no seu material de Calculo.", res["resposta_fala"])
        self.assertIn("Nao invento informacoes que nao constem no seu material.", res["resposta_detalhada"])
        self.assertEqual(res["fontes"], [])
        self.assertEqual(res["trechos_usados"], [])

    def test_recusa_declarada_pelo_modelo_llm(self):
        fake_recusa = json.dumps({
            "encontrado": False,
            "resposta_fala": "",
            "resposta_detalhada": "",
            "fontes": [],
        })

        res = qa_estudos.responder_com_material(
            pergunta="Quem descobriu o Teorema do Confronto?",
            disciplina_nome="Calculo",
            cerebro_fn=lambda msg, sist: fake_recusa,
            caminho_db=self.db_path,
        )

        self.assertTrue(res["ok"])
        self.assertFalse(res["encontrado"])
        self.assertIn("Essa informacao nao consta no seu material de Calculo.", res["resposta_fala"])


class TestRoteadorQAEstudos(BaseQAEstudosTestCase):
    def test_rotear_perguntas_estudos(self):
        casos = [
            ("o que o meu material diz sobre limites", "limites"),
            ("o que meu material diz sobre o Teorema do Confronto", "o Teorema do Confronto"),
            ("O que e integral segundo o meu material?", "O que e integral"),
            ("Explica regra da cadeia pelo meu material", "Explica regra da cadeia"),
            ("o que tem no meu material sobre derivadas", "o que tem no sobre derivadas"),
            ("como funciona o Teorema Fundamental segundo meu material", "como funciona o Teorema Fundamental"),
        ]

        for frase, termo_esperado in casos:
            with self.subTest(frase=frase):
                with mock.patch("nextor.roteador._fazer_estudos_perguntar", return_value="Resposta do material.") as m:
                    r = roteador.rotear(frase)
                    self.assertEqual(r["intencao"], "estudos_perguntar")
                    self.assertEqual(r["resposta"], "Resposta do material.")
                    m.assert_called_once()

    def test_rotear_executa_resposta_real_sem_alucinar(self):
        # Pergunta coberta
        r_coberta = roteador.rotear("O que o meu material diz sobre o Teorema do Confronto em Calculo")
        self.assertEqual(r_coberta["intencao"], "estudos_perguntar")
        self.assertIn("Teorema do Confronto", r_coberta["resposta"])

        # Pergunta nao coberta
        r_ausente = roteador.rotear("O que o meu material diz sobre fotossintese")
        self.assertEqual(r_ausente["intencao"], "estudos_perguntar")
        self.assertIn("Essa informacao nao consta no seu material", r_ausente["resposta"])


class TestServicoQAEndpoints(BaseQAEstudosTestCase):
    def test_endpoint_exige_token(self):
        r = self.client.post("/estudos/perguntar", json={"pergunta": "O que e limite?"})
        self.assertEqual(r.status_code, 401)

    def test_pergunta_obrigatoria(self):
        r = self.client.post("/estudos/perguntar", json={"pergunta": "   "}, headers=self.headers)
        self.assertEqual(r.status_code, 400)
        self.assertIn("obrigatorio", r.get_json()["erro"])

    def test_perguntar_sucesso_com_resposta_duas_camadas(self):
        r = self.client.post(
            "/estudos/perguntar",
            json={"pergunta": "O que e a derivada?", "disciplina": "Calculo"},
            headers=self.headers,
        )
        self.assertEqual(r.status_code, 200)
        dados = r.get_json()
        self.assertTrue(dados["ok"])
        self.assertTrue(dados["encontrado"])
        self.assertEqual(dados["disciplina"], "Calculo")
        self.assertIn("Segundo", dados["resposta_fala"])
        self.assertIn("taxa instantanea", dados["resposta_fala"])
        self.assertIn("Com base no seu material", dados["resposta_detalhada"])
        self.assertTrue(len(dados["fontes"]) >= 1)

    def test_perguntar_assunto_nao_coberto_recusa_sem_alucinar(self):
        r = self.client.post(
            "/estudos/perguntar",
            json={"pergunta": "Qual e a formula da relatividade geral?", "disciplina": "Calculo"},
            headers=self.headers,
        )
        self.assertEqual(r.status_code, 200)
        dados = r.get_json()
        self.assertTrue(dados["ok"])
        self.assertFalse(dados["encontrado"])
        self.assertIn("Essa informacao nao consta no seu material de Calculo.", dados["resposta_fala"])
        self.assertEqual(dados["fontes"], [])


if __name__ == "__main__":
    unittest.main()
