"""Testes unitarios offline das integracoes GTD com GitHub e Notion (Issue #42)."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from nextor import config
from nextor.gtd.armazenamento import ArmazenamentoGTD
from nextor.gtd.integracoes import tarefas_do_github, sincronizar_notion
from nextor.gtd.notion import ClienteNotion


class TestIntegracoesGTD(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.caminho_db = Path(self.tmp.name) / "teste_integracoes.db"
        self.banco = ArmazenamentoGTD(self.caminho_db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_github_cria_itens_sem_duplicar(self):
        issues_falsas = [
            {
                "id": 101,
                "number": 42,
                "title": "Implementar integracao Notion",
                "html_url": "https://github.com/ThiagoVenturim/Nextor/issues/42",
            },
            {
                "id": 102,
                "number": 43,
                "title": "Criar painel PWA celular",
                "html_url": "https://github.com/ThiagoVenturim/Nextor/issues/43",
            },
        ]

        def req_github_fake(path, metodo="GET", dados=None, token=None, handler_requisicao=None):
            return 200, issues_falsas

        itens1 = tarefas_do_github(
            db=self.banco,
            cliente_requisicao=req_github_fake,
        )
        self.assertEqual(len(itens1), 2)
        for it in itens1:
            self.assertEqual(it.contexto, "@trabalho")
            self.assertEqual(it.estado, "proxima")
            self.assertEqual(it.origem, "github")

        # Segunda chamada nao deve duplicar
        itens2 = tarefas_do_github(
            db=self.banco,
            cliente_requisicao=req_github_fake,
        )
        self.assertEqual(len(itens2), 0)

        total_banco = self.banco.listar_itens(contexto="@trabalho")
        self.assertEqual(len(total_banco), 2)

    def test_notion_desligado_sem_token_nao_lanca_excecao_nem_vaza(self):
        with mock.patch.dict(os.environ, {"NOTION_TOKEN": "", "NOTION_DB_TAREFAS": "", "NOTION_DB_LEITURAS": ""}), \
             mock.patch.object(config, "NOTION_TOKEN", ""), \
             mock.patch.object(config, "NOTION_DB_TAREFAS", ""), \
             mock.patch.object(config, "NOTION_DB_LEITURAS", ""):

            cliente = ClienteNotion(token="", db_tarefas="", db_leituras="")
            self.assertFalse(cliente.disponivel())

            # A chamada nao deve levantar excecao e deve retornar status desligado
            res = sincronizar_notion(db=self.banco, cliente=cliente)
            self.assertEqual(res["status"], "desligado")
            self.assertEqual(res["sincronizados"], 0)

    def test_notion_sincronizacao_com_mock_http(self):
        paginas_fake = [
            {
                "id": "notion-page-123",
                "last_edited_time": "2026-11-08T18:00:00.000Z",
                "properties": {
                    "Nome": {
                        "type": "title",
                        "title": [{"plain_text": "Estudar processo administrativo"}]
                    }
                }
            }
        ]

        def fake_http(url, metodo, dados, headers):
            if "/query" in url:
                return 200, {"results": paginas_fake}
            if "/pages" in url and metodo == "POST":
                return 201, {"id": "nova-pag-id", "last_edited_time": "2026-11-08T18:05:00.000Z"}
            return 200, {}

        cliente = ClienteNotion(
            token="secret_notion_fake_token",
            db_tarefas="db_tarefas_123",
            db_leituras="",
            http_client=fake_http,
        )
        self.assertTrue(cliente.disponivel())

        res = sincronizar_notion(db=self.banco, cliente=cliente)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["tarefas_puxadas"], 1)

        # Verifica se o item foi criado no banco local
        itens = self.banco.listar_itens()
        self.assertEqual(len(itens), 1)
        self.assertEqual(itens[0].titulo, "Estudar processo administrativo")
        self.assertEqual(itens[0].origem, "notion")


if __name__ == "__main__":
    unittest.main()
