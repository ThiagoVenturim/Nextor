"""Testes unitarios offline do modulo de resumos e flashcards para Anki. Sem rede nem microfone real."""
import csv
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ["NEXTOR_VOZ_SAIDA"] = "nenhuma"

from nextor import config, estudos, resumos, roteador, servico


class BaseResumosTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.tmp.name) / "estudos"
        self.db_path = self.base_dir / "test_resumos.db"
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

        # Cria materiais de teste
        self.origem_cap1 = Path(self.tmp.name) / "capitulo_1.txt"
        self.origem_cap1.write_text(
            "Capitulo 1: Limites e Continuidade.\n"
            "O conceito fundamental de limites descreve o comportamento de uma funcao proximo a um ponto.\n"
            "A continuidade garante que pequenas variacoes na entrada gerem pequenas variacoes na saida.\n"
            "As propriedades operatorias dos limites facilitam o calculo de formas indeterminadas.",
            encoding="utf-8",
        )
        estudos.importar_material(
            "Calculo",
            self.origem_cap1,
            titulo="Capitulo 1 - Limites e Continuidade",
            tipo="txt",
            base_dir=self.base_dir,
            caminho_db=self.db_path,
        )

        self.origem_aula = Path(self.tmp.name) / "aula_20261101_100000_transcricao.txt"
        self.origem_aula.write_text(
            "# Aula de Calculo\n"
            "Data: 01/11/2026\n"
            "Aviso de consentimento: autorizacao previa do professor.\n\n"
            "## Transcricao\n"
            "[00:00 - 00:15] Bom dia a todos, hoje abordaremos o Teorema Fundamental do Calculo.\n"
            "[00:15 - 00:35] A integral de Riemann formaliza a nocao de area sob uma curva.\n"
            "[00:35 - 00:50] A derivacao e a integracao sao operacoes inversas entre si.",
            encoding="utf-8",
        )
        estudos.importar_material(
            "Calculo",
            self.origem_aula,
            titulo="Aula Calculo - 20261101_100000",
            tipo="aula",
            base_dir=self.base_dir,
            caminho_db=self.db_path,
        )

        self.origem_cap2 = Path(self.tmp.name) / "capitulo_2.txt"
        self.origem_cap2.write_text(
            "Capitulo 2: Derivadas e Regra da Cadeia.\n"
            "A derivada representa a taxa de variacao instantanea de uma grandeza em relacao a outra.\n"
            "A regra da cadeia permite derivar funcoes compostas com multiplas camadas.",
            encoding="utf-8",
        )
        estudos.importar_material(
            "Calculo",
            self.origem_cap2,
            titulo="Capitulo 2 - Derivadas e Regra da Cadeia",
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


class TestLocalizacaoMaterial(BaseResumosTestCase):
    def test_localizar_ultima_aula(self):
        # Alvo vazio, 'aula' ou 'ultima aula' deve encontrar a aula gravada
        mat_vazio = resumos.localizar_material_para_resumo("Calculo", alvo="", caminho_db=self.db_path)
        self.assertIsNotNone(mat_vazio)
        self.assertIn("Aula Calculo", mat_vazio["titulo"])

        mat_ultima = resumos.localizar_material_para_resumo("Calculo", alvo="ultima aula", caminho_db=self.db_path)
        self.assertIsNotNone(mat_ultima)
        self.assertEqual(mat_ultima["id"], mat_vazio["id"])

        mat_aula = resumos.localizar_material_para_resumo("Calculo", alvo="aula", caminho_db=self.db_path)
        self.assertIsNotNone(mat_aula)
        self.assertEqual(mat_aula["id"], mat_vazio["id"])

    def test_localizar_por_capitulo(self):
        mat = resumos.localizar_material_para_resumo("Calculo", alvo="capitulo 1", caminho_db=self.db_path)
        self.assertIsNotNone(mat)
        self.assertEqual(mat["titulo"], "Capitulo 1 - Limites e Continuidade")

    def test_localizar_por_titulo_direto(self):
        mat = resumos.localizar_material_para_resumo("Calculo", alvo="Regra da Cadeia", caminho_db=self.db_path)
        self.assertIsNotNone(mat)
        self.assertEqual(mat["titulo"], "Capitulo 2 - Derivadas e Regra da Cadeia")

    def test_localizar_por_fts(self):
        # 'Riemann' existe apenas no texto interno da transcricao da aula
        mat = resumos.localizar_material_para_resumo("Calculo", alvo="Riemann", caminho_db=self.db_path)
        self.assertIsNotNone(mat)
        self.assertIn("Aula Calculo", mat["titulo"])

    def test_localizar_disciplina_inexistente(self):
        mat = resumos.localizar_material_para_resumo("FisicaQuantica", alvo="aula", caminho_db=self.db_path)
        self.assertIsNone(mat)

    def test_localizar_material_inexistente(self):
        mat = resumos.localizar_material_para_resumo("Calculo", alvo="termo_completamente_inexistente_xyz", caminho_db=self.db_path)
        self.assertIsNone(mat)


class TestGeracaoResumoEFlashcards(unittest.TestCase):
    def test_gerar_resumo_com_fake_cerebro_json(self):
        conteudo = "Texto de teste sobre derivadas."
        titulo = "Aula Derivadas"
        disciplina = "Calculo"

        fake_resposta = """
        {
            "resumo_geral": "Sintese sobre derivadas e aplicacoes.",
            "topicos": [
                {"ponto": "Definicao geometrica da derivada", "fonte": "Aula Derivadas [00:05]"}
            ],
            "flashcards": [
                {
                    "pergunta": "O que representa a derivada geometricamente?",
                    "resposta": "A inclinacao da reta tangente.",
                    "fonte": "Aula Derivadas [00:05]",
                    "tag": "estudos::calculo"
                }
            ]
        }
        """

        res = resumos.gerar_resumo_e_flashcards(
            conteudo=conteudo,
            titulo=titulo,
            disciplina=disciplina,
            cerebro_fn=lambda msg, sist: fake_resposta,
            gerar_cards=True,
        )

        self.assertEqual(res["resumo_geral"], "Sintese sobre derivadas e aplicacoes.")
        self.assertEqual(len(res["topicos"]), 1)
        self.assertEqual(res["topicos"][0]["ponto"], "Definicao geometrica da derivada")
        self.assertEqual(len(res["flashcards"]), 1)
        self.assertEqual(res["flashcards"][0]["pergunta"], "O que representa a derivada geometricamente?")
        self.assertEqual(res["flashcards"][0]["fonte"], "Aula Derivadas [00:05]")

    def test_gerar_resumo_com_markdown_json_bloco(self):
        conteudo = "Texto de teste."
        fake_resposta = """```json
        {
            "resumo_geral": "Resumo limpo de bloco markdown.",
            "topicos": [{"ponto": "Topico 1", "fonte": "Fonte 1"}],
            "flashcards": [{"pergunta": "P1", "resposta": "R1", "fonte": "Fonte 1", "tag": "tag1"}]
        }
        ```"""

        res = resumos.gerar_resumo_e_flashcards(
            conteudo=conteudo,
            titulo="Material 1",
            disciplina="Calculo",
            cerebro_fn=lambda msg, sist: fake_resposta,
            gerar_cards=True,
        )

        self.assertEqual(res["resumo_geral"], "Resumo limpo de bloco markdown.")
        self.assertEqual(len(res["topicos"]), 1)
        self.assertEqual(len(res["flashcards"]), 1)

    def test_gerar_resumo_fallback_deterministico_em_falha_do_cerebro(self):
        conteudo = (
            "[00:00 - 00:10] Conceito inicial da aula de integrais.\n"
            "[00:10 - 00:20] A integral calcula areas acumuladas sob curvas.\n"
            "[00:20 - 00:35] O teorema fundamental unifica derivadas e integrais."
        )

        def cerebro_quebrado(msg, sist):
            raise RuntimeError("Cerebro offline")

        res = resumos.gerar_resumo_e_flashcards(
            conteudo=conteudo,
            titulo="Aula 1",
            disciplina="Calculo Diferencial",
            cerebro_fn=cerebro_quebrado,
            gerar_cards=True,
        )

        self.assertTrue(len(res["topicos"]) >= 2)
        self.assertTrue(len(res["flashcards"]) >= 2)
        # Verifica presenca de fontes reais em cada topico e card
        for topico in res["topicos"]:
            self.assertIn("Aula 1", topico["fonte"])
            self.assertTrue(len(topico["ponto"]) > 0)
        for card in res["flashcards"]:
            self.assertIn("Aula 1", card["fonte"])
            self.assertEqual(card["tag"], "estudos::calculo_diferencial")

    def test_gerar_resumo_sem_cards(self):
        conteudo = "Primeiro paragrafo de estudo com mais de duzentos caracteres para garantir o tamanho minimo necessario do bloco heuristico de extracao durante os testes sem inteligencia artificial."
        res = resumos.gerar_resumo_e_flashcards(
            conteudo=conteudo,
            titulo="Material",
            disciplina="Calculo",
            cerebro_fn=lambda msg, sist: "",
            gerar_cards=False,
        )
        self.assertTrue(len(res["topicos"]) >= 1)
        self.assertEqual(res["flashcards"], [])

    def test_gerar_resumo_conteudo_vazio(self):
        res = resumos.gerar_resumo_e_flashcards(
            conteudo="   ",
            titulo="Material",
            disciplina="Calculo",
        )
        self.assertIn("Nenhum conteudo disponivel", res["resumo_geral"])
        self.assertEqual(res["topicos"], [])
        self.assertEqual(res["flashcards"], [])


class TestExportacaoAnki(unittest.TestCase):
    def test_exportar_flashcards_csv(self):
        cards = [
            {
                "pergunta": "O que e limite?",
                "resposta": "Comportamento da funcao proximo a um ponto.",
                "fonte": "Capitulo 1 [00:10]",
                "tag": "estudos::calculo",
            },
            {
                "pergunta": "O que e derivada com virgula, teste?",
                "resposta": "Taxa instantanea.",
                "fonte": "Capitulo 2",
                "tag": "estudos::calculo",
            },
        ]
        csv_texto = resumos.exportar_flashcards_anki(cards, formato="csv")
        self.assertIn("#separator:Comma", csv_texto)
        self.assertIn("#html:false", csv_texto)
        self.assertIn("#tags column:4", csv_texto)

        linhas = [l for l in csv_texto.strip().splitlines() if not l.startswith("#")]
        self.assertEqual(len(linhas), 2)
        # Parse CSV para checar integridade dos 4 campos
        reader = csv.reader(linhas)
        linhas_parsed = list(reader)
        self.assertEqual(len(linhas_parsed), 2)
        self.assertEqual(linhas_parsed[0][0], "O que e limite?")
        self.assertEqual(linhas_parsed[0][1], "Comportamento da funcao proximo a um ponto.")
        self.assertEqual(linhas_parsed[0][2], "Capitulo 1 [00:10]")
        self.assertEqual(linhas_parsed[0][3], "estudos::calculo")

    def test_exportar_flashcards_tsv(self):
        cards = [
            {
                "pergunta": "Pergunta 1",
                "resposta": "Resposta 1",
                "fonte": "Fonte 1",
                "tag": "tag1",
            }
        ]
        tsv_texto = resumos.exportar_flashcards_anki(cards, formato="tsv")
        self.assertIn("#separator:Tab", tsv_texto)
        self.assertIn("#tags column:4", tsv_texto)
        linhas = [l for l in tsv_texto.strip().splitlines() if not l.startswith("#")]
        self.assertEqual(len(linhas), 1)
        partes = linhas[0].split("\t")
        self.assertEqual(partes, ["Pergunta 1", "Resposta 1", "Fonte 1", "tag1"])

    def test_salvar_flashcards_disco(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            cards = [
                {"pergunta": "P", "resposta": "R", "fonte": "F", "tag": "T"}
            ]
            arquivo_salvo = resumos.salvar_flashcards_disco(
                disciplina_nome="Algebra",
                titulo_material="Capitulo 1 Matrizes",
                flashcards=cards,
                base_dir=base,
                formato="csv",
            )
            self.assertTrue(arquivo_salvo.exists())
            self.assertTrue(arquivo_salvo.name.endswith(".csv"))
            conteudo = arquivo_salvo.read_text(encoding="utf-8")
            self.assertIn("#separator:Comma", conteudo)
            self.assertIn("P,R,F,T", conteudo)


class TestResumirEstudosFluxoCompleto(BaseResumosTestCase):
    def test_resumir_estudos_sucesso(self):
        res = resumos.resumir_estudos(
            disciplina_nome="Calculo",
            alvo="capitulo 1",
            caminho_db=self.db_path,
            base_dir=self.base_dir,
            gerar_cards=True,
            formato_exportacao="csv",
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["disciplina"], "Calculo")
        self.assertEqual(res["titulo"], "Capitulo 1 - Limites e Continuidade")
        self.assertTrue(len(res["topicos"]) >= 1)
        self.assertTrue(len(res["flashcards"]) >= 1)
        self.assertTrue(Path(res["arquivo_flashcards"]).exists())
        self.assertIn("Fonte:", res["aviso"])
        self.assertIn("flashcards para o Anki", res["aviso"])

    def test_resumir_estudos_material_inexistente(self):
        res = resumos.resumir_estudos(
            disciplina_nome="Calculo",
            alvo="fantasma",
            caminho_db=self.db_path,
            base_dir=self.base_dir,
        )
        self.assertFalse(res["ok"])
        self.assertIn("Nao encontrei nenhum material", res["erro"])


class TestRoteadorResumosEFlashcards(unittest.TestCase):
    def test_rotear_flashcards(self):
        frases = [
            ("flashcards de Calculo 1", "Calculo 1"),
            ("gerar flashcards de Algebra", "Algebra"),
            ("criar flashcards da disciplina Fisica", "disciplina Fisica"),
            ("fazer flashcards em Quimica", "Quimica"),
        ]
        for frase, disc_esperada in frases:
            with self.subTest(frase=frase):
                with mock.patch("nextor.roteador._fazer_estudos_resumo", return_value="Flashcards gerados.") as m:
                    r = roteador.rotear(frase)
                    self.assertEqual(r["intencao"], "estudos_flashcards")
                    self.assertEqual(r["resposta"], "Flashcards gerados.")
                    m.assert_called_once_with(disc_esperada, alvo="", gerar_cards=True)

    def test_rotear_resumo_aula(self):
        frases = [
            ("resumir a ultima aula de Calculo", "Calculo"),
            ("resume aula de Fisica", "Fisica"),
            ("resumo a aula da materia Quimica", "materia Quimica"),
        ]
        for frase, disc_esperada in frases:
            with self.subTest(frase=frase):
                with mock.patch("nextor.roteador._fazer_estudos_resumo", return_value="Resumo da aula.") as m:
                    r = roteador.rotear(frase)
                    self.assertEqual(r["intencao"], "estudos_resumo")
                    self.assertEqual(r["resposta"], "Resumo da aula.")
                    m.assert_called_once_with(disc_esperada, alvo="ultima aula", gerar_cards=True)

    def test_rotear_resumo_capitulo(self):
        frases = [
            ("resumir o capitulo 1 de Calculo", "capitulo 1", "Calculo"),
            ("resume capitulo 3 em Algebra", "capitulo 3", "Algebra"),
            ("resumo modulo 2 da disciplina Fisica", "modulo 2", "disciplina Fisica"),
        ]
        for frase, alvo_esperado, disc_esperada in frases:
            with self.subTest(frase=frase):
                with mock.patch("nextor.roteador._fazer_estudos_resumo", return_value="Resumo do capitulo.") as m:
                    r = roteador.rotear(frase)
                    self.assertEqual(r["intencao"], "estudos_resumo")
                    self.assertEqual(r["resposta"], "Resumo do capitulo.")
                    m.assert_called_once_with(disc_esperada, alvo=alvo_esperado, gerar_cards=True)

    def test_rotear_resumo_disciplina(self):
        frases = [
            ("resumir a disciplina de Historia", "Historia"),
            ("resume a materia de Matematica", "Matematica"),
        ]
        for frase, disc_esperada in frases:
            with self.subTest(frase=frase):
                with mock.patch("nextor.roteador._fazer_estudos_resumo", return_value="Resumo geral.") as m:
                    r = roteador.rotear(frase)
                    self.assertEqual(r["intencao"], "estudos_resumo")
                    self.assertEqual(r["resposta"], "Resumo geral.")
                    m.assert_called_once_with(disc_esperada, alvo="", gerar_cards=True)


class TestServicoResumoEndpoints(BaseResumosTestCase):
    def test_endpoints_exigem_token(self):
        self.assertEqual(self.client.post("/estudos/resumo").status_code, 401)
        self.assertEqual(self.client.get("/estudos/flashcards/exportar").status_code, 401)
        self.assertEqual(self.client.post("/estudos/flashcards/exportar").status_code, 401)

    def test_resumo_endpoint_validacoes(self):
        # Sem disciplina
        r_sem_disc = self.client.post(
            "/estudos/resumo",
            json={"disciplina": ""},
            headers=self.headers,
        )
        self.assertEqual(r_sem_disc.status_code, 400)
        self.assertIn("obrigatorio", r_sem_disc.get_json()["erro"])

        # Disciplina inexistente
        r_disc_inexistente = self.client.post(
            "/estudos/resumo",
            json={"disciplina": "Inexistente"},
            headers=self.headers,
        )
        self.assertEqual(r_disc_inexistente.status_code, 404)

    def test_resumo_endpoint_sucesso(self):
        r = self.client.post(
            "/estudos/resumo",
            json={"disciplina": "Calculo", "alvo": "capitulo 1", "formato": "csv"},
            headers=self.headers,
        )
        self.assertEqual(r.status_code, 200)
        dados = r.get_json()
        self.assertTrue(dados["ok"])
        self.assertEqual(dados["disciplina"], "Calculo")
        self.assertEqual(dados["titulo"], "Capitulo 1 - Limites e Continuidade")
        self.assertTrue(len(dados["topicos"]) >= 1)
        self.assertTrue(len(dados["flashcards"]) >= 1)
        self.assertTrue(Path(dados["arquivo_flashcards"]).exists())

    def test_flashcards_exportar_endpoint_csv(self):
        r = self.client.get(
            "/estudos/flashcards/exportar?disciplina=Calculo&alvo=capitulo 1&formato=csv",
            headers=self.headers,
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r.headers.get("Content-Type", ""))
        self.assertIn('attachment; filename="flashcards_calculo.csv"', r.headers.get("Content-Disposition", ""))
        texto = r.data.decode("utf-8")
        self.assertIn("#separator:Comma", texto)
        self.assertIn("#tags column:4", texto)
        self.assertIn("estudos::calculo", texto)

    def test_flashcards_exportar_endpoint_tsv(self):
        r = self.client.get(
            "/estudos/flashcards/exportar?disciplina=Calculo&alvo=capitulo 2&formato=tsv",
            headers=self.headers,
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/tab-separated-values", r.headers.get("Content-Type", ""))
        self.assertIn('attachment; filename="flashcards_calculo.tsv"', r.headers.get("Content-Disposition", ""))
        texto = r.data.decode("utf-8")
        self.assertIn("#separator:Tab", texto)
        self.assertIn("estudos::calculo", texto)

    def test_flashcards_exportar_sem_disciplina_ou_inexistente(self):
        r_sem = self.client.get("/estudos/flashcards/exportar", headers=self.headers)
        self.assertEqual(r_sem.status_code, 400)

        r_inex = self.client.get("/estudos/flashcards/exportar?disciplina=NaoExiste", headers=self.headers)
        self.assertEqual(r_inex.status_code, 404)


if __name__ == "__main__":
    unittest.main()
