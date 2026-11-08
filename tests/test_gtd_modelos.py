"""Testes unitarios offline dos modelos GTD (Issue #43, #44)."""
import unittest

from nextor.gtd.modelos import (
    Item,
    Projeto,
    Leitura,
    normalizar_contexto,
    normalizar_prazo,
    CONTEXTOS_PERMITIDOS,
)


class TestModelosGTD(unittest.TestCase):
    def test_normalizar_contexto(self):
        self.assertEqual(normalizar_contexto("@faculdade"), "@faculdade")
        self.assertEqual(normalizar_contexto("faculdade"), "@faculdade")
        self.assertEqual(normalizar_contexto("@TRABALHO"), "@trabalho")
        self.assertEqual(normalizar_contexto("invalido"), "@qualquer")
        self.assertEqual(normalizar_contexto(""), "@qualquer")
        self.assertEqual(normalizar_contexto(None), "@qualquer")

    def test_normalizar_prazo(self):
        self.assertEqual(normalizar_prazo("2026-11-08"), "2026-11-08")
        self.assertEqual(normalizar_prazo("2026-11-08T12:00:00"), "2026-11-08")
        self.assertIsNone(normalizar_prazo(""))
        self.assertIsNone(normalizar_prazo(None))

    def test_item_criacao_padroes(self):
        it = Item(titulo="Estudar direito penal")
        self.assertTrue(it.id)
        self.assertEqual(it.titulo, "Estudar direito penal")
        self.assertEqual(it.estado, "inbox")
        self.assertEqual(it.contexto, "@qualquer")
        self.assertEqual(it.energia, "media")
        self.assertIsNotNone(it.criado_em)
        self.assertIsNone(it.concluido_em)

    def test_item_serializacao(self):
        it = Item(
            titulo="Treinar na academia",
            contexto="@academia",
            estado="proxima",
            energia="alta",
            prazo="2026-11-10",
        )
        d = it.to_dict()
        self.assertEqual(d["titulo"], "Treinar na academia")
        self.assertEqual(d["contexto"], "@academia")
        self.assertEqual(d["estado"], "proxima")

        it2 = Item.from_dict(d)
        self.assertEqual(it2.id, it.id)
        self.assertEqual(it2.titulo, it.titulo)
        self.assertEqual(it2.contexto, "@academia")

    def test_projeto_criacao_e_serializacao(self):
        p = Projeto(nome="TCC da Faculdade", descricao="Pesquisa e monografia")
        self.assertTrue(p.id)
        self.assertEqual(p.nome, "TCC da Faculdade")
        self.assertEqual(p.estado, "ativo")

        d = p.to_dict()
        p2 = Projeto.from_dict(d)
        self.assertEqual(p2.id, p.id)
        self.assertEqual(p2.nome, p.nome)

    def test_leitura_criacao_e_serializacao(self):
        l = Leitura(
            titulo="A Arte de Fazer Acontecer",
            autor="David Allen",
            tipo="livro",
            paginas_total=350,
            paginas_lidas=50,
        )
        self.assertTrue(l.id)
        self.assertEqual(l.estado, "quero_ler")
        self.assertEqual(l.paginas_total, 350)
        self.assertEqual(l.paginas_lidas, 50)

        d = l.to_dict()
        l2 = Leitura.from_dict(d)
        self.assertEqual(l2.id, l.id)
        self.assertEqual(l2.titulo, l.titulo)
        self.assertEqual(l2.autor, "David Allen")


if __name__ == "__main__":
    unittest.main()
