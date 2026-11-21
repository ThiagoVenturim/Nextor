"""Testes unitarios offline das ferramentas MCP e do roteador de voz para o NexRead (Issue #55)."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

os.environ["NEXTOR_VOZ_SAIDA"] = "nenhuma"

from nextor import config
from nextor.mcp_server import (
    nexread_conversar,
    nexread_gravar_nota,
    nexread_marcar_trecho,
    nexread_salvar_estudos,
    nexread_traduzir_pagina,
)
from nextor.nexread import ArmazenamentoNexRead
from nextor.roteador import rotear


class TestNexReadMCPRoteador(unittest.TestCase):
    def setUp(self):
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

    def test_mcp_nexread_ferramentas(self):
        with mock.patch("nextor.cerebro._chamar_ollama", return_value="Introducao ao aprendizado de maquina."):
            resp_trad = nexread_traduzir_pagina(
                conteudo_ou_html="<h1>Machine Learning</h1><p>Introduction to machine learning models.</p>",
                titulo="Machine Learning",
                url="https://arxiv.org/abs/2611.55555",
            )
            self.assertIn("Artigo traduzido no NexRead", resp_trad)

            banco = ArmazenamentoNexRead(self.db_nexread)
            artigos = banco.listar_artigos()
            self.assertEqual(len(artigos), 1)
            artigo_id = artigos[0].id

            resp_marc = nexread_marcar_trecho(
                artigo_id=artigo_id,
                trecho="machine learning",
                nota="Revisar conceito",
                cor="verde",
            )
            self.assertIn("Trecho marcado em verde", resp_marc)

            resp_grav = nexread_gravar_nota(
                artigo_id=artigo_id,
                transcricao="Anotacao gravada sobre modelos lineares.",
                titulo="Audio 1",
                duracao_seg=10,
            )
            self.assertIn("Audio 1", resp_grav)

            resp_chat = nexread_conversar(
                artigo_id=artigo_id,
                pergunta="Qual o tema?",
                acao="perguntar",
            )
            self.assertIn("Fontes:", resp_chat)

            resp_salvar = nexread_salvar_estudos(artigo_id=artigo_id, disciplina="Ciencia de Dados")
            self.assertIn("Ciencia de Dados", resp_salvar)

    def test_roteador_voz_nexread(self):
        with mock.patch("nextor.cerebro._chamar_ollama", return_value="Redes neurais aplicadas."):
            r1 = rotear("ei Nextor, traduzir pagina ao vivo: Deep learning and neural networks")
            self.assertEqual(r1["intencao"], "nexread_traduzir")
            self.assertIn("Pagina traduzida no NexRead", r1["resposta"])

            r2 = rotear("resumir no nexread")
            self.assertEqual(r2["intencao"], "nexread_conversar")

            r3 = rotear("perguntar sobre o artigo: como funciona a rede?")
            self.assertEqual(r3["intencao"], "nexread_conversar")

            r4 = rotear("salvar leitura do nexread em Computacao")
            self.assertEqual(r4["intencao"], "nexread_salvar_estudos")
            self.assertIn("Computacao", r4["resposta"])


if __name__ == "__main__":
    unittest.main()
