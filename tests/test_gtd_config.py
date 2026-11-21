"""Testes de configuracao do usuario, rotas de config e visao dinamica."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from nextor import config, servico
from nextor.gtd.armazenamento import ArmazenamentoGTD
from nextor.gtd.configuracao import (
    carregar_config,
    obter_config_completa,
    salvar_config,
)
from nextor.gtd.modelos import Item


class TestGTDConfiguracao(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp_dir.name) / "config.json"
        self.db_path = Path(self.temp_dir.name) / "gtd.db"
        self.token_mestre = "nxt_mestre_seguro_123456789012345"

        self.patch_token = mock.patch.object(config, "TOKEN", self.token_mestre)
        self.patch_db = mock.patch.object(config, "GTD_DB", self.db_path)
        self.patch_token.start()
        self.patch_db.start()

        self.orig_config_env = os.environ.get("NEXTOR_GTD_CONFIG_JSON")
        os.environ["NEXTOR_GTD_CONFIG_JSON"] = str(self.config_path)

        self.client = servico.app.test_client()

    def tearDown(self) -> None:
        self.patch_db.stop()
        self.patch_token.stop()

        if self.orig_config_env is not None:
            os.environ["NEXTOR_GTD_CONFIG_JSON"] = self.orig_config_env
        else:
            os.environ.pop("NEXTOR_GTD_CONFIG_JSON", None)

        self.temp_dir.cleanup()

    def test_persistencia_configuracao(self) -> None:
        config_inicial = carregar_config(self.config_path)
        self.assertEqual(config_inicial.get("metodo_ativo"), "gtd")
        self.assertEqual(config_inicial.get("tema"), "escuro")

        atualizacao = {
            "metodo_ativo": "kanban",
            "tema": "claro",
            "paleta": "esmeralda",
            "kanban_wip_limite": 4,
            "wizard_concluido": True,
        }
        salva = salvar_config(atualizacao, self.config_path)
        self.assertEqual(salva["metodo_ativo"], "kanban")
        self.assertEqual(salva["paleta"], "esmeralda")
        self.assertTrue(salva["wizard_concluido"])

        recarregada = carregar_config(self.config_path)
        self.assertEqual(recarregada["metodo_ativo"], "kanban")
        self.assertEqual(recarregada["kanban_wip_limite"], 4)

    def test_obter_config_completa_catalogo(self) -> None:
        completa = obter_config_completa(self.config_path)
        self.assertIn("config", completa)
        self.assertIn("metodos", completa)
        self.assertIn("canais", completa)
        self.assertIn("integracoes", completa)
        self.assertIn("agentes", completa)
        self.assertIn("mcp_ferramentas", completa)
        self.assertEqual(len(completa["metodos"]), 4)

    def test_endpoint_config_requer_token_header(self) -> None:
        resp_sem_token = self.client.get("/gtd/config")
        self.assertEqual(resp_sem_token.status_code, 401)

        resp_query_token = self.client.get(f"/gtd/config?token={self.token_mestre}")
        self.assertEqual(resp_query_token.status_code, 401)

        resp_token_valido = self.client.get(
            "/gtd/config",
            headers={"X-Nextor-Token": self.token_mestre},
        )
        self.assertEqual(resp_token_valido.status_code, 200)
        dados = resp_token_valido.get_json()
        self.assertTrue(dados.get("ok"))
        self.assertIn("config", dados)

    def test_endpoint_put_config_valida_e_atualiza(self) -> None:
        headers = {
            "X-Nextor-Token": self.token_mestre,
            "Content-Type": "application/json",
        }
        resp = self.client.put(
            "/gtd/config",
            headers=headers,
            data=json.dumps({"metodo_ativo": "eisenhower", "paleta": "violeta"}),
        )
        self.assertEqual(resp.status_code, 200)
        dados = resp.get_json()
        self.assertTrue(dados.get("ok"))
        self.assertEqual(dados["config"]["metodo_ativo"], "eisenhower")
        self.assertEqual(dados["config"]["paleta"], "violeta")

        # Metodo invalido
        resp_inv = self.client.put(
            "/gtd/config",
            headers=headers,
            data=json.dumps({"metodo_ativo": "metodo_fantasma"}),
        )
        self.assertEqual(resp_inv.status_code, 400)

    def test_endpoint_visao_dinamica(self) -> None:
        headers = {"X-Nextor-Token": self.token_mestre}
        storage = ArmazenamentoGTD(self.db_path)
        item = Item(id="v1", titulo="Planejar semana", estado="proxima")
        storage.salvar_item(item)

        resp = self.client.get("/gtd/visao", headers=headers)
        self.assertEqual(resp.status_code, 200)
        dados = resp.get_json()
        self.assertTrue(dados.get("ok"))
        self.assertEqual(dados.get("metodo"), "gtd")
        self.assertIn("colunas", dados)
        self.assertIn("itens_por_coluna", dados)

    def test_endpoint_pomodoro_e_notificacao_teste(self) -> None:
        headers = {
            "X-Nextor-Token": self.token_mestre,
            "Content-Type": "application/json",
        }
        # Iniciar pomodoro
        resp = self.client.post(
            "/gtd/pomodoro/iniciar",
            headers=headers,
            data=json.dumps({"item_id": "tarefa-1"}),
        )
        self.assertEqual(resp.status_code, 200)
        dados = resp.get_json()
        self.assertTrue(dados.get("ok"))
        self.assertTrue(dados["ativo"])

        # Estado pomodoro
        resp_estado = self.client.get("/gtd/pomodoro/estado", headers=headers)
        self.assertEqual(resp_estado.status_code, 200)
        self.assertTrue(resp_estado.get_json()["ativo"])

        # Parar pomodoro
        resp_parar = self.client.post("/gtd/pomodoro/parar", headers=headers)
        self.assertEqual(resp_parar.status_code, 200)
        self.assertFalse(resp_parar.get_json()["ativo"])

        # Teste de notificacao
        resp_notif = self.client.post(
            "/gtd/notificacoes/teste",
            headers=headers,
            data=json.dumps({"mensagem": "Alerta de teste"}),
        )
        self.assertEqual(resp_notif.status_code, 200)
        self.assertTrue(resp_notif.get_json().get("ok"))


if __name__ == "__main__":
    unittest.main()
