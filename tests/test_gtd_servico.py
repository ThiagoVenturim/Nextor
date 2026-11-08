"""Testes unitarios offline dos endpoints HTTP do GTD no servico (Issues #42, #43, #44)."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

os.environ["NEXTOR_VOZ_SAIDA"] = "nenhuma"

from nextor import config, servico


class TestServicoGTD(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.caminho_db = Path(self.tmp.name) / "teste_servico_gtd.db"
        self.token_mestre = "nxt_mestre_seguro_123456789012345"

        self.patch_token = mock.patch.object(config, "TOKEN", self.token_mestre)
        self.patch_db = mock.patch.object(config, "GTD_DB", self.caminho_db)
        self.patch_token.start()
        self.patch_db.start()

        self.client = servico.app.test_client()

    def tearDown(self):
        self.patch_db.stop()
        self.patch_token.stop()
        self.tmp.cleanup()

    def test_rotas_gtd_sem_token_retornam_401(self):
        rotas = [
            ("GET", "/gtd/itens"),
            ("POST", "/gtd/capturar"),
            ("POST", "/gtd/processar"),
            ("GET", "/gtd/hoje"),
            ("GET", "/gtd/leituras"),
            ("POST", "/gtd/leituras"),
            ("POST", "/gtd/sincronizar"),
            ("GET", "/gtd/projetos"),
            ("GET", "/gtd/revisao"),
        ]
        for metodo, rota in rotas:
            if metodo == "GET":
                res = self.client.get(rota)
            else:
                res = self.client.post(rota, json={})
            self.assertEqual(res.status_code, 401, f"Rota {rota} deveria exigir autenticacao")

    def test_rotas_gtd_com_token_na_url_retornam_401(self):
        # Exigencia do brief: token mestre no header, NUNCA na URL
        res = self.client.get(f"/gtd/itens?token={self.token_mestre}")
        self.assertEqual(res.status_code, 401)

    def test_rotas_gtd_com_token_no_header_sucesso(self):
        headers = {"X-Nextor-Token": self.token_mestre}

        # 1. Capturar
        res_cap = self.client.post(
            "/gtd/capturar",
            headers=headers,
            json={"titulo": "Estudar processo penal", "contexto": "@faculdade"},
        )
        self.assertEqual(res_cap.status_code, 200)
        dados_cap = res_cap.get_json()
        self.assertTrue(dados_cap["ok"])
        item_id = dados_cap["item"]["id"]

        # 2. Listar itens
        res_list = self.client.get("/gtd/itens?estado=inbox", headers=headers)
        self.assertEqual(res_list.status_code, 200)
        dados_list = res_list.get_json()
        self.assertEqual(len(dados_list["itens"]), 1)

        # 3. Processar
        res_proc = self.client.post(
            "/gtd/processar",
            headers=headers,
            json={"item_id": item_id, "novo_estado": "proxima", "novo_contexto": "@faculdade"},
        )
        self.assertEqual(res_proc.status_code, 200)
        self.assertEqual(res_proc.get_json()["item"]["estado"], "proxima")

        # 4. Hoje
        res_hoje = self.client.get("/gtd/hoje", headers=headers)
        self.assertEqual(res_hoje.status_code, 200)
        self.assertTrue(res_hoje.get_json()["ok"])

        # 5. Criar e listar leituras
        res_leit = self.client.post(
            "/gtd/leituras",
            headers=headers,
            json={"titulo": "Domain-Driven Design", "paginas_total": 500},
        )
        self.assertEqual(res_leit.status_code, 200)
        leitura_id = res_leit.get_json()["leitura"]["id"]

        # 6. Progresso da leitura
        res_prog = self.client.post(
            f"/gtd/leituras/{leitura_id}/progresso",
            headers=headers,
            json={"paginas": 25},
        )
        self.assertEqual(res_prog.status_code, 200)
        self.assertEqual(res_prog.get_json()["progresso"]["paginas_lidas_hoje"], 25)

        # 7. Sincronizacao
        res_sync = self.client.post("/gtd/sincronizar", headers=headers)
        self.assertEqual(res_sync.status_code, 200)

    def test_pwa_arquivos_estaticos(self):
        # O shell do PWA deve ser servido para o navegador
        res_index = self.client.get("/gtd")
        self.assertEqual(res_index.status_code, 200)
        self.assertIn(b"Nextor GTD", res_index.data)

        res_app = self.client.get("/gtd/app")
        self.assertEqual(res_app.status_code, 200)

        res_css = self.client.get("/gtd/app.css")
        self.assertEqual(res_css.status_code, 200)

        res_js = self.client.get("/gtd/app.js")
        self.assertEqual(res_js.status_code, 200)

        res_manifest = self.client.get("/gtd/manifest.webmanifest")
        self.assertEqual(res_manifest.status_code, 200)


if __name__ == "__main__":
    unittest.main()
