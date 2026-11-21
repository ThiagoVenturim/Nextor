"""Testes offline das rotas HTTP e ferramentas MCP da lista de leitura (Issue #44)."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

os.environ["NEXTOR_VOZ_SAIDA"] = "nenhuma"

from nextor import config, servico  # noqa: E402
from nextor.gtd.armazenamento import ArmazenamentoGTD  # noqa: E402

try:
    from nextor import mcp_server
except ImportError:
    mcp_server = None


class TestServicoLeitura(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.caminho_db = Path(self.tmp.name) / "teste_servico_leitura.db"
        self.token = "nxt_mestre_seguro_leitura_1234567890"
        self.patches = [
            mock.patch.object(config, "TOKEN", self.token),
            mock.patch.object(config, "GTD_DB", self.caminho_db),
            mock.patch.object(config, "LEITURA_META_DIARIA", 10),
        ]
        for p in self.patches:
            p.start()
        self.client = servico.app.test_client()
        self.headers = {"X-Nextor-Token": self.token}

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def _criar(self, titulo: str, **extra) -> dict:
        res = self.client.post("/gtd/leituras", headers=self.headers, json={"titulo": titulo, **extra})
        self.assertEqual(res.status_code, 200)
        return res.get_json()["leitura"]

    def test_rotas_novas_exigem_token(self):
        self.assertEqual(self.client.get("/gtd/leituras/meta").status_code, 401)
        self.assertEqual(self.client.post("/gtd/leituras/x/estado", json={"estado": "lido"}).status_code, 401)
        self.assertEqual(self.client.delete("/gtd/leituras/x").status_code, 401)
        self.assertEqual(
            self.client.post("/gtd/leituras/importar-artigos", json={"termo": "ia"}).status_code, 401
        )

    def test_estado_e_remocao(self):
        livro = self._criar("Sapiens", paginas_total=400)

        res = self.client.post(f"/gtd/leituras/{livro['id']}/estado", headers=self.headers, json={"estado": "lendo"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["leitura"]["estado"], "lendo")

        res = self.client.post(f"/gtd/leituras/{livro['id']}/estado", headers=self.headers, json={"estado": "xyz"})
        self.assertEqual(res.status_code, 400)

        res = self.client.post("/gtd/leituras/nao-existe/estado", headers=self.headers, json={"estado": "lido"})
        self.assertEqual(res.status_code, 400)

        self.assertEqual(self.client.delete(f"/gtd/leituras/{livro['id']}", headers=self.headers).status_code, 200)
        self.assertEqual(self.client.delete(f"/gtd/leituras/{livro['id']}", headers=self.headers).status_code, 404)

    def test_meta_e_painel_do_dia(self):
        livro = self._criar("Livro do Dia", estado="lendo", paginas_total=100)
        self._criar("Na fila")
        self.client.post(f"/gtd/leituras/{livro['id']}/progresso", headers=self.headers, json={"paginas": 4})

        meta = self.client.get("/gtd/leituras/meta", headers=self.headers).get_json()
        self.assertTrue(meta["ok"])
        self.assertEqual(meta["meta"]["paginas_lidas_hoje"], 4)
        self.assertEqual(meta["meta"]["faltam_paginas"], 6)
        self.assertEqual(meta["contagem"]["quero_ler"], 1)

        with mock.patch("nextor.agenda.eventos_hoje", return_value=[]):
            hoje = self.client.get("/gtd/hoje", headers=self.headers).get_json()
        self.assertEqual(hoje["leitura"]["livro_atual"]["titulo"], "Livro do Dia")
        self.assertEqual(hoje["leitura"]["fila_quero_ler"][0]["titulo"], "Na fila")

    def test_importar_artigos_ja_buscados(self):
        artigos = [
            {"titulo": "Deep Learning Review", "autores": ["LeCun, Y."], "url": "https://example.org/dl"},
            {"titulo": "Deep Learning Review", "url": "https://example.org/dl"},
        ]
        with mock.patch("nextor.artigos_cientificos.buscar_artigos") as buscar:
            res = self.client.post("/gtd/leituras/importar-artigos", headers=self.headers, json={"artigos": artigos})
            buscar.assert_not_called()
        dados = res.get_json()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(dados["total"], 1)
        self.assertEqual(dados["importados"][0]["estado"], "quero_ler")

    def test_importar_artigos_por_termo_usa_modulo_de_artigos(self):
        falsos = [{"titulo": "Quantum Computing", "autores": ["Feynman, R."], "url": "https://example.org/q"}]
        with mock.patch("nextor.artigos_cientificos.buscar_artigos", return_value=falsos) as buscar:
            res = self.client.post(
                "/gtd/leituras/importar-artigos",
                headers=self.headers,
                json={"termo": "quantum", "fonte": "arxiv", "limite": 3},
            )
        buscar.assert_called_once_with("quantum", fonte="arxiv", limite=3)
        self.assertEqual(res.get_json()["total"], 1)

    def test_importar_artigos_valida_entrada(self):
        casos = [
            {},
            {"termo": "ia", "fonte": "google"},
            {"artigos": "nao e lista"},
        ]
        for corpo in casos:
            res = self.client.post("/gtd/leituras/importar-artigos", headers=self.headers, json=corpo)
            self.assertEqual(res.status_code, 400, corpo)


@unittest.skipIf(mcp_server is None, "mcp nao instalado no ambiente")
class TestMcpLeitura(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.caminho_db = Path(self.tmp.name) / "teste_mcp_leitura.db"
        self.patch_db = mock.patch.object(config, "GTD_DB", self.caminho_db)
        self.patch_db.start()
        self.banco = ArmazenamentoGTD(self.caminho_db)

    def tearDown(self):
        self.patch_db.stop()
        self.tmp.cleanup()

    def test_listar_estado_e_importar(self):
        self.assertEqual(mcp_server.leitura_listar(), "Fila de leitura vazia.")

        falsos = [{"titulo": "Artigo MCP", "url": "https://example.org/mcp"}]
        with mock.patch("nextor.artigos_cientificos.buscar_artigos", return_value=falsos):
            resp = mcp_server.leitura_importar_artigos("agentes")
        self.assertIn("Artigo MCP", resp)

        leitura = self.banco.listar_leituras()[0]
        self.assertIn("quero_ler", mcp_server.leitura_listar("quero_ler"))
        self.assertIn("lido", mcp_server.leitura_estado(leitura.id, "lido"))
        self.assertIn("invalido", mcp_server.leitura_estado(leitura.id, "talvez"))


if __name__ == "__main__":
    unittest.main()
