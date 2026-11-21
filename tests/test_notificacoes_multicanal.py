"""Testes offline das notificacoes multicanal (Issue #46).

Nenhum teste usa rede: todos os canais recebem clientes HTTP ou enviadores mockados,
e urllib.request.urlopen e bloqueado para garantir isso.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import unittest
from datetime import date, time
from pathlib import Path
from unittest import mock

os.environ["NEXTOR_VOZ_SAIDA"] = "nenhuma"

from nextor import config, servico  # noqa: E402
from nextor.gtd.armazenamento import ArmazenamentoGTD  # noqa: E402
from nextor.gtd.configuracao import carregar_config, salvar_config  # noqa: E402
from nextor.gtd.modelos import Item  # noqa: E402
from nextor.notificacoes import (  # noqa: E402
    CanalDiscord,
    CanalTelegram,
    CanalVoz,
    CanalWebPush,
    CanalWhatsApp,
    InscricoesPush,
    RoteadorNotificacoes,
    formatar_titulo,
    validar_inscricao,
)
from nextor.notificacoes import avisos  # noqa: E402
from nextor.notificacoes import roteador_notificacoes as mod_roteador  # noqa: E402

SEGREDO = "segredo-super-secreto-123"
ENV_CANAIS = (
    "DISCORD_WEBHOOK_URL", "DISCORD_BOT_TOKEN", "DISCORD_CANAL_ID",
    "WHATSAPP_API_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_DESTINATARIO", "WHATSAPP_TEMPLATE",
    "VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_SUBSCRIBER_EMAIL",
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_DONO_CHAT_ID", "TELEGRAM_USUARIOS_AUTORIZADOS",
)


def _sem_rede(*_args, **_kwargs):
    raise AssertionError("teste tentou acessar a rede")


def _inscricao(n: int = 1) -> dict:
    return {
        "endpoint": f"https://push.example.com/send/aparelho-{n}",
        "keys": {"p256dh": "BElaChavePublicaDoAparelho_-123", "auth": "segredoAuth-1"},
    }


class BaseSemRede(unittest.TestCase):
    def setUp(self) -> None:
        self.p_rede = mock.patch("urllib.request.urlopen", side_effect=_sem_rede)
        self.p_rede.start()
        self.p_env = mock.patch.dict(os.environ, {k: "" for k in ENV_CANAIS})
        self.p_env.start()
        self.p_cfg = [mock.patch.object(config, k, "", create=True) for k in ENV_CANAIS]
        for p in self.p_cfg:
            p.start()
        self.temp = tempfile.TemporaryDirectory()
        self.pasta = Path(self.temp.name)

    def tearDown(self) -> None:
        for p in self.p_cfg:
            p.stop()
        self.p_env.stop()
        self.p_rede.stop()
        self.temp.cleanup()


class TestDiscord(BaseSemRede):
    def test_modo_bot_monta_url_e_cabecalho(self) -> None:
        chamadas = []
        canal = CanalDiscord(
            bot_token=SEGREDO,
            canal_id="123456789",
            http_client=lambda u, p, h: chamadas.append((u, p, h)) or True,
        )
        self.assertEqual(canal.modo(), "bot")
        self.assertTrue(canal.enviar("Agenda", "Corpo", urgencia="alta"))
        url, payload, headers = chamadas[0]
        self.assertEqual(url, "https://discord.com/api/v10/channels/123456789/messages")
        self.assertEqual(headers["Authorization"], f"Bot {SEGREDO}")
        self.assertIn("URGENTE: Agenda", payload["content"])
        self.assertEqual(payload["allowed_mentions"], {"parse": []})

    def test_webhook_tem_prioridade_e_exige_https(self) -> None:
        canal = CanalDiscord(webhook_url="https://discord.com/api/webhooks/1/x", bot_token="t", canal_id="1")
        self.assertEqual(canal.modo(), "webhook")
        self.assertFalse(CanalDiscord(webhook_url="http://inseguro.example.com/hook").configurado())
        self.assertFalse(CanalDiscord(bot_token="t", canal_id="../outro").configurado())

    def test_le_variaveis_de_ambiente(self) -> None:
        with mock.patch.dict(os.environ, {"DISCORD_BOT_TOKEN": "tok", "DISCORD_CANAL_ID": "42"}):
            self.assertEqual(CanalDiscord().modo(), "bot")

    def test_conteudo_respeita_limite(self) -> None:
        enviados = []
        canal = CanalDiscord(webhook_url="https://discord.com/api/webhooks/1/x",
                             http_client=lambda u, p: enviados.append(p) or True)
        canal.enviar("T", "x" * 5000)
        self.assertLessEqual(len(enviados[0]["content"]), 2000)

    def test_falha_http_real_nao_vaza_segredo_no_log(self) -> None:
        canal = CanalDiscord(webhook_url=f"https://discord.com/api/webhooks/1/{SEGREDO}")
        with self.assertLogs("nextor.notificacoes.discord", level="WARNING") as logs:
            self.assertFalse(canal.enviar("T", "C"))
        self.assertNotIn(SEGREDO, "\n".join(logs.output))


class TestWhatsApp(BaseSemRede):
    def test_texto_livre(self) -> None:
        chamadas = []
        canal = CanalWhatsApp(token=SEGREDO, phone_id="1098765", destinatario="+55 (11) 99999-9999",
                              http_client=lambda u, p, h: chamadas.append((u, p, h)) or True)
        self.assertTrue(canal.enviar("Aviso", "Mensagem"))
        url, payload, headers = chamadas[0]
        self.assertEqual(url, "https://graph.facebook.com/v19.0/1098765/messages")
        self.assertEqual(payload["to"], "5511999999999")
        self.assertEqual(payload["type"], "text")
        self.assertEqual(headers["Authorization"], f"Bearer {SEGREDO}")

    def test_modelo_aprovado(self) -> None:
        chamadas = []
        canal = CanalWhatsApp(token="t", phone_id="1", destinatario="5511", template="nextor_aviso",
                              http_client=lambda u, p, h: chamadas.append(p) or True)
        self.assertTrue(canal.enviar("Titulo", "Corpo"))
        payload = chamadas[0]
        self.assertEqual(payload["type"], "template")
        self.assertEqual(payload["template"]["name"], "nextor_aviso")
        params = payload["template"]["components"][0]["parameters"]
        self.assertEqual([p["text"] for p in params], ["Titulo", "Corpo"])

    def test_phone_id_invalido_nao_configura(self) -> None:
        self.assertFalse(CanalWhatsApp(token="t", phone_id="1/../x", destinatario="55").configurado())
        self.assertFalse(CanalWhatsApp().configurado())

    def test_falha_nao_vaza_token(self) -> None:
        canal = CanalWhatsApp(token=SEGREDO, phone_id="1", destinatario="55")
        with self.assertLogs("nextor.notificacoes.whatsapp", level="WARNING") as logs:
            self.assertFalse(canal.enviar("T", "C"))
        self.assertNotIn(SEGREDO, "\n".join(logs.output))


class TestTelegram(BaseSemRede):
    def test_falha_nao_vaza_token(self) -> None:
        canal = CanalTelegram(bot_token=SEGREDO, chat_id="1")
        with self.assertLogs("nextor", level="WARNING") as logs:
            self.assertFalse(canal.enviar("T", "C"))
        self.assertNotIn(SEGREDO, "\n".join(logs.output))

    def test_resposta_mockada_da_api(self) -> None:
        resposta = mock.MagicMock()
        resposta.read.return_value = b'{"ok": true}'
        with mock.patch("urllib.request.urlopen") as abrir:
            abrir.return_value.__enter__.return_value = resposta
            ok = CanalTelegram(bot_token="t", chat_id="1").enviar("Lembrete", "Agua", urgencia="critica")
            corpo = json.loads(abrir.call_args[0][0].data.decode("utf-8"))
        self.assertTrue(ok)
        self.assertTrue(corpo["text"].startswith("[URGENTE: Lembrete]"))


class TestWebPush(BaseSemRede):
    def _canal(self, enviar_push) -> CanalWebPush:
        return CanalWebPush(
            public_key="pub", private_key=SEGREDO, subscriber_email="eu@example.com",
            inscricoes=InscricoesPush(self.pasta / "push.json"), enviar_push=enviar_push,
        )

    def test_validacao_de_inscricao(self) -> None:
        self.assertIsNotNone(validar_inscricao(_inscricao()))
        self.assertIsNone(validar_inscricao({"endpoint": "http://x.example.com", "keys": _inscricao()["keys"]}))
        self.assertIsNone(validar_inscricao({"endpoint": "https://x.example.com", "keys": {"p256dh": "a b", "auth": "c"}}))
        self.assertIsNone(validar_inscricao("nada"))

    def test_sem_aparelhos_retorna_falso(self) -> None:
        canal = self._canal(lambda *a: 201)
        self.assertTrue(canal.configurado())
        self.assertFalse(canal.enviar("T", "C"))

    def test_envia_para_cada_aparelho_e_remove_expirado(self) -> None:
        envios = []

        def enviar(inscricao, dados, chave, claims, urgencia):
            envios.append((inscricao["endpoint"], json.loads(dados), chave, claims, urgencia))
            return 410 if inscricao["endpoint"].endswith("-2") else 201

        canal = self._canal(enviar)
        canal.inscricoes.adicionar(_inscricao(1))
        canal.inscricoes.adicionar(_inscricao(2))
        canal.inscricoes.adicionar(_inscricao(1))  # repetida: atualiza, nao duplica
        self.assertEqual(canal.inscricoes.quantidade(), 2)

        self.assertTrue(canal.enviar("Tarefa", "Atrasada", urgencia="alta"))
        self.assertEqual(len(envios), 2)
        _, dados, chave, claims, urgencia = envios[0]
        self.assertEqual(dados["title"], "URGENTE: Tarefa")
        self.assertEqual(chave, SEGREDO)
        self.assertEqual(claims, {"sub": "mailto:eu@example.com"})
        self.assertEqual(urgencia, "high")
        self.assertEqual(canal.inscricoes.quantidade(), 1)

    def test_sem_pywebpush_falha_sem_quebrar(self) -> None:
        def enviar(*_a):
            raise ImportError("pywebpush")

        canal = self._canal(enviar)
        canal.inscricoes.adicionar(_inscricao())
        self.assertFalse(canal.enviar("T", "C"))

    def test_erro_de_envio_nao_vaza_endpoint_nem_chave(self) -> None:
        def enviar(inscricao, *_a):
            raise RuntimeError(f"falhou {inscricao['endpoint']} {SEGREDO}")

        canal = self._canal(enviar)
        canal.inscricoes.adicionar(_inscricao())
        with self.assertLogs("nextor.notificacoes.webpush", level="WARNING") as logs:
            self.assertFalse(canal.enviar("T", "C"))
        texto = "\n".join(logs.output)
        self.assertNotIn(SEGREDO, texto)
        self.assertNotIn("push.example.com", texto)


class TestRoteadorEConfig(BaseSemRede):
    def test_nenhum_canal_configurado_nada_quebra(self) -> None:
        roteador = RoteadorNotificacoes(canais={
            "telegram": CanalTelegram(), "discord": CanalDiscord(), "whatsapp": CanalWhatsApp(),
            "webpush": CanalWebPush(inscricoes=InscricoesPush(self.pasta / "p.json")),
        })
        cfg = {
            "canais_ativos": ["telegram", "discord", "whatsapp", "webpush"],
            "eventos_notificacao": {"lembrete": ["telegram", "discord", "whatsapp", "webpush"]},
            "horario_silencio": {"ativo": False},
        }
        res = roteador.notificar("lembrete", "T", "C", config_usuario=cfg)
        self.assertEqual(res["despachados"], [])
        self.assertEqual(res["falhas"], [])
        self.assertEqual({i["motivo"] for i in res["ignorados"]}, {"nao_configurado"})
        self.assertTrue(all(not s["configurado"] for s in roteador.listar_status_canais()))

    def test_varios_canais_ao_mesmo_tempo_e_inativo_ignorado(self) -> None:
        discord, falas = [], []
        roteador = RoteadorNotificacoes(canais={
            "discord": CanalDiscord(webhook_url="https://discord.com/api/webhooks/1/x",
                                    http_client=lambda u, p: discord.append(p) or True),
            "voz": CanalVoz(fn_falar=falas.append),
        })
        cfg = {
            "canais_ativos": ["discord", "voz"],
            "eventos_notificacao": {"pr_para_revisar": ["discord", "voz", "discord", "whatsapp"]},
            "horario_silencio": {"ativo": False},
        }
        res = roteador.notificar("pr_para_revisar", "PR", "Revisar #1", config_usuario=cfg)
        self.assertEqual(res["despachados"], ["discord", "voz"])
        self.assertEqual(len(discord), 1)
        self.assertEqual(res["ignorados"], [{"canal": "whatsapp", "motivo": "inativo"}])

    def test_urgencia_alta_fura_silencio(self) -> None:
        falas = []
        roteador = RoteadorNotificacoes(canais={"voz": CanalVoz(fn_falar=falas.append)})
        cfg = {"canais_ativos": ["voz"], "eventos_notificacao": {"lembrete": ["voz"]},
               "horario_silencio": {"ativo": True, "inicio": "22:00", "fim": "07:00"}}
        res = roteador.notificar("lembrete", "T", "C", urgencia="alta", config_usuario=cfg,
                                 hora_referencia=time(23, 0))
        self.assertFalse(res["silenciado"])
        self.assertEqual(len(falas), 1)

    def test_atalho_notificar_usa_config_salva(self) -> None:
        caminho = self.pasta / "config.json"
        salvar_config({"canais_ativos": ["voz"], "eventos_notificacao": {"lembrete": ["voz"]},
                       "horario_silencio": {"ativo": False}}, caminho_customizado=caminho)
        falas = []
        roteador = RoteadorNotificacoes(canais={"voz": CanalVoz(fn_falar=falas.append)})
        with mock.patch.dict(os.environ, {"NEXTOR_GTD_CONFIG_JSON": str(caminho)}), \
                mock.patch.object(mod_roteador, "roteador_instancia", roteador):
            res = mod_roteador.notificar("lembrete", "T", "C")
        self.assertEqual(res["despachados"], ["voz"])

    def test_salvar_config_valida_canais_eventos_horarios_e_tema(self) -> None:
        caminho = self.pasta / "config.json"
        salvo = salvar_config({
            "canais_ativos": ["discord", "sms", "DISCORD", "webpush"],
            "eventos_notificacao": {"tarefa_atrasada": ["whatsapp", "pombo"], "Evento Ruim!": ["voz"],
                                    "agenda_do_dia": "telegram"},
            "horario_silencio": {"ativo": True, "inicio": "7:5", "fim": "6:30"},
            "tema": "claro",
            "paleta": "violeta",
        }, caminho_customizado=caminho)
        self.assertEqual(salvo["canais_ativos"], ["discord", "webpush"])
        self.assertEqual(salvo["eventos_notificacao"]["tarefa_atrasada"], ["whatsapp"])
        self.assertNotIn("Evento Ruim!", salvo["eventos_notificacao"])
        self.assertEqual(salvo["eventos_notificacao"]["agenda_do_dia"], ["telegram"])
        self.assertEqual(salvo["horario_silencio"], {"ativo": True, "inicio": "22:00", "fim": "06:30"})
        recarregado = carregar_config(caminho)
        self.assertEqual((recarregado["tema"], recarregado["paleta"]), ("claro", "violeta"))

        salvar_config({"tema": "neon", "paleta": "rosa"}, caminho_customizado=caminho)
        recarregado = carregar_config(caminho)
        self.assertEqual((recarregado["tema"], recarregado["paleta"]), ("claro", "violeta"))

    def test_formatar_titulo(self) -> None:
        self.assertEqual(formatar_titulo(" Oi ", "normal"), "Oi")
        self.assertEqual(formatar_titulo("Oi", "critica"), "URGENTE: Oi")
        self.assertEqual(formatar_titulo("Oi", "desconhecida"), "Oi")


class TestAvisos(BaseSemRede):
    def setUp(self) -> None:
        super().setUp()
        avisos.limpar_historico()
        self.db = ArmazenamentoGTD(self.pasta / "gtd.db")
        self.enviados = []

    def _notificador(self, **kw):
        self.enviados.append(kw)
        return {"despachados": ["telegram"], "falhas": [], "silenciado": False}

    def test_tarefas_atrasadas_avisa_uma_vez_por_dia(self) -> None:
        self.db.salvar_item(Item(titulo="Pagar conta", estado="proxima", prazo="2026-01-01"))
        self.db.salvar_item(Item(titulo="Futuro", estado="proxima", prazo="2099-01-01"))
        hoje = date(2026, 6, 1)
        res = avisos.avisar_tarefas_atrasadas(db=self.db, notificador=self._notificador, hoje=hoje)
        self.assertTrue(res["enviado"])
        self.assertEqual(self.enviados[0]["evento"], "tarefa_atrasada")
        self.assertIn("Pagar conta", self.enviados[0]["corpo"])
        self.assertNotIn("Futuro", self.enviados[0]["corpo"])

        repetido = avisos.avisar_tarefas_atrasadas(db=self.db, notificador=self._notificador, hoje=hoje)
        self.assertFalse(repetido["enviado"])
        self.assertEqual(len(self.enviados), 1)

    def test_prs_para_revisar_com_github_mockado(self) -> None:
        resposta = {"items": [{"number": 7, "title": "Corrige bug",
                               "repository_url": "https://api.github.com/repos/dono/repo",
                               "html_url": "https://github.com/dono/repo/pull/7"}]}
        handler = mock.Mock(return_value=(200, resposta))
        with mock.patch.object(config, "GITHUB_USUARIO", "dono"):
            res = avisos.avisar_prs_para_revisar(notificador=self._notificador, handler_github=handler)
        self.assertTrue(res["enviado"])
        self.assertIn("review-requested:dono", handler.call_args[0][0].full_url)
        self.assertIn("dono/repo#7 Corrige bug", self.enviados[0]["corpo"])
        again = avisos.avisar_prs_para_revisar(notificador=self._notificador, handler_github=handler)
        self.assertFalse(again["enviado"])

    def test_agenda_do_dia(self) -> None:
        with mock.patch("nextor.agenda.eventos_hoje", return_value=[]):
            res = avisos.avisar_agenda_do_dia(db=self.db, notificador=self._notificador)
        self.assertTrue(res["enviado"])
        self.assertEqual(self.enviados[0]["evento"], "agenda_do_dia")
        self.assertTrue(self.enviados[0]["corpo"])


class TestRotasPush(BaseSemRede):
    def setUp(self) -> None:
        super().setUp()
        self.token = "nxt_mestre_seguro_123456789012345"
        self.p_token = mock.patch.object(config, "TOKEN", self.token)
        self.p_token.start()
        self.canal = CanalWebPush(public_key="chave-publica", private_key=SEGREDO, subscriber_email="eu@example.com",
                                  inscricoes=InscricoesPush(self.pasta / "push.json"))
        self.p_canal = mock.patch.dict(mod_roteador.roteador_instancia.canais, {"webpush": self.canal})
        self.p_canal.start()
        self.client = servico.app.test_client()
        self.h = {"X-Nextor-Token": self.token, "Content-Type": "application/json"}

    def tearDown(self) -> None:
        self.p_canal.stop()
        self.p_token.stop()
        super().tearDown()

    def test_rotas_exigem_token(self) -> None:
        for metodo, rota in (("get", "/gtd/notificacoes/push/chave"), ("post", "/gtd/notificacoes/push/inscrever"),
                             ("post", "/gtd/notificacoes/push/cancelar"), ("post", "/gtd/notificacoes/disparar")):
            self.assertEqual(getattr(self.client, metodo)(rota).status_code, 401, rota)

    def test_chave_inscrever_e_cancelar(self) -> None:
        chave = self.client.get("/gtd/notificacoes/push/chave", headers=self.h).get_json()
        self.assertEqual(chave["chave_publica"], "chave-publica")
        self.assertNotIn(SEGREDO, json.dumps(chave))

        ruim = self.client.post("/gtd/notificacoes/push/inscrever", headers=self.h, data=json.dumps({"endpoint": "x"}))
        self.assertEqual(ruim.status_code, 400)

        ok = self.client.post("/gtd/notificacoes/push/inscrever", headers=self.h, data=json.dumps(_inscricao()))
        self.assertEqual(ok.get_json()["aparelhos"], 1)

        fora = self.client.post("/gtd/notificacoes/push/cancelar", headers=self.h,
                                data=json.dumps({"endpoint": _inscricao()["endpoint"]}))
        self.assertTrue(fora.get_json()["removido"])
        self.assertEqual(fora.get_json()["aparelhos"], 0)

    def test_disparar_evento_desconhecido(self) -> None:
        resp = self.client.post("/gtd/notificacoes/disparar", headers=self.h, data=json.dumps({"evento": "x"}))
        self.assertEqual(resp.status_code, 400)

    def test_disparar_evento_valido(self) -> None:
        with mock.patch.object(avisos, "AVISOS", {"tarefa_atrasada": lambda notificador=None: {"evento": "tarefa_atrasada", "enviado": False}}):
            resp = self.client.post("/gtd/notificacoes/disparar", headers=self.h,
                                    data=json.dumps({"evento": "tarefa_atrasada"}))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["evento"], "tarefa_atrasada")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    unittest.main()
