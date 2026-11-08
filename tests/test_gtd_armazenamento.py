"""Testes unitarios offline do armazenamento SQLite do GTD (Issue #43)."""
from pathlib import Path
import tempfile
import unittest

from nextor.gtd.armazenamento import ArmazenamentoGTD
from nextor.gtd.modelos import Item, Projeto, Leitura


class TestArmazenamentoGTD(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.caminho_db = Path(self.tmp.name) / "teste_gtd.db"
        self.banco = ArmazenamentoGTD(self.caminho_db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_crud_item(self):
        it = Item(
            titulo="Revisar peticao",
            contexto="@trabalho",
            estado="inbox",
            nota="Audiencia amanha",
        )
        self.banco.salvar_item(it)

        recuperado = self.banco.obter_item(it.id)
        self.assertIsNotNone(recuperado)
        self.assertEqual(recuperado.titulo, "Revisar peticao")
        self.assertEqual(recuperado.contexto, "@trabalho")

        # Atualizacao
        recuperado.estado = "proxima"
        self.banco.salvar_item(recuperado)
        atualizado = self.banco.obter_item(it.id)
        self.assertEqual(atualizado.estado, "proxima")

        # Listagem com filtro
        proximas = self.banco.listar_itens(estado="proxima")
        self.assertEqual(len(proximas), 1)
        inbox = self.banco.listar_itens(estado="inbox")
        self.assertEqual(len(inbox), 0)

        # Remocao
        self.assertTrue(self.banco.remover_item(it.id))
        self.assertIsNone(self.banco.obter_item(it.id))

    def test_crud_projeto(self):
        p = Projeto(nome="Organizacao de Documentos", descricao="Digitalizar recibos")
        self.banco.salvar_projeto(p)

        recuperado = self.banco.obter_projeto(p.id)
        self.assertIsNotNone(recuperado)
        self.assertEqual(recuperado.nome, "Organizacao de Documentos")

        projetos = self.banco.listar_projetos(estado="ativo")
        self.assertEqual(len(projetos), 1)

        self.assertTrue(self.banco.remover_projeto(p.id))
        self.assertIsNone(self.banco.obter_projeto(p.id))

    def test_crud_leitura_e_historico(self):
        l = Leitura(
            titulo="Clean Architecture",
            autor="Robert C. Martin",
            tipo="livro",
            paginas_total=300,
        )
        self.banco.salvar_leitura(l)

        recuperada = self.banco.obter_leitura(l.id)
        self.assertIsNotNone(recuperada)
        self.assertEqual(recuperada.titulo, "Clean Architecture")

        # Registra progresso diario
        total1 = self.banco.registrar_progresso_leitura(l.id, 15, "2026-11-08")
        self.assertEqual(total1, 15)
        total2 = self.banco.registrar_progresso_leitura(l.id, 10, "2026-11-08")
        self.assertEqual(total2, 25)

        self.assertEqual(self.banco.paginas_lidas_na_data("2026-11-08"), 25)
        self.assertEqual(self.banco.paginas_lidas_na_data("2026-11-07"), 0)

    def test_buscar_item_por_ref(self):
        it = Item(
            titulo="Issue #100",
            ref_externa="github:repo:100",
            origem="github",
        )
        self.banco.salvar_item(it)

        achado = self.banco.buscar_item_por_ref("github:repo:100")
        self.assertIsNotNone(achado)
        self.assertEqual(achado.id, it.id)
        self.assertIsNone(self.banco.buscar_item_por_ref("inexistente"))


if __name__ == "__main__":
    unittest.main()
