"""Testes dos metodos de produtividade intercambiaveis e timer Pomodoro."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from nextor.gtd.armazenamento import ArmazenamentoGTD
from nextor.gtd.metodos import (
    REGISTRO_METODOS,
    MetodoEisenhower,
    MetodoGTD,
    MetodoKanban,
    MetodoPARA,
    TimerPomodoro,
    listar_metodos,
    obter_metodo,
)
from nextor.gtd.modelos import Item


class TestMetodosProdutividade(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_gtd.db"
        self.storage = ArmazenamentoGTD(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_registro_e_listagem(self) -> None:
        metodos = listar_metodos()
        identificadores = [m["slug"] for m in metodos]
        self.assertIn("gtd", identificadores)
        self.assertIn("para", identificadores)
        self.assertIn("eisenhower", identificadores)
        self.assertIn("kanban", identificadores)

        metodo_gtd = obter_metodo("gtd")
        self.assertIsInstance(metodo_gtd, MetodoGTD)
        metodo_fallback = obter_metodo("metodo_inexistente")
        self.assertEqual(metodo_fallback.slug, "gtd")

    def test_metodo_gtd_classificacao_e_visao(self) -> None:
        metodo = MetodoGTD()
        item = Item(id="1", titulo="Comprar cafe")
        self.assertEqual(metodo.classificar(item), "inbox")

        item.estado = "proxima"
        self.assertEqual(metodo.classificar(item), "proxima")

        item.estado = "feito"
        self.assertEqual(metodo.classificar(item), "feito")

        itens = [
            Item(id="1", titulo="Inbox", estado="inbox"),
            Item(id="2", titulo="Fazer agora", estado="proxima"),
            Item(id="3", titulo="Concluido", estado="feito"),
        ]
        visao = metodo.visao_dia(itens)
        self.assertIn("itens_por_coluna", visao)
        self.assertEqual(len(visao["itens_por_coluna"]["proxima"]), 1)
        self.assertEqual(len(visao["itens_por_coluna"]["inbox"]), 1)
        self.assertEqual(len(visao["itens_por_coluna"]["feito"]), 1)

    def test_metodo_para_classificacao(self) -> None:
        metodo = MetodoPARA()
        item = Item(id="1", titulo="Documento", metadados={"balde_para": "projetos"})
        self.assertEqual(metodo.classificar(item), "projetos")

        item2 = Item(id="2", titulo="Sem metadado")
        self.assertEqual(metodo.classificar(item2), "inbox")

        item3 = Item(id="3", titulo="Referencia", metadados={"balde_para": "recursos"})
        self.assertEqual(metodo.classificar(item3), "recursos")

    def test_metodo_eisenhower_classificacao(self) -> None:
        metodo = MetodoEisenhower()
        item1 = Item(id="1", titulo="Crise", metadados={"urgente": True, "importante": True})
        self.assertEqual(metodo.classificar(item1), "fazer")

        item2 = Item(id="2", titulo="Estrategia", metadados={"urgente": False, "importante": True})
        self.assertEqual(metodo.classificar(item2), "agendar")

        item3 = Item(id="3", titulo="Interrupcao", metadados={"urgente": True, "importante": False})
        self.assertEqual(metodo.classificar(item3), "delegar")

        item4 = Item(id="4", titulo="Distracao", metadados={"urgente": False, "importante": False})
        self.assertEqual(metodo.classificar(item4), "eliminar")

        item5 = Item(id="5", titulo="Feito", estado="feito", metadados={"urgente": True, "importante": True})
        self.assertEqual(metodo.classificar(item5), "feito")

    def test_metodo_kanban_wip_limit(self) -> None:
        metodo = MetodoKanban(limite_wip=2)
        self.assertTrue(metodo.validar_wip(qtd_fazendo=0))
        self.assertTrue(metodo.validar_wip(qtd_fazendo=1))
        self.assertFalse(metodo.validar_wip(qtd_fazendo=2))
        self.assertFalse(metodo.validar_wip(qtd_fazendo=3))

        item_fazendo = Item(id="k1", titulo="Tarefa", metadados={"coluna_kanban": "fazendo"})
        self.assertEqual(metodo.classificar(item_fazendo), "fazendo")

        item_afazer = Item(id="k2", titulo="Tarefa 2", metadados={"coluna_kanban": "a_fazer"})
        self.assertEqual(metodo.classificar(item_afazer), "a_fazer")

    def test_troca_de_metodo_sem_perda_de_dados(self) -> None:
        item = Item(
            id="task-1",
            titulo="Escrever relatorio",
            estado="proxima",
            metadados={
                "coluna_kanban": "fazendo",
                "urgente": True,
                "importante": True,
                "balde_para": "projetos",
            },
        )
        self.storage.salvar_item(item)

        recuperado = self.storage.obter_item("task-1")
        self.assertIsNotNone(recuperado)

        metodo_gtd = obter_metodo("gtd")
        metodo_kanban = obter_metodo("kanban")
        metodo_eisenhower = obter_metodo("eisenhower")
        metodo_para = obter_metodo("para")

        self.assertEqual(metodo_gtd.classificar(recuperado), "proxima")
        self.assertEqual(metodo_kanban.classificar(recuperado), "fazendo")
        self.assertEqual(metodo_eisenhower.classificar(recuperado), "fazer")
        self.assertEqual(metodo_para.classificar(recuperado), "projetos")


class TestTimerPomodoro(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_gtd.db"
        self.storage = ArmazenamentoGTD(self.db_path)
        self.timer = TimerPomodoro(duracao_foco_min=25, pausa_curta_min=5)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_ciclo_pomodoro(self) -> None:
        item = Item(id="pomo-1", titulo="Focar no codigo")
        self.storage.salvar_item(item)

        estado = self.timer.iniciar(item_id="pomo-1")
        self.assertTrue(estado["ativo"])
        self.assertEqual(estado["modo"], "foco")
        self.assertEqual(estado["item_id"], "pomo-1")

        estado_pausado = self.timer.pausar()
        self.assertTrue(estado_pausado["pausado"])

        estado_concluido = self.timer.concluir(db=self.storage)
        self.assertEqual(estado_concluido["status"], "concluido")
        self.assertEqual(estado_concluido["ciclos_concluidos"], 1)

        item_atualizado = self.storage.obter_item("pomo-1")
        self.assertIsNotNone(item_atualizado)
        self.assertEqual(item_atualizado.obter_meta("pomodoros_concluidos"), 1)

        estado_parado = self.timer.parar()
        self.assertFalse(estado_parado["ativo"])
        self.assertIsNone(estado_parado["item_id"])


if __name__ == "__main__":
    unittest.main()
