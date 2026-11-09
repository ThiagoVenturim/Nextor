"""Testes unitarios offline dos endpoints HTTP do Coach de Estudos no servico (Issue #57)."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

os.environ["NEXTOR_VOZ_SAIDA"] = "nenhuma"

from nextor import config, servico
from nextor.coach.armazenamento import ArmazenamentoCoach
from nextor.coach.coach import criar_plano
from nextor.coach.modelos import Recurso, Trilha


class TestCoachServico(unittest.TestCase):
    def setUp(self):
        self.token_mestre = "token-teste-mestre-coach-12345"
        self.client = servico.app.test_client()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_coach.db"
        self.patch_db = mock.patch.object(config, "COACH_DB", self.db_path)
        self.patch_db.start()
        self.banco = ArmazenamentoCoach(self.db_path)

        self.recurso = Recurso(
            trilha_id="ingles_iniciante",
            tipo="video",
            titulo="Introducao a Fonetica",
            ordem=1,
            duracao_min=15,
        )
        self.trilha = Trilha(
            id="ingles_iniciante",
            titulo="Ingles Basico",
            habilidade="ingles",
            recursos=[self.recurso],
        )
        self.banco.salvar_trilha(self.trilha)
        self.plano = criar_plano(self.trilha, ritmo={"dias_semana": 5, "minutos_dia": 30}, db=self.banco, integrar_gtd=False)

    def tearDown(self):
        self.patch_db.stop()
        self.temp_dir.cleanup()

    def test_bloqueio_sem_token_ou_com_token_na_query(self):
        with mock.patch.object(config, "TOKEN", self.token_mestre):
            # 1. Sem token no header
            resp = self.client.get("/coach/trilhas")
            self.assertEqual(resp.status_code, 401)

            # 2. Token na query string deve ser explicitamente rejeitado
            resp_query = self.client.get(f"/coach/trilhas?token={self.token_mestre}")
            self.assertEqual(resp_query.status_code, 401)

    def test_rotas_coach_autenticadas_com_sucesso(self):
        headers = {"X-Nextor-Token": self.token_mestre}
        with mock.patch.object(config, "TOKEN", self.token_mestre), \
             mock.patch("nextor.coach.coach.dia_esta_cheio", return_value=False):

            # 1. GET /coach/trilhas
            resp = self.client.get("/coach/trilhas", headers=headers)
            self.assertEqual(resp.status_code, 200)
            dados = resp.get_json()
            self.assertTrue(dados["ok"])
            self.assertTrue(len(dados["trilhas"]) >= 1)

            # 2. POST /coach/trilhas
            nova_trilha = {
                "id": "trilha_web",
                "titulo": "Web Standards",
                "habilidade": "web",
                "recursos": [{"tipo": "artigo", "titulo": "Intro HTML", "duracao_min": 10}],
            }
            with mock.patch("nextor.coach.trilhas._obter_pasta_usuario", return_value=Path(self.temp_dir.name)):
                resp_post_t = self.client.post("/coach/trilhas", json=nova_trilha, headers=headers)
                self.assertEqual(resp_post_t.status_code, 201)

            # 3. GET /coach/planos
            resp_planos = self.client.get("/coach/planos", headers=headers)
            self.assertEqual(resp_planos.status_code, 200)
            self.assertTrue(len(resp_planos.get_json()["planos"]) >= 1)

            # 4. GET /coach/acao-do-dia
            resp_acao = self.client.get(f"/coach/acao-do-dia?plano_id={self.plano.id}", headers=headers)
            self.assertEqual(resp_acao.status_code, 200)
            dados_acao = resp_acao.get_json()
            self.assertTrue(dados_acao["ok"])
            self.assertIsNotNone(dados_acao["acao"])

            # 5. POST /coach/concluir
            resp_conc = self.client.post(
                "/coach/concluir",
                json={"plano_id": self.plano.id, "recurso_id": self.recurso.id},
                headers=headers,
            )
            self.assertEqual(resp_conc.status_code, 200)
            dados_conc = resp_conc.get_json()
            self.assertTrue(dados_conc["ok"])
            self.assertTrue(dados_conc["xp_ganho"] > 0)

            # 6. GET /coach/resumo
            resp_resumo = self.client.get(f"/coach/resumo?plano_id={self.plano.id}", headers=headers)
            self.assertEqual(resp_resumo.status_code, 200)
            dados_resumo = resp_resumo.get_json()
            self.assertTrue(dados_resumo["ok"])
            self.assertEqual(dados_resumo["concluidas"], 1)


if __name__ == "__main__":
    unittest.main()
