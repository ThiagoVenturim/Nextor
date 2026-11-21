"""Testes offline da tela de configuracao (Issue #47): skills, ferramentas MCP, agentes,
canais por evento, validacao e leitura da config pelos modulos."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from nextor import config, mcp_server, servico
from nextor.gtd.configuracao import (
    SKILLS_IDS,
    agente_ativo,
    carregar_config,
    ferramenta_mcp_ativa,
    obter_config_completa,
    salvar_config,
)


class BaseConfig(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.caminho = Path(self.tmp.name) / "config.json"
        self.env_antigo = os.environ.get("NEXTOR_GTD_CONFIG_JSON")
        os.environ["NEXTOR_GTD_CONFIG_JSON"] = str(self.caminho)

    def tearDown(self) -> None:
        if self.env_antigo is None:
            os.environ.pop("NEXTOR_GTD_CONFIG_JSON", None)
        else:
            os.environ["NEXTOR_GTD_CONFIG_JSON"] = self.env_antigo
        self.tmp.cleanup()


class TestCatalogoMCP(BaseConfig):
    def test_catalogo_vem_do_mcp_server(self) -> None:
        nomes = {f["nome"] for f in mcp_server.listar_ferramentas()}
        self.assertIn("gtd_capturar", nomes)
        self.assertIn("nexvoice_iniciar_sessao", nomes)
        for f in mcp_server.listar_ferramentas():
            self.assertIn(f["skill"], SKILLS_IDS, f["nome"])
            self.assertTrue(f["descricao"], f["nome"])

    def test_padrao_expoe_todas(self) -> None:
        self.assertEqual(set(mcp_server.ferramentas_expostas({})), set(mcp_server.FERRAMENTAS))

    def test_desligar_ferramenta_e_skill(self) -> None:
        salvar_config({"mcp_ferramentas": {"falar": False}, "skills": {"nexvoice": False}})
        expostas = set(mcp_server.ferramentas_expostas())
        self.assertNotIn("falar", expostas)
        self.assertFalse(any(n.startswith("nexvoice_") for n in expostas))
        self.assertIn("gtd_capturar", expostas)

    def test_construir_servidor_registra_so_as_ligadas(self) -> None:
        registradas = []

        class ServidorFalso:
            def __init__(self, nome):
                self.nome = nome

            def tool(self, description=""):
                def deco(fn):
                    registradas.append(fn.__name__)
                    return fn
                return deco

        cfg = {"skills": {"coach": False}, "mcp_ferramentas": {"anotar": False}}
        with mock.patch.object(mcp_server, "MCPServer", ServidorFalso):
            mcp_server.construir_servidor(cfg)
        self.assertNotIn("anotar", registradas)
        self.assertFalse(any(n.startswith("coach_") for n in registradas))
        self.assertIn("listar_notas", registradas)

    def test_ferramenta_desconhecida_e_ignorada(self) -> None:
        salvo = salvar_config({"mcp_ferramentas": {"rm_rf": False, "Falar": False, "gtd_dia": False}})
        self.assertEqual(salvo["mcp_ferramentas"], {"gtd_dia": False})
        self.assertFalse(ferramenta_mcp_ativa(salvo, "gtd_dia", "gtd"))


class TestAgentesESkills(BaseConfig):
    def test_agente_depende_das_skills(self) -> None:
        cfg = carregar_config()
        self.assertTrue(agente_ativo(cfg, "sugerir_ordem_dia"))
        cfg = salvar_config({"skills": {"agenda": False}})
        self.assertFalse(agente_ativo(cfg, "sugerir_ordem_dia"))
        self.assertTrue(agente_ativo(cfg, "organizar_inbox"))
        self.assertFalse(agente_ativo(cfg, "agente_inexistente"))

    def test_chaves_desconhecidas_nao_sao_gravadas(self) -> None:
        salvo = salvar_config({
            "agentes": {"revisao_semanal": False, "minerador": True},
            "skills": {"coach": False, "hack": True},
            "integracoes": {"github": False, "banco_x": True},
        })
        self.assertFalse(salvo["agentes"]["revisao_semanal"])
        self.assertNotIn("minerador", salvo["agentes"])
        self.assertFalse(salvo["skills"]["coach"])
        self.assertNotIn("hack", salvo["skills"])
        self.assertFalse(salvo["integracoes"]["github"])
        self.assertNotIn("banco_x", salvo["integracoes"])

    def test_catalogo_completo_mostra_o_que_cada_um_faz(self) -> None:
        salvar_config({"skills": {"agenda": False}, "mcp_ferramentas": {"gtd_dia": False}})
        completa = obter_config_completa()
        skills = {s["id"]: s for s in completa["skills"]}
        self.assertFalse(skills["agenda"]["ativo"])
        self.assertIn("agenda_dia", skills["agenda"]["ferramentas"])
        self.assertTrue(all(s["descricao"] for s in completa["skills"]))

        mcp = {f["nome"]: f for f in completa["mcp_ferramentas"]}
        self.assertFalse(mcp["gtd_dia"]["ativo"])
        self.assertFalse(mcp["gtd_dia"]["exposta"])
        self.assertTrue(mcp["agenda_dia"]["ativo"])
        self.assertFalse(mcp["agenda_dia"]["exposta"])

        agentes = {a["id"]: a for a in completa["agentes"]}
        self.assertTrue(agentes["sugerir_ordem_dia"]["ativo"])
        self.assertFalse(agentes["sugerir_ordem_dia"]["efetivo"])
        self.assertIn("agenda", agentes["sugerir_ordem_dia"]["skills"])

        self.assertIn("lembrete", completa["eventos"])
        self.assertEqual(completa["temas"], ["escuro", "claro"])
        self.assertIn("ambar", completa["paletas"])


class TestNotificacoesConfig(BaseConfig):
    def test_canais_por_evento_validados(self) -> None:
        salvo = salvar_config({
            "canais_ativos": ["Telegram", "discord", "pombo", "discord"],
            "eventos_notificacao": {
                "lembrete": ["discord", "sms", "voz"],
                "evento_falso": ["telegram"],
                "pomodoro_fim": "voz",
            },
        })
        self.assertEqual(salvo["canais_ativos"], ["telegram", "discord"])
        self.assertEqual(salvo["eventos_notificacao"]["lembrete"], ["discord", "voz"])
        self.assertNotIn("evento_falso", salvo["eventos_notificacao"])
        self.assertEqual(salvo["eventos_notificacao"]["pomodoro_fim"], ["voz", "telegram"])

    def test_horario_silencio_invalido_mantem_anterior(self) -> None:
        salvar_config({"horario_silencio": {"ativo": True, "inicio": "23:00", "fim": "06:30"}})
        salvo = salvar_config({"horario_silencio": {"inicio": "25:99", "fim": "x"}})
        self.assertEqual(salvo["horario_silencio"]["inicio"], "23:00")
        self.assertEqual(salvo["horario_silencio"]["fim"], "06:30")

    def test_config_antiga_ganha_chaves_novas(self) -> None:
        self.caminho.write_text(json.dumps({"metodo_ativo": "para", "agentes": {"organizar_inbox": False}}), encoding="utf-8")
        cfg = carregar_config()
        self.assertEqual(cfg["metodo_ativo"], "para")
        self.assertFalse(cfg["agentes"]["organizar_inbox"])
        self.assertTrue(cfg["agentes"]["sugerir_ordem_dia"])
        self.assertTrue(all(cfg["skills"][s] for s in SKILLS_IDS))
        self.assertEqual(cfg["mcp_ferramentas"], {})


class TestEndpointConfig(BaseConfig):
    def setUp(self) -> None:
        super().setUp()
        self.token = "nxt_teste_config_tela_0123456789"
        self.patch_token = mock.patch.object(config, "TOKEN", self.token)
        self.patch_token.start()
        self.client = servico.app.test_client()
        self.h = {"X-Nextor-Token": self.token, "Content-Type": "application/json"}

    def tearDown(self) -> None:
        self.patch_token.stop()
        super().tearDown()

    def test_put_e_get_skills_mcp(self) -> None:
        resp = self.client.put("/gtd/config", headers=self.h, data=json.dumps({
            "skills": {"noticias": False},
            "mcp_ferramentas": {"pomodoro_parar": False},
            "agentes": {"organizar_inbox": False},
        }))
        self.assertEqual(resp.status_code, 200)
        dados = self.client.get("/gtd/config", headers=self.h).get_json()
        self.assertFalse(dados["config"]["skills"]["noticias"])
        self.assertFalse(dados["config"]["mcp_ferramentas"]["pomodoro_parar"])
        agentes = {a["id"]: a for a in dados["agentes"]}
        self.assertFalse(agentes["organizar_inbox"]["ativo"])

    def test_ordem_do_dia_respeita_skill(self) -> None:
        salvar_config({"skills": {"agenda": False}})
        dados = self.client.get("/gtd/ordem", headers=self.h).get_json()
        self.assertTrue(dados["desligado"])

    def test_get_config_nao_vaza_segredos(self) -> None:
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_segredo_que_nao_pode_sair"}):
            corpo = self.client.get("/gtd/config", headers=self.h).get_data(as_text=True)
        self.assertNotIn("ghp_segredo_que_nao_pode_sair", corpo)
        self.assertNotIn(self.token, corpo)


if __name__ == "__main__":
    unittest.main()
