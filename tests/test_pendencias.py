"""Testes unitarios offline do painel de tarefas e pendencias (issue #13).

Sem rede, sem hardware real, sem audio, sem chamada externa.
Isolamento total com tempfile.TemporaryDirectory e mocks offline.
Cobre:
1) coletar_pendencias_anotacoes (parsing de carimbos, checklists [ ], descarte de [x], atrasada vs para_hoje);
2) coletar_pendencias_agenda (uso de mock_eventos, classificacao de prazos e datas);
3) coletar_pendencias_github (uso de mock_issues, classificacao de labels e repositorio);
4) coletar_todas_pendencias e ordenacao estrita (atrasadas, hoje, prazos mais proximos, fontes opcionais);
5) resposta em duas camadas (resumo falado curto e lista estruturada completa);
6) conclusao de tarefas (nota local direta com [x], GitHub em duas etapas com confirmacao/cancelamento);
7) gatilhos no roteador ('quais sao minhas pendencias', 'o que fazer hoje', 'marcar tarefa como feita', confirmar/cancelar);
8) endpoints HTTP em servico.py (/v1/pendencias, /v1/pendencias/concluir; 401 sem token, filtros e 200).
"""
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

os.environ["NEXTOR_VOZ_SAIDA"] = "nenhuma"

from nextor import config, pendencias, roteador, servico


class BasePendenciasTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.caminho_base = Path(self.tmp_dir.name).resolve()
        self.arquivo_anotacoes = self.caminho_base / "anotacoes.md"

        self.patch_anotacoes = mock.patch.object(
            config,
            "ANOTACOES",
            self.arquivo_anotacoes,
        )
        self.patch_token = mock.patch.object(
            config,
            "TOKEN",
            "token-mestre-super-seguro-1234567890",
        )
        self.patch_gh_issues = mock.patch(
            "nextor.github_integration.listar_issues_atribuidas",
            return_value=[],
        )
        self.patch_agenda = mock.patch(
            "nextor.agenda.eventos_entre",
            return_value=[],
        )
        self.patch_anotacoes.start()
        self.patch_token.start()
        self.patch_gh_issues.start()
        self.patch_agenda.start()

        pendencias.limpar_conclusao_pendente()
        self.client = servico.app.test_client()
        self.h_mestre = {"X-Nextor-Token": "token-mestre-super-seguro-1234567890"}

    def tearDown(self):
        pendencias.limpar_conclusao_pendente()
        self.patch_anotacoes.stop()
        self.patch_token.stop()
        self.patch_gh_issues.stop()
        self.patch_agenda.stop()
        self.tmp_dir.cleanup()


class TestColetarPendenciasAnotacoes(BasePendenciasTestCase):
    def test_arquivo_inexistente_retorna_vazio(self):
        self.assertEqual(pendencias.coletar_pendencias_anotacoes(self.arquivo_anotacoes), [])

    def test_parsing_checklists_e_carimbos(self):
        tz = ZoneInfo("America/Sao_Paulo")
        agora = datetime(2026, 11, 4, 15, 0, tzinfo=tz)

        conteudo = (
            "- [ ] Comprar cafe\n"
            "- [x] Pagar boleto internet\n"
            "- [X] Limpar mesa\n"
            "- [2026-11-04] Entregar relatorio hoje\n"
            "- [2026-11-01 10:00] Consulta medica passada\n"
            "- [2026-11-10] Apresentacao futura\n"
            "- Tarefa simples sem check\n"
        )
        self.arquivo_anotacoes.write_text(conteudo, encoding="utf-8")

        itens = pendencias.coletar_pendencias_anotacoes(self.arquivo_anotacoes, agora=agora)
        # 7 linhas, 2 concluidas ([x], [X]), sobram 5 pendencias
        self.assertEqual(len(itens), 5)

        # 1. Comprar cafe
        self.assertEqual(itens[0]["titulo"], "Comprar cafe")
        self.assertEqual(itens[0]["id"], "nota:1")
        self.assertFalse(itens[0]["atrasada"])
        self.assertFalse(itens[0]["para_hoje"])

        # 2. Entregar relatorio hoje
        self.assertEqual(itens[1]["titulo"], "Entregar relatorio hoje")
        self.assertTrue(itens[1]["para_hoje"])
        self.assertFalse(itens[1]["atrasada"])

        # 3. Consulta medica passada (atrasada)
        self.assertEqual(itens[2]["titulo"], "Consulta medica passada")
        self.assertTrue(itens[2]["atrasada"])

        # 4. Apresentacao futura
        self.assertEqual(itens[3]["titulo"], "Apresentacao futura")
        self.assertFalse(itens[3]["atrasada"])
        self.assertFalse(itens[3]["para_hoje"])

        # 5. Tarefa simples
        self.assertEqual(itens[4]["titulo"], "Tarefa simples sem check")


class TestColetarPendenciasAgenda(BasePendenciasTestCase):
    def test_coleta_com_mock_eventos(self):
        tz = ZoneInfo("America/Sao_Paulo")
        agora = datetime(2026, 11, 4, 14, 0, tzinfo=tz)

        eventos = [
            {
                "titulo": "Reuniao de Alinhamento",
                "inicio": datetime(2026, 11, 4, 16, 0, tzinfo=tz),
            },
            {
                "titulo": "Entrega Atrasada",
                "inicio": datetime(2026, 11, 3, 10, 0, tzinfo=tz),
            },
            {
                "titulo": "Workshop Futuro",
                "inicio": date(2026, 11, 8),
            },
        ]
        itens = pendencias.coletar_pendencias_agenda(agora=agora, mock_eventos=eventos)
        self.assertEqual(len(itens), 3)

        self.assertEqual(itens[0]["fonte"], "agenda")
        self.assertEqual(itens[0]["titulo"], "Reuniao de Alinhamento")
        self.assertTrue(itens[0]["para_hoje"])
        self.assertFalse(itens[0]["atrasada"])

        self.assertEqual(itens[1]["titulo"], "Entrega Atrasada")
        self.assertTrue(itens[1]["atrasada"])

        self.assertEqual(itens[2]["titulo"], "Workshop Futuro")
        self.assertFalse(itens[2]["para_hoje"])
        self.assertFalse(itens[2]["atrasada"])


class TestColetarPendenciasGitHub(BaseGitHubTestCase := BasePendenciasTestCase):
    def test_coleta_com_mock_issues(self):
        issues = [
            {
                "repo": "Nextor",
                "numero": 13,
                "titulo": "Painel de tarefas",
                "labels": ["urgente", "feature"],
                "url": "https://github.com/ThiagoVenturim/Nextor/issues/13",
            },
            {
                "repo": "Nextor",
                "numero": 14,
                "titulo": "Refatorar audio",
                "labels": ["melhoria"],
                "url": "https://github.com/ThiagoVenturim/Nextor/issues/14",
            },
        ]
        itens = pendencias.coletar_pendencias_github(mock_issues=issues)
        self.assertEqual(len(itens), 2)

        self.assertEqual(itens[0]["fonte"], "github")
        self.assertEqual(itens[0]["id"], "github:Nextor#13")
        self.assertEqual(itens[0]["numero"], 13)
        self.assertTrue(itens[0]["para_hoje"])  # label 'urgente'

        self.assertEqual(itens[1]["id"], "github:Nextor#14")
        self.assertFalse(itens[1]["para_hoje"])


class TestColetarTodasPendenciasEOrdenacao(BasePendenciasTestCase):
    def test_ordenacao_estrita_atrasadas_depois_hoje_depois_futuras(self):
        tz = ZoneInfo("America/Sao_Paulo")
        agora = datetime(2026, 11, 4, 12, 0, tzinfo=tz)

        conteudo = (
            "- [2026-11-04 18:00] Tarefa de hoje a noite\n"
            "- [2026-11-02] Tarefa atrasada da semana passada\n"
            "- [2026-11-09] Tarefa semana que vem\n"
            "- Tarefa sem data definida\n"
        )
        self.arquivo_anotacoes.write_text(conteudo, encoding="utf-8")

        eventos = [
            {
                "titulo": "Reuniao Hoje a Tarde",
                "inicio": datetime(2026, 11, 4, 15, 0, tzinfo=tz),
            }
        ]
        issues = [
            {
                "repo": "Nextor",
                "numero": 13,
                "titulo": "Issue Urgente Hoje",
                "labels": ["hoje"],
            }
        ]

        todas = pendencias.coletar_todas_pendencias(
            caminho_anotacoes=self.arquivo_anotacoes,
            mock_eventos=eventos,
            mock_issues=issues,
            agora=agora,
        )

        # 1. A primeira DEVE ser a atrasada
        self.assertTrue(todas[0]["atrasada"])
        self.assertIn("atrasada", todas[0]["titulo"].lower())

        # 2. Seguintes devem ser as de hoje
        hoje_itens = [t for t in todas if t["para_hoje"] and not t["atrasada"]]
        self.assertEqual(len(hoje_itens), 3)

        # 3. Itens sem data vao para o final
        self.assertIsNone(todas[-1]["dt_prazo"])
        self.assertEqual(todas[-1]["titulo"], "Tarefa sem data definida")

    def test_filtros_fontes_opcionais(self):
        self.arquivo_anotacoes.write_text("- Nota teste\n", encoding="utf-8")
        eventos = [{"titulo": "Evento", "inicio": date(2026, 11, 4)}]
        issues = [{"repo": "App", "numero": 1, "titulo": "Bug"}]

        apenas_notas = pendencias.coletar_todas_pendencias(
            incluir_anotacoes=True,
            incluir_agenda=False,
            incluir_github=False,
            caminho_anotacoes=self.arquivo_anotacoes,
            mock_eventos=eventos,
            mock_issues=issues,
        )
        self.assertEqual(len(apenas_notas), 1)
        self.assertEqual(apenas_notas[0]["fonte"], "anotacoes")


class TestRespostaDuasCamadas(unittest.TestCase):
    def test_gerar_resumo_falado_com_pendencias(self):
        itens = [
            {"titulo": "Finalizar release", "para_hoje": True, "atrasada": False},
            {"titulo": "Enviar email atrasado", "para_hoje": True, "atrasada": True},
            {"titulo": "Estudar civil", "para_hoje": False, "atrasada": False},
        ]
        resumo = pendencias.gerar_resumo_falado(itens, apenas_hoje=False)
        self.assertIn("Voce tem 3 pendencias", resumo)
        self.assertIn("2 para hoje", resumo)
        self.assertIn("1 atrasadas", resumo)
        self.assertIn("Finalizar release", resumo)

    def test_gerar_resumo_falado_apenas_hoje(self):
        itens = [
            {"titulo": "Reuniao 1", "para_hoje": True, "atrasada": False},
            {"titulo": "Reuniao 2", "para_hoje": True, "atrasada": True},
        ]
        resumo = pendencias.gerar_resumo_falado(itens, apenas_hoje=True)
        self.assertIn("Voce tem 2 tarefas para hoje", resumo)
        self.assertIn("sendo 1 em atraso", resumo)

    def test_gerar_resumo_falado_vazio(self):
        self.assertIn("nao possui nenhuma pendencia", pendencias.gerar_resumo_falado([]))
        self.assertIn("nao tem tarefas pendentes para hoje", pendencias.gerar_resumo_falado([], apenas_hoje=True))


class TestConclusaoTarefas(BasePendenciasTestCase):
    def test_concluir_tarefa_anotacao_direta(self):
        conteudo = (
            "- [ ] Primeira tarefa pendente\n"
            "- [ ] Segunda tarefa pendente\n"
        )
        self.arquivo_anotacoes.write_text(conteudo, encoding="utf-8")

        res = pendencias.concluir_tarefa("nota:1", caminho_anotacoes=self.arquivo_anotacoes)
        self.assertTrue(res["ok"])
        self.assertEqual(res["fonte"], "anotacoes")

        # Verifica marcacao [x] no arquivo
        linhas = self.arquivo_anotacoes.read_text(encoding="utf-8").splitlines()
        self.assertTrue(linhas[0].startswith("- [x] Primeira tarefa pendente"))
        self.assertTrue(linhas[1].startswith("- [ ] Segunda tarefa pendente"))

        # Nova coleta nao traz a primeira
        restantes = pendencias.coletar_pendencias_anotacoes(self.arquivo_anotacoes)
        self.assertEqual(len(restantes), 1)
        self.assertEqual(restantes[0]["titulo"], "Segunda tarefa pendente")

    def test_concluir_tarefa_github_em_duas_etapas_com_confirmacao(self):
        # 1. Primeira etapa: proposta aguardando confirmacao
        res_prop = pendencias.concluir_tarefa("github:Nextor#13", confirmar=False)
        self.assertTrue(res_prop["ok"])
        self.assertTrue(res_prop["requer_confirmacao"])
        self.assertIn("confirma conclusao", res_prop["mensagem"])

        pendente = pendencias.obter_conclusao_pendente()
        self.assertIsNotNone(pendente)
        self.assertEqual(pendente["tipo"], "github")
        self.assertEqual(pendente["numero"], "13")

        # 2. Confirmacao explicita
        def fake_github_api(path, metodo="GET", dados=None, token=None, handler_requisicao=None):
            return 200, {"state": "closed"}

        with mock.patch("nextor.github_integration.fazer_requisicao_api", side_effect=fake_github_api):
            msg_conf = pendencias.confirmar_conclusao_pendente()
            self.assertIn("concluida no GitHub", msg_conf)
            self.assertIsNone(pendencias.obter_conclusao_pendente())

    def test_cancelar_conclusao_pendente(self):
        pendencias.concluir_tarefa("github:Nextor#13", confirmar=False)
        self.assertIsNotNone(pendencias.obter_conclusao_pendente())

        msg_canc = pendencias.cancelar_conclusao_pendente()
        self.assertIn("cancelada com sucesso", msg_canc)
        self.assertIsNone(pendencias.obter_conclusao_pendente())


class TestGatilhosRoteador(BasePendenciasTestCase):
    def test_gatilhos_pendencias(self):
        with mock.patch("nextor.pendencias.gerar_resumo_falado", return_value="Voce tem 2 pendencias."):
            r1 = roteador.rotear("quais sao minhas pendencias")
            self.assertEqual(r1["intencao"], "pendencias")
            self.assertIn("Voce tem 2 pendencias", r1["resposta"])

            r2 = roteador.rotear("minhas pendencias")
            self.assertEqual(r2["intencao"], "pendencias")

    def test_gatilhos_pendencias_hoje(self):
        with mock.patch("nextor.pendencias.gerar_resumo_falado", return_value="Voce tem 1 tarefa para hoje."):
            r1 = roteador.rotear("o que eu tenho para fazer hoje")
            self.assertEqual(r1["intencao"], "pendencias_hoje")
            self.assertIn("1 tarefa para hoje", r1["resposta"])

            r2 = roteador.rotear("tarefas de hoje")
            self.assertEqual(r2["intencao"], "pendencias_hoje")

    def test_gatilho_concluir_tarefa(self):
        with mock.patch("nextor.pendencias.concluir_tarefa_por_voz", return_value="Tarefa marcada como concluida.") as mock_conc:
            r = roteador.rotear("marcar a tarefa Comprar leite como feita")
            self.assertEqual(r["intencao"], "pendencias_concluir")
            self.assertEqual(r["resposta"], "Tarefa marcada como concluida.")
            mock_conc.assert_called_with("Comprar leite")

    def test_gatilhos_confirmar_e_cancelar_conclusao(self):
        with mock.patch("nextor.pendencias.confirmar_conclusao_pendente", return_value="Tarefa concluida no GitHub.") as mock_conf:
            r = roteador.rotear("confirma conclusao")
            self.assertEqual(r["intencao"], "pendencias_confirmar_conclusao")
            self.assertEqual(r["resposta"], "Tarefa concluida no GitHub.")
            mock_conf.assert_called_once()

        with mock.patch("nextor.pendencias.cancelar_conclusao_pendente", return_value="Conclusao cancelada.") as mock_canc:
            r = roteador.rotear("cancela conclusao")
            self.assertEqual(r["intencao"], "pendencias_cancelar_conclusao")
            self.assertEqual(r["resposta"], "Conclusao cancelada.")
            mock_canc.assert_called_once()


class TestEndpointsHTTP(BasePendenciasTestCase):
    def test_bloqueio_sem_token_mestre_retorna_401(self):
        self.assertEqual(self.client.get("/v1/pendencias").status_code, 401)
        self.assertEqual(self.client.post("/v1/pendencias/concluir", json={"id": "nota:1"}).status_code, 401)

    def test_endpoint_pendencias_com_filtros(self):
        self.arquivo_anotacoes.write_text("- [ ] Revisar codigo\n", encoding="utf-8")

        # GET geral
        resp = self.client.get("/v1/pendencias", headers=self.h_mestre)
        self.assertEqual(resp.status_code, 200)
        dados = resp.get_json()
        self.assertTrue(dados["ok"])
        self.assertEqual(dados["total"], 1)
        self.assertIn("resumo_falado", dados)
        self.assertEqual(dados["pendencias"][0]["titulo"], "Revisar codigo")

        # GET filtrando por fonte
        resp_fonte = self.client.get("/v1/pendencias?fonte=anotacoes", headers=self.h_mestre)
        self.assertEqual(resp_fonte.status_code, 200)
        self.assertEqual(resp_fonte.get_json()["total"], 1)

    def test_endpoint_concluir_tarefa_nota(self):
        self.arquivo_anotacoes.write_text("- [ ] Terminar artigo\n", encoding="utf-8")

        resp = self.client.post(
            "/v1/pendencias/concluir",
            json={"id": "nota:1"},
            headers=self.h_mestre,
        )
        self.assertEqual(resp.status_code, 200)
        dados = resp.get_json()
        self.assertTrue(dados["ok"])
        self.assertEqual(dados["fonte"], "anotacoes")

        # Arquivo foi marcado
        self.assertIn("- [x] Terminar artigo", self.arquivo_anotacoes.read_text(encoding="utf-8"))

    def test_endpoint_concluir_sem_id_retorna_400(self):
        resp = self.client.post(
            "/v1/pendencias/concluir",
            json={},
            headers=self.h_mestre,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["erro"], "id_obrigatorio")


if __name__ == "__main__":
    unittest.main()
