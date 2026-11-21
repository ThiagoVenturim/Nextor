"""Testes unitarios offline do servidor MCP e roteador de voz com GTD."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from nextor import config, roteador
try:
    from nextor import mcp_server
except ImportError:
    mcp_server = None

from nextor.gtd.armazenamento import ArmazenamentoGTD


class TestMcpRoteadorGTD(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.caminho_db = Path(self.tmp.name) / "teste_mcp_gtd.db"
        self.patch_db = mock.patch.object(config, "GTD_DB", self.caminho_db)
        self.patch_db.start()
        self.banco = ArmazenamentoGTD(self.caminho_db)

    def tearDown(self):
        self.patch_db.stop()
        self.tmp.cleanup()

    @unittest.skipIf(mcp_server is None, "mcp nao instalado no ambiente")
    def test_mcp_gtd_capturar(self):
        resp = mcp_server.gtd_capturar("Organizar gaveta de documentos", contexto="@casa")
        self.assertIn("Capturado no GTD: Organizar gaveta de documentos", resp)
        self.assertIn("@casa", resp)

        itens = self.banco.listar_itens()
        self.assertEqual(len(itens), 1)
        self.assertEqual(itens[0].titulo, "Organizar gaveta de documentos")

    @unittest.skipIf(mcp_server is None, "mcp nao instalado no ambiente")
    def test_mcp_gtd_dia(self):
        resp = mcp_server.gtd_dia()
        self.assertIsInstance(resp, str)
        self.assertTrue(len(resp) > 0)

    @unittest.skipIf(mcp_server is None, "mcp nao instalado no ambiente")
    def test_mcp_leitura_progresso(self):
        resp = mcp_server.leitura_progresso(10)
        self.assertIn("Registradas 10 paginas", resp)

    def test_roteador_voz_gtd_capturar(self):
        res = roteador.rotear("anota tarefa comprar cafe")
        self.assertEqual(res["intencao"], "gtd_capturar")
        self.assertIn("Anotado na sua caixa de entrada", res["resposta"])

    def test_roteador_voz_gtd_dia(self):
        res = roteador.rotear("o que tenho pra hoje")
        self.assertEqual(res["intencao"], "gtd_dia")
        self.assertIsInstance(res["resposta"], str)

    def test_roteador_voz_leitura_progresso(self):
        res = roteador.rotear("li 20 paginas")
        self.assertEqual(res["intencao"], "leitura_progresso")
        self.assertIn("20 paginas", res["resposta"])


if __name__ == "__main__":
    unittest.main()
