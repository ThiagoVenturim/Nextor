"""Testes unitarios offline dos endpoints HTTP e PWA do NexVoice no servico (Issue #56)."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

os.environ["NEXTOR_VOZ_SAIDA"] = "nenhuma"

from nextor import config, servico


class TestNexVoiceServico(unittest.TestCase):
    def setUp(self):
        self.token_mestre = "token-teste-mestre-nexvoice-123456"
        self.client = servico.app.test_client()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_dir.name)
        self.db_nexvoice = self.base_path / "test_nexvoice.db"
        self.estudos_dir = self.base_path / "estudos"
        self.estudos_db = self.estudos_dir / "indice_estudos.db"

        self.patch_nv_db = mock.patch.object(config, "NEXVOICE_DB", self.db_nexvoice)
        self.patch_est_dir = mock.patch.object(config, "ESTUDOS_DIR", self.estudos_dir)
        self.patch_est_db = mock.patch.object(config, "ESTUDOS_DB", self.estudos_db)
        self.patch_nv_tts = mock.patch.object(config, "NEXVOICE_TTS_MOTOR", "stub")
        self.patch_nv_db.start()
        self.patch_est_dir.start()
        self.patch_est_db.start()
        self.patch_nv_tts.start()

    def tearDown(self):
        self.patch_nv_db.stop()
        self.patch_est_dir.stop()
        self.patch_est_db.stop()
        self.patch_nv_tts.stop()
        self.temp_dir.cleanup()

    def test_pwa_nexvoice_servido_corretamente(self):
        resp_pwa = self.client.get("/nexvoice")
        self.assertEqual(resp_pwa.status_code, 200)
        self.assertIn(b"NexVoice", resp_pwa.data)
        resp_pwa.close()

        resp_manifest = self.client.get("/nexvoice/manifest.webmanifest")
        self.assertEqual(resp_manifest.status_code, 200)
        resp_manifest.close()

        resp_sw = self.client.get("/nexvoice/sw.js")
        self.assertEqual(resp_sw.status_code, 200)
        resp_sw.close()

    def test_autenticacao_rejeita_sem_token_ou_token_na_query(self):
        with mock.patch.object(config, "TOKEN", self.token_mestre):
            resp_sem = self.client.get("/nexvoice/sessoes")
            self.assertEqual(resp_sem.status_code, 401)

            resp_query = self.client.get(f"/nexvoice/sessoes?token={self.token_mestre}")
            self.assertEqual(resp_query.status_code, 401)

    def test_fluxo_completo_endpoints_nexvoice_com_etica_e_bidirecional(self):
        headers = {"X-Nextor-Token": self.token_mestre}
        with mock.patch.object(config, "TOKEN", self.token_mestre), \
             mock.patch("nextor.cerebro._chamar_ollama", side_effect=OSError("offline")):

            # 1. Tentar iniciar reuniao sem consentimento -> 403 Forbidden
            resp_sem_cons = self.client.post(
                "/nexvoice/sessoes",
                json={
                    "titulo": "Reuniao Internacional",
                    "modo": "reuniao",
                    "consentimento_confirmado": False,
                },
                headers=headers,
            )
            self.assertEqual(resp_sem_cons.status_code, 403)
            self.assertEqual(resp_sem_cons.get_json()["erro"], "consentimento_ou_privacidade_obrigatorio")

            # 2. Iniciar reuniao com consentimento confirmado -> 201 Created
            resp_ini = self.client.post(
                "/nexvoice/sessoes",
                json={
                    "titulo": "Reuniao Internacional",
                    "modo": "reuniao",
                    "idioma_meu": "pt-BR",
                    "idioma_outro": "en-US",
                    "consentimento_confirmado": True,
                    "consentimento_participantes": "Maria e Alex",
                },
                headers=headers,
            )
            self.assertEqual(resp_ini.status_code, 201)
            sessao_id = resp_ini.get_json()["sessao"]["id"]

            # 3. POST /nexvoice/trechos (entrada e saida)
            resp_tr_in = self.client.post(
                "/nexvoice/trechos",
                json={
                    "sessao_id": sessao_id,
                    "direcao": "entrada",
                    "locutor": "Alex",
                    "texto_fala": "Let us review the project architecture",
                },
                headers=headers,
            )
            self.assertEqual(resp_tr_in.status_code, 201)
            tr_in = resp_tr_in.get_json()["trecho"]
            self.assertEqual(tr_in["idioma_destino"], "pt-BR")
            self.assertIn("arquitetura do projeto", tr_in["texto_traduzido"].lower())

            resp_tr_out = self.client.post(
                "/nexvoice/trechos",
                json={
                    "sessao_id": sessao_id,
                    "direcao": "saida",
                    "locutor": "Maria",
                    "texto_fala": "Obrigado pela explicacao",
                },
                headers=headers,
            )
            self.assertEqual(resp_tr_out.status_code, 201)
            tr_out = resp_tr_out.get_json()["trecho"]
            self.assertEqual(tr_out["idioma_destino"], "en-US")
            self.assertIn("thank you for the explanation", tr_out["texto_traduzido"].lower())

            # 4. GET /nexvoice/sessoes/<id>/legendas.srt
            resp_srt = self.client.get(f"/nexvoice/sessoes/{sessao_id}/legendas.srt", headers=headers)
            self.assertEqual(resp_srt.status_code, 200)
            self.assertIn(b"-->", resp_srt.data)

            # 5. POST /nexvoice/salvar-estudos
            resp_est = self.client.post(
                "/nexvoice/salvar-estudos",
                json={"sessao_id": sessao_id, "disciplina": "Arquitetura de Sistemas"},
                headers=headers,
            )
            self.assertEqual(resp_est.status_code, 200)
            self.assertTrue(resp_est.get_json()["ok"])

            # 6. POST /nexvoice/encerrar
            resp_enc = self.client.post(
                "/nexvoice/encerrar",
                json={"sessao_id": sessao_id, "gerar_ata": True},
                headers=headers,
            )
            self.assertEqual(resp_enc.status_code, 200)
            dados_enc = resp_enc.get_json()
            self.assertTrue(dados_enc["ok"])
            self.assertEqual(dados_enc["sessao"]["estado"], "encerrada")
            self.assertIn("ata_reuniao", dados_enc)

            # 7. GET /nexvoice/sessoes/<id>
            resp_det = self.client.get(f"/nexvoice/sessoes/{sessao_id}", headers=headers)
            self.assertEqual(resp_det.status_code, 200)
            det = resp_det.get_json()
            self.assertEqual(len(det["consentimentos"]), 1)
            self.assertEqual(len(det["sessao"]["trechos"]), 2)


if __name__ == "__main__":
    unittest.main()
