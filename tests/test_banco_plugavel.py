"""Testes unitarios do banco plugavel (SQLAlchemy Core) para GTD e Coach (Issue #66)."""
import os
import unittest
from unittest import mock

os.environ["NEXTOR_VOZ_SAIDA"] = "nenhuma"

from nextor import config
from nextor.coach.armazenamento import ArmazenamentoCoach
from nextor.coach.modelos import Plano, Pontuacao, ProgressoAcao, Recurso, Trilha
from nextor.db import ArmazenamentoCoachSQLAlchemy, ArmazenamentoGTDSQLAlchemy, obter_engine
from nextor.gtd.armazenamento import ArmazenamentoGTD
from nextor.gtd.modelos import Item, Leitura, Projeto


class TestGTDSQLAlchemy(unittest.TestCase):
    def setUp(self):
        import uuid
        self.db_url = f"sqlite:///file:mem_gtd_{uuid.uuid4().hex}?mode=memory&cache=shared"
        self.banco = ArmazenamentoGTD(self.db_url)

    def test_instancia_usa_backend_sqlalchemy(self):
        self.assertIsInstance(self.banco._backend, ArmazenamentoGTDSQLAlchemy)

    def test_crud_item(self):
        it = Item(
            titulo="Configurar banco plugavel",
            contexto="@trabalho",
            estado="inbox",
            nota="Suporte a SQLAlchemy e ODBC",
            metadados={"prioridade": "alta"},
        )
        self.banco.salvar_item(it)

        recuperado = self.banco.obter_item(it.id)
        self.assertIsNotNone(recuperado)
        self.assertEqual(recuperado.titulo, "Configurar banco plugavel")
        self.assertEqual(recuperado.contexto, "@trabalho")
        self.assertEqual(recuperado.metadados.get("prioridade"), "alta")

        # Atualizacao
        recuperado.estado = "proxima"
        recuperado.prazo = "2026-11-20"
        self.banco.salvar_item(recuperado)

        atualizado = self.banco.obter_item(it.id)
        self.assertEqual(atualizado.estado, "proxima")
        self.assertEqual(atualizado.prazo, "2026-11-20")

        # Listagem com filtros
        proximas = self.banco.listar_itens(estado="proxima")
        self.assertEqual(len(proximas), 1)
        inbox = self.banco.listar_itens(estado="inbox")
        self.assertEqual(len(inbox), 0)

        # Remocao
        self.assertTrue(self.banco.remover_item(it.id))
        self.assertIsNone(self.banco.obter_item(it.id))

    def test_buscar_item_por_ref(self):
        it = Item(
            titulo="Issue #66",
            ref_externa="github:Nextor:66",
            origem="github",
        )
        self.banco.salvar_item(it)

        achado = self.banco.buscar_item_por_ref("github:Nextor:66")
        self.assertIsNotNone(achado)
        self.assertEqual(achado.id, it.id)
        self.assertIsNone(self.banco.buscar_item_por_ref("inexistente"))

    def test_crud_projeto(self):
        p = Projeto(nome="Infraestrutura de Banco", descricao="SQLAlchemy + Docker + K8s")
        self.banco.salvar_projeto(p)

        recuperado = self.banco.obter_projeto(p.id)
        self.assertIsNotNone(recuperado)
        self.assertEqual(recuperado.nome, "Infraestrutura de Banco")

        projetos = self.banco.listar_projetos(estado="ativo")
        self.assertEqual(len(projetos), 1)

        self.assertTrue(self.banco.remover_projeto(p.id))
        self.assertIsNone(self.banco.obter_projeto(p.id))

    def test_crud_leitura_e_historico(self):
        leitura_obj = Leitura(
            titulo="Designing Data-Intensive Applications",
            autor="Martin Kleppmann",
            tipo="livro",
            paginas_total=500,
            fonte_url="https://example.org/ddia",
        )
        self.banco.salvar_leitura(leitura_obj)

        recuperada = self.banco.obter_leitura(leitura_obj.id)
        self.assertIsNotNone(recuperada)
        self.assertEqual(recuperada.titulo, "Designing Data-Intensive Applications")

        # Busca por url e titulo case-insensitive
        por_url = self.banco.buscar_leitura_por_url("https://example.org/ddia")
        self.assertIsNotNone(por_url)
        self.assertEqual(por_url.id, leitura_obj.id)

        por_tit = self.banco.buscar_leitura_por_titulo("  designing data-intensive applications  ")
        self.assertIsNotNone(por_tit)
        self.assertEqual(por_tit.id, leitura_obj.id)

        # Registra progresso diario
        tot1 = self.banco.registrar_progresso_leitura(leitura_obj.id, 20, "2026-11-15")
        self.assertEqual(tot1, 20)
        tot2 = self.banco.registrar_progresso_leitura(leitura_obj.id, 15, "2026-11-15")
        self.assertEqual(tot2, 35)

        self.assertEqual(self.banco.paginas_lidas_na_data("2026-11-15"), 35)
        self.assertEqual(self.banco.paginas_lidas_na_data("2026-11-14"), 0)

        # Remocao da leitura remove historico
        self.assertTrue(self.banco.remover_leitura(leitura_obj.id))
        self.assertIsNone(self.banco.obter_leitura(leitura_obj.id))
        self.assertEqual(self.banco.paginas_lidas_na_data("2026-11-15"), 0)

    def test_sincronizacao_notion(self):
        self.banco.salvar_mapeamento_notion("itens", "item_123", "notion_abc", "2026-11-15T10:00:00")
        mapa = self.banco.obter_mapeamento_notion("itens", "item_123")
        self.assertIsNotNone(mapa)
        self.assertEqual(mapa["id_notion"], "notion_abc")

        # Atualizacao
        self.banco.salvar_mapeamento_notion("itens", "item_123", "notion_xyz", "2026-11-15T12:00:00")
        atualizado = self.banco.obter_mapeamento_notion("itens", "item_123")
        self.assertEqual(atualizado["id_notion"], "notion_xyz")


class TestCoachSQLAlchemy(unittest.TestCase):
    def setUp(self):
        import uuid
        self.db_url = f"sqlite:///file:mem_coach_{uuid.uuid4().hex}?mode=memory&cache=shared"
        self.banco = ArmazenamentoCoach(self.db_url)

    def test_instancia_usa_backend_sqlalchemy(self):
        self.assertIsInstance(self.banco._backend, ArmazenamentoCoachSQLAlchemy)

    def test_salvar_e_obter_trilha_com_recursos(self):
        r1 = Recurso(trilha_id="t1", tipo="video", titulo="Video Introducao", ordem=1, duracao_min=20)
        r2 = Recurso(trilha_id="t1", tipo="artigo", titulo="Artigo Pratico", ordem=2, duracao_min=15, dominio_publico=True)
        trilha = Trilha(
            id="t1",
            titulo="Trilha de Arquitetura",
            habilidade="engenharia",
            recursos=[r1, r2],
        )
        self.banco.salvar_trilha(trilha)

        carregada = self.banco.obter_trilha("t1")
        self.assertIsNotNone(carregada)
        self.assertEqual(carregada.titulo, "Trilha de Arquitetura")
        self.assertEqual(len(carregada.recursos), 2)
        self.assertEqual(carregada.recursos[0].titulo, "Video Introducao")
        self.assertTrue(carregada.recursos[1].dominio_publico)

        lista = self.banco.listar_trilhas()
        self.assertEqual(len(lista), 1)

    def test_salvar_e_listar_planos(self):
        plano = Plano(trilha_id="t1", dias_semana=4, minutos_dia=45)
        self.banco.salvar_plano(plano)

        recuperado = self.banco.obter_plano(plano.id)
        self.assertIsNotNone(recuperado)
        self.assertEqual(recuperado.dias_semana, 4)
        self.assertEqual(recuperado.minutos_dia, 45)

        planos = self.banco.listar_planos(ativo_apenas=True)
        self.assertEqual(len(planos), 1)

    def test_acoes_e_pontuacao(self):
        acao = ProgressoAcao(
            plano_id="p1",
            recurso_id="r1",
            data="2026-11-15",
            estado="pendente",
        )
        self.banco.salvar_acao(acao)

        carregada = self.banco.obter_acao(acao.id)
        self.assertIsNotNone(carregada)
        self.assertEqual(carregada.estado, "pendente")

        por_rec = self.banco.obter_acao_por_recurso("p1", "r1")
        self.assertIsNotNone(por_rec)
        self.assertEqual(por_rec.id, acao.id)

        # Atualiza para feito com pontuacao
        carregada.estado = "feito"
        carregada.pontos = 50
        self.banco.salvar_acao(carregada)
        atualizada = self.banco.obter_acao(acao.id)
        self.assertEqual(atualizada.estado, "feito")
        self.assertEqual(atualizada.pontos, 50)

        # Pontuacao
        pts = Pontuacao(plano_id="p1", xp_total=250, nivel=3, streak=5, ultima_data="2026-11-15")
        self.banco.salvar_pontuacao(pts)
        pts_carregados = self.banco.obter_pontuacao("p1")
        self.assertIsNotNone(pts_carregados)
        self.assertEqual(pts_carregados.xp_total, 250)
        self.assertEqual(pts_carregados.nivel, 3)
        self.assertEqual(pts_carregados.streak, 5)

        # Upsert de pontuacao
        pts.xp_total = 300
        pts.streak = 6
        self.banco.salvar_pontuacao(pts)
        pts_atualizados = self.banco.obter_pontuacao("p1")
        self.assertEqual(pts_atualizados.xp_total, 300)
        self.assertEqual(pts_atualizados.streak, 6)


class TestConfiguracaoBancoPlugavel(unittest.TestCase):
    def test_com_db_url_no_config_usa_sqlalchemy(self):
        with mock.patch.object(config, "DB_URL", "sqlite:///:memory:"):
            banco_gtd = ArmazenamentoGTD()
            banco_coach = ArmazenamentoCoach()
            self.assertIsNotNone(banco_gtd._backend)
            self.assertIsNotNone(banco_coach._backend)
            self.assertIsInstance(banco_gtd._backend, ArmazenamentoGTDSQLAlchemy)
            self.assertIsInstance(banco_coach._backend, ArmazenamentoCoachSQLAlchemy)

    def test_sem_db_url_no_config_usa_sqlite_padrao(self):
        with mock.patch.object(config, "DB_URL", ""):
            banco_gtd = ArmazenamentoGTD()
            banco_coach = ArmazenamentoCoach()
            self.assertIsNone(banco_gtd._backend)
            self.assertIsNone(banco_coach._backend)
            self.assertIsNotNone(banco_gtd.caminho)
            self.assertIsNotNone(banco_coach.caminho)

    def test_obter_engine_sem_url_lanca_excecao(self):
        with mock.patch.object(config, "DB_URL", ""):
            with self.assertRaises(ValueError):
                obter_engine("")


if __name__ == "__main__":
    unittest.main()
