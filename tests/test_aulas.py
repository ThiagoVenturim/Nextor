"""Testes unitarios offline do modulo de gravacao e transcricao de aulas. Sem rede nem microfone real."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ["NEXTOR_VOZ_SAIDA"] = "nenhuma"

from nextor import aulas, companheiro, config, estudos, roteador, servico


class TestFormatacaoETranscricao(unittest.TestCase):
    def test_formatar_segundos(self):
        self.assertEqual(aulas.formatar_segundos(0), "00:00")
        self.assertEqual(aulas.formatar_segundos(45.9), "00:45")
        self.assertEqual(aulas.formatar_segundos(75), "01:15")
        self.assertEqual(aulas.formatar_segundos(3599), "59:59")
        self.assertEqual(aulas.formatar_segundos(3600), "01:00:00")
        self.assertEqual(aulas.formatar_segundos(3665), "01:01:05")

    def test_transcrever_audio_com_fake(self):
        fake_trechos = [
            {"inicio": "00:00", "fim": "00:05", "texto": "Inicio da aula"},
            {"inicio": "00:05", "fim": "00:12", "texto": "Definicao de limites"},
        ]
        res = aulas.transcrever_audio(Path("dummy.wav"), transcritor_fake=lambda p: fake_trechos)
        self.assertEqual(res, fake_trechos)

    def test_transcrever_audio_arquivo_inexistente(self):
        res = aulas.transcrever_audio(Path("arquivo_inexistente_xyz.wav"))
        self.assertEqual(res, [])

    def test_transcrever_audio_sem_modelo_vosk(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            wav_fake = Path(tmpdir) / "teste.wav"
            wav_fake.write_bytes(b"RIFF" + b"\x00" * 40)
            with mock.patch.object(config, "VOSK_MODELO", str(Path(tmpdir) / "modelo_inexistente")):
                res = aulas.transcrever_audio(wav_fake)
                self.assertEqual(len(res), 1)
                self.assertIn("Transcricao local pendente do modelo Vosk", res[0]["texto"])


class BaseAulasTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.tmp.name) / "estudos"
        self.db_path = self.base_dir / "test_aulas.db"

        self.p_dir = mock.patch.object(config, "ESTUDOS_DIR", self.base_dir)
        self.p_db = mock.patch.object(config, "ESTUDOS_DB", self.db_path)
        self.p_edir = mock.patch.object(estudos.config, "ESTUDOS_DIR", self.base_dir)
        self.p_edb = mock.patch.object(estudos.config, "ESTUDOS_DB", self.db_path)
        self.p_sd = mock.patch.object(aulas, "sd", None)

        self.p_dir.start()
        self.p_db.start()
        self.p_edir.start()
        self.p_edb.start()
        self.p_sd.start()

        # Reseta o gravador singleton do modulo
        aulas.gravador._gravando = False
        aulas.gravador._disciplina = ""
        aulas.gravador._frames = []
        companheiro.companheiro.atualizar(atividade="normal", detalhe="")

    def tearDown(self):
        aulas.gravador._gravando = False
        aulas.gravador._disciplina = ""
        aulas.gravador._frames = []
        self.p_sd.stop()
        self.p_edb.stop()
        self.p_edir.stop()
        self.p_db.stop()
        self.p_dir.stop()
        self.tmp.cleanup()


class TestGravadorAulaCiclo(BaseAulasTestCase):
    def test_iniciar_e_parar_gravacao_completa(self):
        # 1. Iniciar gravacao
        res_inicio = aulas.iniciar_gravacao("Calculo 1")
        self.assertTrue(res_inicio["ok"])
        self.assertTrue(res_inicio["gravando"])
        self.assertEqual(res_inicio["disciplina"], "Calculo 1")
        self.assertIn(aulas.AVISO_CONSENTIMENTO, res_inicio["aviso"])

        # Verifica estado interno e indicador visual no companheiro
        status = aulas.status_gravacao()
        self.assertTrue(status["gravando"])
        self.assertEqual(status["disciplina"], "Calculo 1")
        self.assertEqual(companheiro.companheiro.ver()["atividade"], "gravando_aula")

        # 2. Parar gravacao com transcritor simulado
        trechos_simulados = [
            {"inicio": "00:00", "fim": "00:10", "texto": "Bom dia turma, hoje veremos integrais."},
            {"inicio": "00:10", "fim": "00:25", "texto": "A integral definida representa a area sob a curva."},
        ]

        res_fim = aulas.parar_gravacao(
            transcritor_fake=lambda p: trechos_simulados,
            base_dir=self.base_dir,
            caminho_db=self.db_path,
        )

        self.assertTrue(res_fim["ok"])
        self.assertEqual(res_fim["disciplina"], "Calculo 1")
        self.assertFalse(aulas.status_gravacao()["gravando"])
        self.assertEqual(companheiro.companheiro.ver()["atividade"], "normal")

        # Verifica arquivos gerados em disco
        caminho_audio = Path(res_fim["caminho_audio"])
        caminho_txt = Path(res_fim["caminho_transcricao"])
        self.assertTrue(caminho_audio.exists())
        self.assertTrue(caminho_txt.exists())

        # Verifica conteudo do arquivo de transcricao com carimbos e consentimento
        conteudo = caminho_txt.read_text(encoding="utf-8")
        self.assertIn("# Aula de Calculo 1", conteudo)
        self.assertIn(aulas.AVISO_CONSENTIMENTO, conteudo)
        self.assertIn("[00:00 - 00:10] Bom dia turma, hoje veremos integrais.", conteudo)
        self.assertIn("[00:10 - 00:25] A integral definida representa a area sob a curva.", conteudo)

        # 3. Verifica indexacao na biblioteca FTS5
        busca = estudos.buscar_materiais("definida area", disciplina_nome="Calculo 1", caminho_db=self.db_path)
        self.assertEqual(len(busca), 1)
        self.assertIn("Calculo 1", busca[0]["disciplina"])


class TestGravadorValidacoesECorrencia(BaseAulasTestCase):
    def test_recusa_disciplina_vazia(self):
        res = aulas.iniciar_gravacao("   ")
        self.assertFalse(res["ok"])
        self.assertIn("obrigatorio", res["erro"])
        self.assertFalse(aulas.status_gravacao()["gravando"])

    def test_recusa_gravacao_concorrente(self):
        res1 = aulas.iniciar_gravacao("Fisica Geral")
        self.assertTrue(res1["ok"])

        # Tentativa de iniciar outra gravacao enquanto uma esta ativa
        res2 = aulas.iniciar_gravacao("Quimica Organica")
        self.assertFalse(res2["ok"])
        self.assertIn("Ja existe uma gravacao em andamento para Fisica Geral", res2["erro"])

        # Para a gravacao ativa
        res_parar = aulas.parar_gravacao(base_dir=self.base_dir, caminho_db=self.db_path)
        self.assertTrue(res_parar["ok"])

    def test_parar_sem_gravacao_ativa(self):
        res = aulas.parar_gravacao(base_dir=self.base_dir, caminho_db=self.db_path)
        self.assertFalse(res["ok"])
        self.assertIn("Nenhuma gravacao em andamento", res["erro"])

    def test_backend_customizado_executado(self):
        chamado = []
        res = aulas.iniciar_gravacao("Algebra", backend_gravador=lambda: chamado.append(True))
        self.assertTrue(res["ok"])
        self.assertEqual(chamado, [True])
        aulas.parar_gravacao(base_dir=self.base_dir, caminho_db=self.db_path)


class TestAvisoConsentimento(unittest.TestCase):
    def test_presenca_do_aviso_de_consentimento(self):
        self.assertIn("autorizacao previa do professor", aulas.AVISO_CONSENTIMENTO)
        self.assertIn("instituicao de ensino", aulas.AVISO_CONSENTIMENTO)


class TestRoteadorAulas(unittest.TestCase):
    def test_rotear_iniciar_gravacao(self):
        frases = [
            ("gravar aula de Calculo Numerico", "Calculo Numerico"),
            ("grava a aula de Fisica 2", "Fisica 2"),
            ("iniciar gravacao da aula de Algebra Linear", "Algebra Linear"),
            ("gravar aula de Estrutura de Dados", "Estrutura de Dados"),
        ]
        for frase, disc_esperada in frases:
            with self.subTest(frase=frase):
                with mock.patch("nextor.roteador._fazer_estudos_gravar_aula", return_value="Gravacao iniciada.") as m:
                    r = roteador.rotear(frase)
                    self.assertEqual(r["intencao"], "estudos_gravar_aula")
                    self.assertEqual(r["resposta"], "Gravacao iniciada.")
                    m.assert_called_once_with(disc_esperada)

    def test_rotear_parar_gravacao(self):
        frases = [
            "parar a gravacao",
            "para gravacao",
            "encerrar gravacao",
            "terminar gravacao",
        ]
        for frase in frases:
            with self.subTest(frase=frase):
                with mock.patch("nextor.roteador._fazer_estudos_parar_gravacao", return_value="Gravacao encerrada.") as m:
                    r = roteador.rotear(frase)
                    self.assertEqual(r["intencao"], "estudos_parar_gravacao")
                    self.assertEqual(r["resposta"], "Gravacao encerrada.")
                    m.assert_called_once()


class TestServicoAulasEndpoints(BaseAulasTestCase):
    def setUp(self):
        super().setUp()
        self.token_teste = "token-mestre-super-seguro-com-mais-de-24-caracteres"
        self.p_token = mock.patch.object(config, "TOKEN", self.token_teste)
        self.p_token.start()
        self.client = servico.app.test_client()
        self.headers = {"X-Nextor-Token": self.token_teste}

    def tearDown(self):
        self.p_token.stop()
        super().tearDown()

    def test_endpoints_exigem_token(self):
        self.assertEqual(self.client.post("/estudos/aulas/gravar").status_code, 401)
        self.assertEqual(self.client.post("/estudos/aulas/parar").status_code, 401)
        self.assertEqual(self.client.get("/estudos/aulas/status").status_code, 401)

    def test_gravar_sem_disciplina_retorna_400(self):
        r = self.client.post("/estudos/aulas/gravar", json={"disciplina": ""}, headers=self.headers)
        self.assertEqual(r.status_code, 400)
        self.assertIn("disciplina obrigatoria", r.get_json()["erro"])

    def test_ciclo_completo_via_api(self):
        # 1. Iniciar gravacao
        r_ini = self.client.post(
            "/estudos/aulas/gravar",
            json={"disciplina": "Sistemas Operacionais"},
            headers=self.headers,
        )
        self.assertEqual(r_ini.status_code, 200)
        dados_ini = r_ini.get_json()
        self.assertTrue(dados_ini["ok"])
        self.assertTrue(dados_ini["gravando"])
        self.assertIn(aulas.AVISO_CONSENTIMENTO, dados_ini["consentimento"])

        # 2. Checar status
        r_status = self.client.get("/estudos/aulas/status", headers=self.headers)
        self.assertEqual(r_status.status_code, 200)
        dados_st = r_status.get_json()
        self.assertTrue(dados_st["ok"])
        self.assertTrue(dados_st["gravando"])
        self.assertEqual(dados_st["disciplina"], "Sistemas Operacionais")

        # 3. Concorrencia via API retorna 400
        r_conc = self.client.post(
            "/estudos/aulas/gravar",
            json={"disciplina": "Redes"},
            headers=self.headers,
        )
        self.assertEqual(r_conc.status_code, 400)
        self.assertIn("Ja existe uma gravacao em andamento", r_conc.get_json()["erro"])

        # 4. Parar gravacao
        with mock.patch("nextor.aulas.transcrever_audio", return_value=[{"inicio": "00:00", "fim": "00:05", "texto": "Escalonamento de CPU"}]):
            r_parar = self.client.post("/estudos/aulas/parar", headers=self.headers)
        self.assertEqual(r_parar.status_code, 200)
        dados_fim = r_parar.get_json()
        self.assertTrue(dados_fim["ok"])
        self.assertEqual(dados_fim["disciplina"], "Sistemas Operacionais")
        self.assertTrue(Path(dados_fim["caminho_transcricao"]).exists())

        # 5. Parar novamente retorna 400
        r_parar_novamente = self.client.post("/estudos/aulas/parar", headers=self.headers)
        self.assertEqual(r_parar_novamente.status_code, 400)
        self.assertIn("Nenhuma gravacao em andamento", r_parar_novamente.get_json()["erro"])


if __name__ == "__main__":
    unittest.main()
