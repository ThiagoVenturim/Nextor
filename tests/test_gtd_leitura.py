"""Testes unitarios offline do modulo de leituras e meta diaria (Issue #44)."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from nextor import config
from nextor.gtd.armazenamento import ArmazenamentoGTD
from nextor.gtd.leitura import (
    criar_leitura,
    listar_leituras,
    atualizar_progresso,
    meta_diaria_progresso,
    importar_artigos,
)


class TestLeituraGTD(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.caminho_db = Path(self.tmp.name) / "teste_leitura.db"
        self.banco = ArmazenamentoGTD(self.caminho_db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_criar_e_listar_leituras(self):
        l1 = criar_leitura(
            titulo="Refactoring",
            autor="Martin Fowler",
            tipo="livro",
            paginas_total=400,
            db=self.banco,
        )
        self.assertEqual(l1.titulo, "Refactoring")
        self.assertEqual(l1.estado, "quero_ler")

        todas = listar_leituras(db=self.banco)
        self.assertEqual(len(todas), 1)

    def test_atualizar_progresso_soma_paginas_e_atinge_meta(self):
        livro = criar_leitura(
            titulo="Atomic Habits",
            paginas_total=100,
            db=self.banco,
        )
        with mock.patch.object(config, "LEITURA_META_DIARIA", 20):
            # Le 12 paginas: nao atinge meta
            res1 = atualizar_progresso(livro.id, 12, db=self.banco)
            self.assertEqual(res1["paginas_adicionadas"], 12)
            self.assertEqual(res1["paginas_lidas_hoje"], 12)
            self.assertFalse(res1["meta_atingida"])
            self.assertEqual(res1["faltam_paginas"], 8)
            self.assertEqual(res1["leitura"]["estado"], "lendo")

            # Le mais 10 paginas: total 22, atinge a meta
            res2 = atualizar_progresso(livro.id, 10, db=self.banco)
            self.assertEqual(res2["paginas_lidas_hoje"], 22)
            self.assertTrue(res2["meta_atingida"])
            self.assertEqual(res2["faltam_paginas"], 0)

    def test_atualizar_progresso_conclui_leitura(self):
        artigo = criar_leitura(
            titulo="Attention Is All You Need",
            tipo="artigo",
            paginas_total=15,
            db=self.banco,
        )
        res = atualizar_progresso(artigo.id, 15, db=self.banco)
        self.assertEqual(res["leitura"]["estado"], "lido")
        self.assertIsNotNone(res["leitura"]["concluido_em"])

    def test_meta_diaria_progresso(self):
        l = criar_leitura("Livro A", db=self.banco)
        with mock.patch.object(config, "LEITURA_META_DIARIA", 25):
            atualizar_progresso(l.id, 10, db=self.banco)
            meta = meta_diaria_progresso(db=self.banco)
            self.assertEqual(meta["paginas_lidas_hoje"], 10)
            self.assertEqual(meta["meta_diaria"], 25)
            self.assertFalse(meta["meta_atingida"])

    def test_importar_artigos_sem_duplicar(self):
        artigos_falsos = [
            {
                "titulo": "Pesquisa sobre Redes Neurais",
                "autores": ["Silva, J.", "Santos, M."],
                "url": "https://arxiv.org/abs/2401.00001",
            },
            {
                "titulo": "Pesquisa sobre Redes Neurais",  # Titulo repetido
                "autores": ["Outro Autor"],
                "url": "https://arxiv.org/abs/2401.00002",
            },
            {
                "titulo": "Processamento de Linguagem Natural",
                "autores": ["Oliveira, P."],
                "url": "https://arxiv.org/abs/2401.00001",  # URL repetida
            },
            {
                "titulo": "Novo Modelo Transformer",
                "autores": ["Vaswani, A."],
                "url": "https://arxiv.org/abs/2401.00004",
            },
        ]

        def buscador_fake(termo, fonte="todos", limite=5):
            return artigos_falsos

        importados = importar_artigos(
            termo="redes neurais",
            db=self.banco,
            buscador=buscador_fake,
        )

        # Apenas os 2 artigos unicos devem ser importados
        self.assertEqual(len(importados), 2)
        titulos_importados = [i.titulo for i in importados]
        self.assertIn("Pesquisa sobre Redes Neurais", titulos_importados)
        self.assertIn("Novo Modelo Transformer", titulos_importados)

        # Se rodar novamente, nao deve importar nenhum novo
        segunda_rodada = importar_artigos(
            termo="redes neurais",
            db=self.banco,
            buscador=buscador_fake,
        )
        self.assertEqual(len(segunda_rodada), 0)


if __name__ == "__main__":
    unittest.main()
