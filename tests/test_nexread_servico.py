"""Testes unitarios offline dos endpoints HTTP, PWA e extensao do NexRead no servico (Issue #55)."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

os.environ["NEXTOR_VOZ_SAIDA"] = "nenhuma"

from nextor import config, servico


class TestNexReadServico(unittest.TestCase):
    def setUp(self):
        self.token_mestre = "token-teste-mestre-nexread-123456"
        self.client = servico.app.test_client()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_dir.name)
        self.db_nexread = self.base_path / "test_nexread.db"
        self.estudos_dir = self.base_path / "estudos"
        self.estudos_db = self.estudos_dir / "indice_estudos.db"

        self.patch_nr_db = mock.patch.object(config, "NEXREAD_DB", self.db_nexread)
        self.patch_est_dir = mock.patch.object(config, "ESTUDOS_DIR", self.estudos_dir)
        self.patch_est_db = mock.patch.object(config, "ESTUDOS_DB", self.estudos_db)
        self.patch_nr_db.start()
        self.patch_est_dir.start()
        self.patch_est_db.start()

    def tearDown(self):
        self.patch_nr_db.stop()
        self.patch_est_dir.stop()
        self.patch_est_db.stop()
        self.temp_dir.cleanup()

    def test_pwa_e_extensao_servidos_corretamente(self):
        resp_pwa = self.client.get("/nexread")
        self.assertEqual(resp_pwa.status_code, 200)
        self.assertIn(b"NexRead", resp_pwa.data)
        resp_pwa.close()

        resp_manifest = self.client.get("/nexread/manifest.webmanifest")
        self.assertEqual(resp_manifest.status_code, 200)
        resp_manifest.close()

        resp_ext = self.client.get("/nexread/extensao/manifest.json")
        self.assertEqual(resp_ext.status_code, 200)
        self.assertIn(b"activeTab", resp_ext.data)
        resp_ext.close()

    def test_bloqueio_sem_token_ou_com_token_na_query(self):
        with mock.patch.object(config, "TOKEN", self.token_mestre):
            resp_sem = self.client.get("/nexread/artigos")
            self.assertEqual(resp_sem.status_code, 401)

            resp_query = self.client.get(f"/nexread/artigos?token={self.token_mestre}")
            self.assertEqual(resp_query.status_code, 401)

    def test_fluxo_completo_endpoints_nexread(self):
        headers = {"X-Nextor-Token": self.token_mestre}
        with mock.patch.object(config, "TOKEN", self.token_mestre), \
             mock.patch("nextor.cerebro._chamar_ollama", return_value="Texto traduzido localmente."):

            # 1. POST /nexread/traduzir
            resp_trad = self.client.post(
                "/nexread/traduzir",
                json={
                    "conteudo_html": "<h1>Neural Networks</h1><p>Deep learning research paper.</p>",
                    "titulo": "Neural Networks",
                    "url": "https://arxiv.org/abs/2611.99999",
                    "modo_layout": "lado_a_lado",
                    "aberta_pelo_usuario": True,
                },
                headers=headers,
            )
            self.assertEqual(resp_trad.status_code, 201)
            dados_trad = resp_trad.get_json()
            self.assertTrue(dados_trad["ok"])
            artigo_id = dados_trad["artigo"]["id"]
            self.assertIn("nexread-linha-paralela", dados_trad["html_traduzido"])

            # 2. POST /nexread/marcacoes
            resp_marc = self.client.post(
                "/nexread/marcacoes",
                json={
                    "artigo_id": artigo_id,
                    "trecho": "Deep learning",
                    "nota": "Conceito fundamental",
                    "cor": "azul",
                },
                headers=headers,
            )
            self.assertEqual(resp_marc.status_code, 201)
            marcacao_id = resp_marc.get_json()["marcacao"]["id"]

            # 3. POST /nexread/gravacoes
            resp_grav = self.client.post(
                "/nexread/gravacoes",
                json={
                    "artigo_id": artigo_id,
                    "titulo": "Resumo falado",
                    "transcricao": "Explicacao gravada pelo estudante sobre redes neurais.",
                    "duracao_seg": 12,
                },
                headers=headers,
            )
            self.assertEqual(resp_grav.status_code, 201)

            # 4. POST /nexread/conversar
            resp_chat = self.client.post(
                "/nexread/conversar",
                json={
                    "artigo_id": artigo_id,
                    "pergunta": "O que o artigo aborda?",
                    "acao": "perguntar",
                },
                headers=headers,
            )
            self.assertEqual(resp_chat.status_code, 200)
            dados_chat = resp_chat.get_json()
            self.assertTrue(dados_chat["ok"])
            self.assertTrue(len(dados_chat["fontes"]) >= 1)

            # 5. POST /nexread/salvar-estudos
            resp_salvar = self.client.post(
                "/nexread/salvar-estudos",
                json={
                    "artigo_id": artigo_id,
                    "disciplina": "Aprendizado Profundo",
                },
                headers=headers,
            )
            self.assertEqual(resp_salvar.status_code, 200)
            self.assertTrue(resp_salvar.get_json()["ok"])

            # 6. GET /nexread/artigos/<id> e DELETE /nexread/marcacoes/<id>
            resp_det = self.client.get(f"/nexread/artigos/{artigo_id}", headers=headers)
            self.assertEqual(resp_det.status_code, 200)
            det = resp_det.get_json()
            self.assertEqual(len(det["marcacoes"]), 1)
            self.assertEqual(len(det["gravacoes"]), 1)

            resp_del = self.client.delete(f"/nexread/marcacoes/{marcacao_id}", headers=headers)
            self.assertEqual(resp_del.status_code, 200)


if __name__ == "__main__":
    unittest.main()
