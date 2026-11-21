"""Metodos plugaveis (Issue #45): registro de metodo novo, mover entre colunas, WIP e Pomodoro."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Dict, List
from unittest import mock

os.environ.setdefault("NEXTOR_VOZ_SAIDA", "nenhuma")

from nextor import config, mcp_server, servico  # noqa: E402
from nextor.gtd.armazenamento import ArmazenamentoGTD  # noqa: E402
from nextor.gtd.configuracao import carregar_config, salvar_config  # noqa: E402
from nextor.gtd.metodos import (  # noqa: E402
    REGISTRO_METODOS,
    ColunaInvalida,
    LimiteWIPExcedido,
    Metodo,
    MetodoEisenhower,
    MetodoGTD,
    MetodoKanban,
    MetodoPARA,
    TimerPomodoro,
    listar_metodos,
    obter_metodo,
    registrar_metodo,
    remover_metodo,
)
from nextor.gtd.metodos.operacoes import ItemNaoEncontrado, montar_visao, mover_item  # noqa: E402
from nextor.gtd.modelos import Item  # noqa: E402


class MetodoTresTarefas(Metodo):
    """Metodo de exemplo: tres tarefas do dia, o resto espera."""

    nome = "Tres Tarefas"
    slug = "tres_tarefas"
    descricao = "Escolha tres tarefas para hoje."

    def colunas(self) -> List[Dict[str, str]]:
        return [
            {"id": "espera", "titulo": "Espera", "descricao": "Fora do dia"},
            {"id": "hoje", "titulo": "Hoje", "descricao": "As tres do dia"},
            {"id": "feito", "titulo": "Feito", "descricao": "Concluidas"},
        ]

    def classificar(self, item: Item) -> str:
        if item.estado == "feito":
            return "feito"
        return item.obter_meta("coluna_tres_tarefas") or "espera"


class TestRegistroPlugavel(unittest.TestCase):
    def tearDown(self) -> None:
        remover_metodo("tres_tarefas")

    def test_registrar_metodo_novo_aparece_no_catalogo(self) -> None:
        registrar_metodo(MetodoTresTarefas)
        self.assertIn("tres_tarefas", [m["slug"] for m in listar_metodos()])
        self.assertIsInstance(obter_metodo("tres_tarefas"), MetodoTresTarefas)

    def test_registro_recusa_duplicado_slug_invalido_e_nao_metodo(self) -> None:
        registrar_metodo(MetodoTresTarefas)
        with self.assertRaises(ValueError):
            registrar_metodo(MetodoTresTarefas)
        registrar_metodo(MetodoTresTarefas, substituir=True)

        class SlugRuim(MetodoTresTarefas):
            slug = "Slug Ruim!"

        with self.assertRaises(ValueError):
            registrar_metodo(SlugRuim)
        with self.assertRaises(TypeError):
            registrar_metodo(object())  # type: ignore[arg-type]

    def test_metodo_padrao_nao_pode_ser_removido(self) -> None:
        self.assertFalse(remover_metodo("gtd"))
        self.assertIn("gtd", REGISTRO_METODOS)

    def test_mover_padrao_do_metodo_novo_usa_campo_proprio(self) -> None:
        metodo = registrar_metodo(MetodoTresTarefas)
        item = Item(id="x", titulo="Ler", estado="proxima")
        metodo.mover(item, "hoje")
        self.assertEqual(item.obter_meta("coluna_tres_tarefas"), "hoje")
        self.assertEqual(metodo.classificar(item), "hoje")
        metodo.mover(item, "feito")
        self.assertEqual(item.estado, "feito")
        self.assertIsNotNone(item.concluido_em)
        metodo.mover(item, "hoje")
        self.assertEqual(item.estado, "proxima")
        self.assertIsNone(item.concluido_em)

    def test_catalogo_descreve_colunas_campos_e_regras(self) -> None:
        cat = {m["slug"]: m for m in listar_metodos({"kanban_wip_limite": 5})}
        self.assertEqual(set(cat) >= {"gtd", "para", "eisenhower", "kanban"}, True)
        self.assertEqual(cat["kanban"]["regras"]["limite_wip"], 5)
        self.assertIsNone(cat["para"]["coluna_concluida"])
        for m in cat.values():
            self.assertTrue(m["colunas"])
            self.assertIn("campos_extra", m)


class TestMoverPorMetodo(unittest.TestCase):
    def test_coluna_invalida(self) -> None:
        with self.assertRaises(ColunaInvalida):
            MetodoGTD().mover(Item(titulo="a"), "nao_existe")

    def test_gtd_move_pelo_estado(self) -> None:
        item = Item(titulo="Ligar", estado="inbox")
        MetodoGTD().mover(item, "aguardando")
        self.assertEqual(item.estado, "aguardando")
        MetodoGTD().mover(item, "feito")
        self.assertEqual(item.estado, "feito")
        self.assertIsNotNone(item.concluido_em)

    def test_eisenhower_quadrante_manual_e_coerente(self) -> None:
        item = Item(titulo="Plano", metadados={"urgente": True, "importante": True})
        metodo = MetodoEisenhower()
        metodo.mover(item, "agendar")
        self.assertEqual(metodo.classificar(item), "agendar")
        self.assertFalse(item.obter_meta("urgente"))
        self.assertTrue(item.obter_meta("importante"))

    def test_para_arquivar_nao_conclui_e_tirar_de_feito_reabre(self) -> None:
        metodo = MetodoPARA()
        item = Item(titulo="Curso", estado="proxima")
        metodo.mover(item, "arquivos")
        self.assertEqual(item.estado, "proxima")
        self.assertEqual(metodo.classificar(item), "arquivos")

        feito = Item(titulo="Velho", estado="feito")
        metodo.mover(feito, "recursos")
        self.assertEqual(feito.estado, "proxima")
        self.assertEqual(metodo.classificar(feito), "recursos")

    def test_kanban_respeita_limite_wip(self) -> None:
        metodo = MetodoKanban(limite_wip=2)
        itens = [Item(id=f"k{i}", titulo=f"T{i}") for i in range(3)]
        metodo.mover(itens[0], "fazendo", itens)
        metodo.mover(itens[1], "fazendo", itens)
        with self.assertRaises(LimiteWIPExcedido):
            metodo.mover(itens[2], "fazendo", itens)
        self.assertEqual(metodo.classificar(itens[2]), "a_fazer")
        # Mover de novo um item que ja esta em fazendo nao conta duas vezes
        metodo.mover(itens[0], "fazendo", itens)
        # Concluir libera vaga
        metodo.mover(itens[0], "feito", itens)
        self.assertEqual(itens[0].estado, "feito")
        metodo.mover(itens[2], "fazendo", itens)
        self.assertEqual(metodo.classificar(itens[2]), "fazendo")

    def test_kanban_limite_vem_da_config(self) -> None:
        metodo = obter_metodo("kanban", {"kanban_wip_limite": 1})
        self.assertEqual(metodo.limite_wip, 1)
        self.assertEqual(obter_metodo("kanban").limite_wip, 3)
        self.assertEqual(MetodoKanban(limite_wip="x").limite_wip, 3)  # type: ignore[arg-type]

    def test_estado_feito_vale_em_todos_os_metodos(self) -> None:
        item = Item(titulo="Relatorio", metadados={"coluna_kanban": "fazendo", "quadrante": "fazer"})
        MetodoGTD().mover(item, "feito")
        self.assertEqual(MetodoKanban().classificar(item), "feito")
        self.assertEqual(MetodoEisenhower().classificar(item), "feito")
        self.assertEqual(MetodoPARA().classificar(item), "arquivos")
        MetodoGTD().mover(item, "proxima")
        self.assertEqual(MetodoKanban().classificar(item), "fazendo")


class TestGTDVisaoCompleta(unittest.TestCase):
    def test_visao_gtd_traz_contextos_projetos_e_revisao(self) -> None:
        itens = [
            Item(id="1", titulo="A", estado="proxima", contexto="@casa", projeto_id="p1"),
            Item(id="2", titulo="B", estado="aguardando", projeto_id="p2"),
            Item(id="3", titulo="C", estado="inbox"),
            Item(id="4", titulo="D", estado="proxima", contexto="@casa"),
        ]
        visao = MetodoGTD().visao_dia(itens)
        self.assertEqual(visao["contextos"], {"@casa": 2})
        self.assertEqual(visao["projetos"]["p1"], {"abertas": 1, "proximas": 1})
        self.assertEqual(visao["revisao"]["projetos_sem_proxima_acao"], ["p2"])
        self.assertEqual(visao["revisao"]["inbox_para_processar"], 1)
        self.assertEqual(visao["metodo_descricao"], MetodoGTD.descricao)


class TestOperacoesPersistidas(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = ArmazenamentoGTD(Path(self.tmp.name) / "gtd.db")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_trocar_metodo_e_mover_nao_perde_campos_dos_outros(self) -> None:
        self.db.salvar_item(Item(id="t1", titulo="Escrever", estado="proxima", metadados={"balde_para": "projetos"}))
        cfg = {"metodo_ativo": "kanban", "kanban_wip_limite": 2}
        mover_item("t1", "fazendo", db=self.db, cfg=cfg)
        mover_item("t1", "fazer", db=self.db, cfg=cfg, slug="eisenhower")

        salvo = self.db.obter_item("t1")
        self.assertEqual(salvo.obter_meta("balde_para"), "projetos")
        self.assertEqual(salvo.obter_meta("coluna_kanban"), "fazendo")
        self.assertEqual(salvo.obter_meta("quadrante"), "fazer")
        for slug, esperado in (("gtd", "proxima"), ("para", "projetos"), ("kanban", "fazendo"), ("eisenhower", "fazer")):
            visao = montar_visao(db=self.db, cfg=cfg, slug=slug)
            ids = [i["id"] for i in visao["itens_por_coluna"][esperado]]
            self.assertIn("t1", ids, slug)

    def test_item_inexistente(self) -> None:
        with self.assertRaises(ItemNaoEncontrado):
            mover_item("nada", "proxima", db=self.db, cfg={})

    def test_wip_considera_itens_do_banco(self) -> None:
        cfg = {"metodo_ativo": "kanban", "kanban_wip_limite": 1}
        self.db.salvar_item(Item(id="a", titulo="A"))
        self.db.salvar_item(Item(id="b", titulo="B"))
        mover_item("a", "fazendo", db=self.db, cfg=cfg)
        with self.assertRaises(LimiteWIPExcedido):
            mover_item("b", "fazendo", db=self.db, cfg=cfg)


class TestPomodoroRetomar(unittest.TestCase):
    def test_retomar_continua_de_onde_parou(self) -> None:
        timer = TimerPomodoro()
        timer.iniciar(duracao_min=10)
        timer.pausar()
        restantes = timer.segundos_restantes
        estado = timer.retomar()
        self.assertFalse(estado["pausado"])
        self.assertTrue(estado["ativo"])
        self.assertLessEqual(estado["segundos_restantes"], restantes)
        self.assertGreater(estado["segundos_restantes"], restantes - 5)

    def test_retomar_sem_sessao_nao_faz_nada(self) -> None:
        self.assertFalse(TimerPomodoro().retomar()["ativo"])


class TestEndpointsMetodos(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "gtd.db"
        self.config_path = Path(self.tmp.name) / "config.json"
        self.token = "nxt_mestre_seguro_123456789012345"
        self.patches = [
            mock.patch.object(config, "TOKEN", self.token),
            mock.patch.object(config, "GTD_DB", self.db_path),
            mock.patch.dict(os.environ, {"NEXTOR_GTD_CONFIG_JSON": str(self.config_path)}),
        ]
        for p in self.patches:
            p.start()
        self.headers = {"X-Nextor-Token": self.token, "Content-Type": "application/json"}
        self.client = servico.app.test_client()
        self.db = ArmazenamentoGTD(self.db_path)
        from nextor.gtd.metodos import pomodoro
        pomodoro.parar()

    def tearDown(self) -> None:
        from nextor.gtd.metodos import pomodoro
        pomodoro.parar()
        remover_metodo("tres_tarefas")
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def _mover(self, **corpo):
        return self.client.post("/gtd/visao/mover", headers=self.headers, data=json.dumps(corpo))

    def test_rotas_novas_exigem_token(self) -> None:
        self.assertEqual(self.client.get("/gtd/metodos").status_code, 401)
        self.assertEqual(self.client.post("/gtd/visao/mover", json={}).status_code, 401)

    def test_catalogo_lista_metodo_registrado_e_ativo(self) -> None:
        registrar_metodo(MetodoTresTarefas)
        dados = self.client.get("/gtd/metodos", headers=self.headers).get_json()
        self.assertEqual(dados["ativo"], "gtd")
        self.assertIn("tres_tarefas", [m["slug"] for m in dados["metodos"]])
        # E pode virar o metodo ativo da config
        resp = self.client.put("/gtd/config", headers=self.headers, data=json.dumps({"metodo_ativo": "tres_tarefas"}))
        self.assertEqual(resp.status_code, 200)
        visao = self.client.get("/gtd/visao", headers=self.headers).get_json()
        self.assertEqual(visao["metodo"], "tres_tarefas")

    def test_visao_metodo_desconhecido_e_400(self) -> None:
        resp = self.client.get("/gtd/visao?metodo=fantasma", headers=self.headers)
        self.assertEqual(resp.status_code, 400)

    def test_mover_com_wip_da_config(self) -> None:
        salvar_config({"metodo_ativo": "kanban", "kanban_wip_limite": 1})
        self.db.salvar_item(Item(id="m1", titulo="Um"))
        self.db.salvar_item(Item(id="m2", titulo="Dois"))

        ok = self._mover(item_id="m1", coluna="fazendo")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.get_json()["coluna"], "fazendo")

        cheio = self._mover(item_id="m2", coluna="fazendo")
        self.assertEqual(cheio.status_code, 409)
        self.assertEqual(cheio.get_json()["codigo"], "limite_wip")

        visao = self.client.get("/gtd/visao", headers=self.headers).get_json()
        self.assertEqual(visao["limite_wip"], 1)
        self.assertEqual(visao["regras"]["limite_wip"], 1)

    def test_mover_erros_de_entrada(self) -> None:
        self.db.salvar_item(Item(id="e1", titulo="E"))
        self.assertEqual(self._mover(item_id="e1").status_code, 400)
        self.assertEqual(self._mover(item_id="e1", coluna="xyz").status_code, 400)
        self.assertEqual(self._mover(item_id="nada", coluna="proxima").status_code, 404)
        self.assertEqual(self._mover(item_id="e1", coluna="proxima", metodo="fantasma").status_code, 400)
        resp = self.client.post("/gtd/visao/mover", headers=self.headers, data="[]")
        self.assertEqual(resp.status_code, 400)

    def test_pomodoro_usa_duracao_da_config_retoma_e_pode_ser_desligado(self) -> None:
        salvar_config({"pomodoro_duracao_min": 50})
        dados = self.client.post("/gtd/pomodoro/iniciar", headers=self.headers, data="{}").get_json()
        self.assertGreater(dados["segundos_restantes"], 49 * 60)

        self.client.post("/gtd/pomodoro/pausar", headers=self.headers)
        retomado = self.client.post("/gtd/pomodoro/retomar", headers=self.headers, data="{}").get_json()
        self.assertTrue(retomado["ativo"])
        self.assertFalse(retomado["pausado"])

        self.client.post("/gtd/pomodoro/parar", headers=self.headers)
        salvar_config({"pomodoro_ativo": False})
        self.assertFalse(carregar_config()["pomodoro_ativo"])
        resp = self.client.post("/gtd/pomodoro/iniciar", headers=self.headers, data="{}")
        self.assertEqual(resp.status_code, 409)
        visao = self.client.get("/gtd/visao", headers=self.headers).get_json()
        self.assertFalse(visao["pomodoro_ativo"])

    def test_config_limita_wip_e_duracao(self) -> None:
        cfg = salvar_config({"kanban_wip_limite": 999, "pomodoro_duracao_min": 0})
        self.assertEqual(cfg["kanban_wip_limite"], 50)
        self.assertEqual(cfg["pomodoro_duracao_min"], 1)

    def test_mcp_trocar_e_mover(self) -> None:
        self.assertIn("desconhecido", mcp_server.gtd_trocar_metodo("fantasma"))
        self.assertIn("Kanban", mcp_server.gtd_trocar_metodo("kanban"))
        self.db.salvar_item(Item(id="abcd1234", titulo="Revisar PR", estado="proxima"))
        resposta = mcp_server.gtd_mover_item("abcd", "fazendo")
        self.assertIn("fazendo", resposta)
        self.assertEqual(self.db.obter_item("abcd1234").obter_meta("coluna_kanban"), "fazendo")
        self.assertIn("Nao movido", mcp_server.gtd_mover_item("abcd1234", "inexistente"))


if __name__ == "__main__":
    unittest.main()
