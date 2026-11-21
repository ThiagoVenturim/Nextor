"""Testes unitarios offline do modulo de leituras e meta diaria (Issue #44)."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from nextor import config
from nextor.gtd.armazenamento import ArmazenamentoGTD
from nextor.gtd.gtd import agenda_do_dia
from nextor.gtd.leitura import (
    criar_leitura,
    listar_leituras,
    atualizar_progresso,
    meta_diaria_progresso,
    importar_artigos,
    definir_estado_leitura,
    remover_leitura,
    resumo_leituras,
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
        leitura = criar_leitura("Livro A", db=self.banco)
        with mock.patch.object(config, "LEITURA_META_DIARIA", 25):
            atualizar_progresso(leitura.id, 10, db=self.banco)
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


class TestLeituraEstadosEPainel(unittest.TestCase):
    """Estados manuais, remocao, resumo do painel e artigos ja buscados (#44)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.banco = ArmazenamentoGTD(Path(self.tmp.name) / "teste_leitura_estados.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_definir_estado_lido_e_voltar(self):
        livro = criar_leitura("Duna", paginas_total=600, db=self.banco)
        lido = definir_estado_leitura(livro.id, "lido", db=self.banco)
        self.assertEqual(lido.estado, "lido")
        self.assertIsNotNone(lido.concluido_em)
        self.assertEqual(lido.paginas_lidas, 600)
        # Marcar como lido nao conta para a meta do dia
        self.assertEqual(meta_diaria_progresso(db=self.banco)["paginas_lidas_hoje"], 0)

        de_volta = definir_estado_leitura(livro.id, "lendo", db=self.banco)
        self.assertEqual(de_volta.estado, "lendo")
        self.assertIsNone(de_volta.concluido_em)

    def test_definir_estado_invalido_ou_id_inexistente(self):
        livro = criar_leitura("Livro B", db=self.banco)
        with self.assertRaises(ValueError):
            definir_estado_leitura(livro.id, "abandonado", db=self.banco)
        with self.assertRaises(ValueError):
            definir_estado_leitura("nao-existe", "lendo", db=self.banco)

    def test_criar_ja_lido_registra_conclusao(self):
        livro = criar_leitura("Livro C", estado="lido", db=self.banco)
        self.assertIsNotNone(livro.concluido_em)

    def test_remover_leitura_sem_historico(self):
        livro = criar_leitura("Livro D", db=self.banco)
        self.assertTrue(remover_leitura(livro.id, db=self.banco))
        self.assertFalse(remover_leitura(livro.id, db=self.banco))
        self.assertEqual(listar_leituras(db=self.banco), [])

    def test_resumo_leituras_para_painel(self):
        lendo = criar_leitura("Em andamento", estado="lendo", db=self.banco)
        for i in range(4):
            criar_leitura(f"Fila {i}", db=self.banco)
        criar_leitura("Terminado", estado="lido", db=self.banco)
        with mock.patch.object(config, "LEITURA_META_DIARIA", 10):
            atualizar_progresso(lendo.id, 5, db=self.banco)
            resumo = resumo_leituras(db=self.banco)
        self.assertEqual(resumo["contagem"], {"quero_ler": 4, "lendo": 1, "lido": 1})
        self.assertEqual([item["titulo"] for item in resumo["lendo"]], ["Em andamento"])
        self.assertEqual(len(resumo["fila_quero_ler"]), 3)
        self.assertEqual(resumo["meta"]["percentual"], 50)
        self.assertEqual(resumo["meta"]["faltam_paginas"], 5)

    def test_agenda_do_dia_mostra_fila_de_leitura(self):
        criar_leitura("Atual", estado="lendo", db=self.banco)
        criar_leitura("Proximo", db=self.banco)
        with mock.patch("nextor.agenda.eventos_hoje", return_value=[]):
            res = agenda_do_dia(db=self.banco)
        self.assertEqual(res["leitura"]["livro_atual"]["titulo"], "Atual")
        self.assertEqual(res["leitura"]["fila_quero_ler"][0]["titulo"], "Proximo")
        self.assertEqual(res["leitura"]["contagem"]["lendo"], 1)

    def test_importar_artigos_ja_buscados_sem_rede(self):
        artigos = [
            {"titulo": "Artigo A", "autores": ["A", "B", "C", "D"], "url": "https://example.org/a"},
            {"titulo": "", "url": "https://example.org/sem-titulo"},
            {"titulo": "Artigo B", "autores": [], "pdf_url": "https://example.org/b.pdf"},
        ]
        with mock.patch("nextor.artigos_cientificos.buscar_artigos") as buscar:
            importados = importar_artigos(artigos=artigos, db=self.banco)
            buscar.assert_not_called()
        self.assertEqual([i.titulo for i in importados], ["Artigo A", "Artigo B"])
        self.assertEqual(importados[0].autor, "A, B, C et al.")
        self.assertEqual(importados[1].fonte_url, "https://example.org/b.pdf")
        self.assertTrue(all(i.estado == "quero_ler" and i.tipo == "artigo" for i in importados))

    def test_importar_artigos_respeita_limite_e_termo_vazio(self):
        artigos = [{"titulo": f"Artigo {i}", "url": f"https://example.org/{i}"} for i in range(30)]
        importados = importar_artigos(artigos=artigos, limite=100, db=self.banco)
        self.assertEqual(len(importados), 20)
        with mock.patch("nextor.artigos_cientificos.buscar_artigos") as buscar:
            self.assertEqual(importar_artigos(termo="  ", db=self.banco), [])
            buscar.assert_not_called()

    def test_importar_artigos_falha_de_rede_nao_quebra(self):
        with mock.patch("nextor.artigos_cientificos.buscar_artigos", side_effect=OSError("sem rede")):
            self.assertEqual(importar_artigos(termo="ia", db=self.banco), [])


if __name__ == "__main__":
    unittest.main()
