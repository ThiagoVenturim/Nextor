"""Testes offline da ordem sugerida do dia, contextos e comandos do painel GTD (Issue #43)."""
import os
from datetime import date, datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest import mock

os.environ["NEXTOR_VOZ_SAIDA"] = "nenhuma"

from nextor import config, servico, telegram_bot
from nextor.gtd import (
    agenda_do_dia,
    buscar_item_por_prefixo,
    capturar,
    contar_por_contexto,
    processar,
)
from nextor.gtd.armazenamento import ArmazenamentoGTD
from nextor.gtd.configuracao import carregar_config, salvar_config
from nextor.gtd.ordem_dia import ROTINA_PADRAO, obter_rotina, parsear_rotina, sugerir_ordem_do_dia

ROTINA_TESTE = "08:00-12:00 @faculdade; 13:00-18:00 @trabalho; 18:30-19:30 @academia; 21:00-21:30 @leitura"


class BaseTmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.caminho_db = Path(self.tmp.name) / "gtd.db"
        self.caminho_cfg = Path(self.tmp.name) / "config.json"
        self.patches = [
            mock.patch.object(config, "GTD_DB", self.caminho_db),
            mock.patch.object(config, "GTD_ROTINA", ""),
            mock.patch.dict(os.environ, {"NEXTOR_GTD_CONFIG_JSON": str(self.caminho_cfg)}),
            mock.patch("nextor.agenda.eventos_hoje", return_value=[]),
        ]
        for p in self.patches:
            p.start()
        self.banco = ArmazenamentoGTD(self.caminho_db)

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def acao(self, titulo, contexto, prazo=None, energia="media"):
        item = capturar(titulo, contexto=contexto, prazo=prazo, energia=energia, db=self.banco)
        return processar(item.id, "proxima", db=self.banco)


class TestRotina(BaseTmp):
    def test_parsear_texto_ordena_e_descarta_invalidos(self):
        blocos = parsear_rotina(
            "13:00-18:00 @trabalho; 08:00-12:00 faculdade\n25:00-26:00 @casa; 10:00-09:00 @casa; "
            "09:00-10:00 @inexistente; lixo"
        )
        self.assertEqual(blocos, [
            {"inicio": "08:00", "fim": "12:00", "contexto": "@faculdade"},
            {"inicio": "13:00", "fim": "18:00", "contexto": "@trabalho"},
        ])

    def test_parsear_lista_de_dicionarios(self):
        blocos = parsear_rotina([{"inicio": "18:30", "fim": "19:30", "contexto": "@academia"}, {"inicio": "x"}])
        self.assertEqual(blocos, [{"inicio": "18:30", "fim": "19:30", "contexto": "@academia"}])

    def test_prioridade_argumento_config_env_padrao(self):
        self.assertEqual(obter_rotina(cfg={}), parsear_rotina(ROTINA_PADRAO))
        with mock.patch.object(config, "GTD_ROTINA", "07:00-08:00 @casa"):
            self.assertEqual(obter_rotina(cfg={})[0]["contexto"], "@casa")
            cfg = {"rotina": [{"inicio": "06:00", "fim": "07:00", "contexto": "@academia"}]}
            self.assertEqual(obter_rotina(cfg=cfg)[0]["contexto"], "@academia")
            self.assertEqual(obter_rotina("05:00-06:00 @leitura", cfg=cfg)[0]["contexto"], "@leitura")

    def test_salvar_config_valida_rotina(self):
        salvo = salvar_config({"rotina": "08:00-12:00 @faculdade; invalido"})
        self.assertEqual(salvo["rotina"], [{"inicio": "08:00", "fim": "12:00", "contexto": "@faculdade"}])
        self.assertEqual(carregar_config()["rotina"], salvo["rotina"])
        self.assertEqual(salvar_config({"rotina": ""})["rotina"], [])


class TestOrdemDoDia(BaseTmp):
    def setUp(self):
        super().setUp()
        self.hoje = date.today()
        self.agora = datetime.combine(self.hoje, datetime.min.time()).replace(hour=7)

    def ordem(self, **kw):
        kw.setdefault("rotina", ROTINA_TESTE)
        kw.setdefault("eventos", [])
        kw.setdefault("agora", self.agora)
        kw.setdefault("cfg", {})
        return sugerir_ordem_do_dia(db=self.banco, **kw)

    def bloco(self, res, contexto):
        return next(e for e in res["linha_do_tempo"] if e["tipo"] == "contexto" and e["contexto"] == contexto)

    def test_acoes_vao_para_o_bloco_do_contexto_com_atrasadas_primeiro(self):
        ontem = (self.hoje - timedelta(days=1)).isoformat()
        self.acao("Ler capitulo 3", "@faculdade")
        self.acao("Entregar trabalho", "@faculdade", prazo=ontem)
        self.acao("Revisar PR", "@trabalho")
        res = self.ordem()
        fac = self.bloco(res, "@faculdade")
        self.assertEqual([a["titulo"] for a in fac["acoes"]], ["Entregar trabalho", "Ler capitulo 3"])
        self.assertTrue(fac["acoes"][0]["atrasada"])
        self.assertEqual(self.bloco(res, "@trabalho")["acoes"][0]["titulo"], "Revisar PR")
        self.assertEqual(res["proximo_passo"]["titulo"], "Entregar trabalho")
        self.assertEqual(res["proximo_passo"]["inicio"], "08:00")
        self.assertIn("Ordem sugerida: 08:00 @faculdade", res["resumo"])

    def test_evento_que_cobre_o_bloco_marca_ocupado_e_urgente_vai_para_sem_bloco(self):
        self.acao("Treino de perna", "@academia", prazo=self.hoje.isoformat())
        ini = datetime.combine(self.hoje, datetime.min.time()).replace(hour=18)
        eventos = [{"titulo": "Reuniao do grupo", "inicio": ini, "fim": ini + timedelta(hours=2), "eh_reuniao": True}]
        res = self.ordem(eventos=eventos)
        academia = self.bloco(res, "@academia")
        self.assertTrue(academia["ocupado_pela_agenda"])
        self.assertEqual(academia["acoes"], [])
        self.assertEqual([a["titulo"] for a in res["sem_bloco"]], ["Treino de perna"])
        evento = next(e for e in res["linha_do_tempo"] if e["tipo"] == "evento")
        self.assertEqual((evento["inicio"], evento["fim"]), ("18:00", "20:00"))
        inicios = [e["inicio"] for e in res["linha_do_tempo"]]
        self.assertEqual(inicios, sorted(inicios))

    def test_evento_de_dia_inteiro_nao_ocupa_bloco(self):
        res = self.ordem(eventos=[{"titulo": "Feriado", "dia_inteiro": True, "inicio": self.hoje}])
        self.assertFalse(any(e["tipo"] == "evento" for e in res["linha_do_tempo"]))
        self.assertFalse(self.bloco(res, "@faculdade")["ocupado_pela_agenda"])

    def test_qualquer_preenche_blocos_e_contexto_sem_bloco_fica_de_fora(self):
        self.acao("Pagar boleto", "@qualquer")
        self.acao("Arrumar armario", "@casa")
        res = self.ordem()
        self.assertEqual(self.bloco(res, "@faculdade")["acoes"][0]["titulo"], "Pagar boleto")
        self.assertEqual([a["titulo"] for a in res["sem_bloco"]], ["Arrumar armario"])

    def test_limite_de_acoes_por_bloco(self):
        for n in range(5):
            self.acao(f"Tarefa {n}", "@trabalho")
        res = self.ordem(acoes_por_bloco=2)
        self.assertEqual(len(self.bloco(res, "@trabalho")["acoes"]), 2)

    def test_blocos_passados_e_proximo_passo(self):
        self.acao("Revisar PR", "@trabalho")
        self.acao("Ler capitulo 3", "@faculdade")
        agora = self.agora.replace(hour=12, minute=30)
        res = self.ordem(agora=agora)
        self.assertTrue(self.bloco(res, "@faculdade")["passado"])
        self.assertEqual(res["proximo_passo"]["titulo"], "Revisar PR")

    def test_bloco_de_leitura_mostra_paginas_faltando(self):
        with mock.patch.object(config, "LEITURA_META_DIARIA", 20):
            self.banco.registrar_progresso_leitura("geral", 5)
            res = self.ordem()
        self.assertEqual(self.bloco(res, "@leitura")["leitura_faltam_paginas"], 15)

    def test_agenda_do_dia_inclui_ordem_e_respeita_agente_desligado(self):
        self.acao("Revisar PR", "@trabalho")
        res = agenda_do_dia(db=self.banco)
        self.assertIsNotNone(res["ordem_sugerida"])
        self.assertIn("linha_do_tempo", res["ordem_sugerida"])
        salvar_config({"agentes": {"sugerir_ordem_dia": False}})
        self.assertIsNone(agenda_do_dia(db=self.banco)["ordem_sugerida"])


class TestContextosEPrefixo(BaseTmp):
    def test_contar_por_contexto(self):
        self.acao("A", "@casa")
        self.acao("B", "@casa")
        self.acao("C", "@leitura")
        capturar("Ainda no inbox", contexto="@casa", db=self.banco)
        contagem = contar_por_contexto(db=self.banco)
        self.assertEqual(contagem["@casa"], 2)
        self.assertEqual(contagem["@leitura"], 1)
        self.assertEqual(contagem["@academia"], 0)

    def test_buscar_item_por_prefixo(self):
        item = self.acao("A", "@casa")
        self.assertEqual(buscar_item_por_prefixo(item.id[:6], db=self.banco).id, item.id)
        self.assertEqual(buscar_item_por_prefixo(item.id, db=self.banco).id, item.id)
        self.assertIsNone(buscar_item_por_prefixo(item.id[:3], db=self.banco))
        self.assertIsNone(buscar_item_por_prefixo("zzzzzz", db=self.banco))


class TestServicoOrdem(BaseTmp):
    def setUp(self):
        super().setUp()
        self.token = "nxt_mestre_seguro_123456789012345"
        self.patch_token = mock.patch.object(config, "TOKEN", self.token)
        self.patch_token.start()
        self.client = servico.app.test_client()
        self.h = {"X-Nextor-Token": self.token}

    def tearDown(self):
        self.patch_token.stop()
        super().tearDown()

    def test_rotas_novas_exigem_token(self):
        for rota in ("/gtd/ordem", "/gtd/contextos"):
            self.assertEqual(self.client.get(rota).status_code, 401)

    def test_ordem_e_contextos(self):
        self.acao("Revisar PR", "@trabalho")
        res = self.client.get("/gtd/ordem", headers=self.h)
        self.assertEqual(res.status_code, 200)
        dados = res.get_json()
        self.assertTrue(dados["ok"])
        self.assertIn("linha_do_tempo", dados)
        self.assertIn("@trabalho", dados["rotina_texto"])
        res = self.client.get("/gtd/contextos", headers=self.h)
        self.assertEqual(res.get_json()["contextos"]["@trabalho"], 1)

    def test_ordem_desligada_nos_ajustes(self):
        salvar_config({"agentes": {"sugerir_ordem_dia": False}})
        dados = self.client.get("/gtd/ordem", headers=self.h).get_json()
        self.assertTrue(dados["desligado"])

    def test_painel_gtd_bloqueado_fora_da_rede_local_ou_vpn(self):
        publico = {"REMOTE_ADDR": "8.8.8.8"}
        for rota in ("/gtd", "/gtd/ordem", "/gtd/itens"):
            res = self.client.get(rota, headers=self.h, environ_base=publico)
            self.assertEqual(res.status_code, 403, rota)
        vpn = {"REMOTE_ADDR": "100.100.1.2"}
        self.assertEqual(self.client.get("/gtd/ordem", headers=self.h, environ_base=vpn).status_code, 200)
        lan = {"REMOTE_ADDR": "192.168.0.20"}
        self.assertEqual(self.client.get("/gtd/contextos", headers=self.h, environ_base=lan).status_code, 200)

    def test_webhook_github_nao_passa_pelo_filtro_de_rede(self):
        with mock.patch.object(config, "GITHUB_WEBHOOK_SECRET", "", create=True):
            res = self.client.post("/gtd/webhook/github", data=b"{}", environ_base={"REMOTE_ADDR": "8.8.8.8"})
        self.assertEqual(res.status_code, 404)


class TestTelegramPainel(BaseTmp):
    def test_proximas_contexto_e_feito(self):
        item = self.acao("Comprar racao", "@casa")
        self.acao("Revisar PR", "@trabalho")
        resp = telegram_bot.tratar_comando("/proximas", "@casa")
        self.assertIn("Comprar racao", resp)
        self.assertNotIn("Revisar PR", resp)
        self.assertIn(item.id[:6], resp)
        self.assertIn("Contexto desconhecido", telegram_bot.tratar_comando("/proximas", "@marte"))
        self.assertIn("Comprar racao", telegram_bot.tratar_comando("/contexto", "casa"))

        resp = telegram_bot.tratar_comando("/feito", item.id[:6])
        self.assertEqual(resp, "Feito: Comprar racao")
        self.assertEqual(self.banco.obter_item(item.id).estado, "feito")
        self.assertIn("Nenhuma acao", telegram_bot.tratar_comando("/feito", "zzzzzz"))
        self.assertIn("Uso:", telegram_bot.tratar_comando("/feito", ""))

    def test_contextos_ordem_revisao_e_sufixo_do_bot(self):
        self.acao("Revisar PR", "@trabalho")
        self.assertIn("@trabalho: 1", telegram_bot.tratar_comando("/contextos@NextorBot", ""))
        with mock.patch.object(config, "GTD_ROTINA", "00:00-23:59 @trabalho"):
            resp = telegram_bot.tratar_comando("/ordem", "")
        self.assertIn("Revisar PR", resp)
        self.assertIn("@trabalho", resp)
        self.assertIn("Revisao semanal", telegram_bot.tratar_comando("/revisao", ""))

    def test_ajuda_lista_comandos_gtd(self):
        resp = telegram_bot.tratar_comando("/ajuda", "")
        for cmd in ("/inbox", "/ordem", "/contextos", "/proximas", "/feito", "/revisao"):
            self.assertIn(cmd, resp)


if __name__ == "__main__":
    unittest.main()
