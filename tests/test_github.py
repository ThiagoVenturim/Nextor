"""Testes unitarios offline da integracao com o GitHub (issue #16).

Sem rede, sem hardware real, sem audio, sem chamada externa.
Mocks offline para chamadas a API do GitHub.
Cobre:
1) normalizar_repositorio (prefixo de usuario, repositorio completo, padrao);
2) fazer_requisicao_api (headers Authorization Bearer, Accept, Api-Version, tratamento de 200, 401, 404, 500);
3) listar_issues_atribuidas e listar_itens_kanban (agrupamento nas 4 colunas, resumos por voz);
4) regra estrita de confirmacao previa para acoes de escrita (proposta sem escrita, confirmacao e cancelamento);
5) gatilhos no roteador ('o que tem no meu kanban', 'minhas issues', 'cria issue', 'move cartao', confirmar, cancelar);
6) endpoints HTTP em servico.py (/v1/github/* com bloqueio 401 e fluxo de confirmacao).
"""
import io
import json
import os
import unittest
from unittest import mock
import urllib.error

os.environ["NEXTOR_VOZ_SAIDA"] = "nenhuma"

from nextor import config, github_integration, roteador, servico


class BaseGitHubTestCase(unittest.TestCase):
    def setUp(self):
        self.patch_token = mock.patch.object(
            config,
            "TOKEN",
            "token-mestre-super-seguro-1234567890",
        )
        self.patch_gh_token = mock.patch.object(
            config,
            "GITHUB_TOKEN",
            "ghp_fake_github_token_para_testes_offline_123456",
        )
        self.patch_gh_user = mock.patch.object(
            config,
            "GITHUB_USUARIO",
            "ThiagoVenturim",
        )
        self.patch_gh_repo = mock.patch.object(
            config,
            "GITHUB_REPOSITORIO_PADRAO",
            "Nextor",
        )
        self.patch_token.start()
        self.patch_gh_token.start()
        self.patch_gh_user.start()
        self.patch_gh_repo.start()

        github_integration.limpar_acao_pendente()
        self.client = servico.app.test_client()
        self.h_mestre = {"X-Nextor-Token": "token-mestre-super-seguro-1234567890"}

    def tearDown(self):
        github_integration.limpar_acao_pendente()
        self.patch_token.stop()
        self.patch_gh_token.stop()
        self.patch_gh_user.stop()
        self.patch_gh_repo.stop()


class TestNormalizarRepositorio(BaseGitHubTestCase):
    def test_repo_curto_ganha_prefixo_usuario(self):
        self.assertEqual(github_integration.normalizar_repositorio("Nextor"), "ThiagoVenturim/Nextor")
        self.assertEqual(github_integration.normalizar_repositorio("meu-projeto"), "ThiagoVenturim/meu-projeto")

    def test_repo_completo_mantido(self):
        self.assertEqual(github_integration.normalizar_repositorio("outro-user/app"), "outro-user/app")
        self.assertEqual(github_integration.normalizar_repositorio("empresa/sistema"), "empresa/sistema")

    def test_repo_vazio_usa_padrao(self):
        self.assertEqual(github_integration.normalizar_repositorio(""), "ThiagoVenturim/Nextor")
        self.assertEqual(github_integration.normalizar_repositorio(None), "ThiagoVenturim/Nextor")

    def test_respeita_variavel_ambiente_usuario(self):
        with mock.patch.dict(os.environ, {"GITHUB_USUARIO": "usuario-teste"}):
            self.assertEqual(github_integration.normalizar_repositorio("projeto"), "usuario-teste/projeto")


class TestFazerRequisicaoApi(BaseGitHubTestCase):
    def test_montagem_headers_e_metodo_get(self):
        chamadas = []

        def fake_handler(req):
            chamadas.append(req)
            return 200, {"ok": True}

        status, resp = github_integration.fazer_requisicao_api(
            "/user/issues",
            metodo="GET",
            token="token-teste-123",
            handler_requisicao=fake_handler,
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(chamadas), 1)
        req = chamadas[0]
        self.assertEqual(req.get_method(), "GET")
        self.assertEqual(req.full_url, "https://api.github.com/user/issues")
        self.assertEqual(req.get_header("Authorization"), "Bearer token-teste-123")
        self.assertEqual(req.get_header("Accept"), "application/vnd.github+json")
        self.assertEqual(req.get_header("X-github-api-version"), "2022-11-28")
        self.assertEqual(req.get_header("User-agent"), "Nextor-Assistant")

    def test_montagem_headers_e_corpo_post(self):
        chamadas = []

        def fake_handler(req):
            chamadas.append(req)
            return 201, {"id": 100}

        status, resp = github_integration.fazer_requisicao_api(
            "/repos/ThiagoVenturim/Nextor/issues",
            metodo="POST",
            dados={"title": "Nova issue", "body": "Descricao"},
            handler_requisicao=fake_handler,
        )
        self.assertEqual(status, 201)
        req = chamadas[0]
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.get_header("Content-type"), "application/json")
        corpo = json.loads(req.data.decode("utf-8"))
        self.assertEqual(corpo["title"], "Nova issue")
        self.assertEqual(corpo["body"], "Descricao")

    def test_resposta_200_com_urllib_mock(self):
        class MockResp:
            def __init__(self, code, data):
                self.status = code
                self.code = code
                self._data = data

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def read(self):
                return json.dumps(self._data).encode("utf-8")

        with mock.patch("urllib.request.urlopen", return_value=MockResp(200, [{"id": 1}])):
            status, dados = github_integration.fazer_requisicao_api("/user/issues")
            self.assertEqual(status, 200)
            self.assertEqual(dados, [{"id": 1}])

    def test_resposta_401_nao_autorizado(self):
        class Mock401(urllib.error.HTTPError):
            def __init__(self):
                super().__init__(
                    url="https://api.github.com/user/issues",
                    code=401,
                    msg="Unauthorized",
                    hdrs={},
                    fp=io.BytesIO(b'{"message": "Bad credentials"}'),
                )

        with mock.patch("urllib.request.urlopen", side_effect=Mock401()):
            status, dados = github_integration.fazer_requisicao_api("/user/issues")
            self.assertEqual(status, 401)
            self.assertEqual(dados.get("message"), "Bad credentials")

    def test_resposta_404_nao_encontrado(self):
        class Mock404(urllib.error.HTTPError):
            def __init__(self):
                super().__init__(
                    url="https://api.github.com/repos/inexistente/issues",
                    code=404,
                    msg="Not Found",
                    hdrs={},
                    fp=io.BytesIO(b'{"message": "Not Found"}'),
                )

        with mock.patch("urllib.request.urlopen", side_effect=Mock404()):
            status, dados = github_integration.fazer_requisicao_api("/repos/inexistente/issues")
            self.assertEqual(status, 404)
            self.assertEqual(dados.get("message"), "Not Found")

    def test_erro_conexao_retorna_500(self):
        with mock.patch("urllib.request.urlopen", side_effect=ConnectionResetError("Falha de rede")):
            status, dados = github_integration.fazer_requisicao_api("/user/issues")
            self.assertEqual(status, 500)
            self.assertIn("Falha de rede", dados.get("message", ""))


class TestListagemIssuesEKanban(BaseGitHubTestCase):
    def test_listar_issues_atribuidas_sucesso(self):
        dados_mock = [
            {
                "id": 101,
                "number": 15,
                "title": "Organizador de pastas",
                "state": "closed",
                "repository": {"name": "Nextor"},
                "labels": [{"name": "enhancement"}],
                "html_url": "https://github.com/ThiagoVenturim/Nextor/issues/15",
            },
            {
                "id": 102,
                "number": 16,
                "title": "Integracao GitHub",
                "state": "open",
                "repository": {"name": "Nextor"},
                "labels": [{"name": "in-progress"}],
                "html_url": "https://github.com/ThiagoVenturim/Nextor/issues/16",
            },
        ]
        with mock.patch("nextor.github_integration.fazer_requisicao_api", return_value=(200, dados_mock)):
            issues = github_integration.listar_issues_atribuidas()
            self.assertEqual(len(issues), 2)
            self.assertEqual(issues[0]["numero"], 15)
            self.assertEqual(issues[0]["repo"], "Nextor")
            self.assertEqual(issues[1]["numero"], 16)
            self.assertEqual(issues[1]["labels"], ["in-progress"])

    def test_listar_itens_kanban_agrupamento_nas_quatro_colunas(self):
        issues_mock = [
            {"numero": 1, "titulo": "Nova demanda", "estado": "open", "labels": ["bug"]},
            {"numero": 2, "titulo": "Desenvolvendo skill", "estado": "open", "labels": ["in-progress"]},
            {"numero": 3, "titulo": "Ajuste em PR", "estado": "open", "labels": ["review"]},
            {"numero": 4, "titulo": "Demanda finalizada", "estado": "closed", "labels": []},
            {"numero": 5, "titulo": "Documentacao pronta", "estado": "open", "labels": ["done"]},
        ]
        with mock.patch("nextor.github_integration.listar_issues_atribuidas", return_value=issues_mock):
            kanban = github_integration.listar_itens_kanban()
            self.assertTrue(kanban["ok"])
            self.assertEqual(kanban["total"], 5)
            colunas = kanban["colunas"]
            self.assertEqual(len(colunas["A Fazer"]), 1)
            self.assertEqual(colunas["A Fazer"][0]["numero"], 1)

            self.assertEqual(len(colunas["Em Progresso"]), 1)
            self.assertEqual(colunas["Em Progresso"][0]["numero"], 2)

            self.assertEqual(len(colunas["Revisao"]), 1)
            self.assertEqual(colunas["Revisao"][0]["numero"], 3)

            self.assertEqual(len(colunas["Concluido"]), 2)
            self.assertEqual([i["numero"] for i in colunas["Concluido"]], [4, 5])

    def test_resumo_kanban_por_voz(self):
        # 1. Kanban com tarefas
        kanban_mock = {
            "ok": True,
            "total": 3,
            "colunas": {
                "A Fazer": [{"numero": 10, "titulo": "Testar integracao"}],
                "Em Progresso": [{"numero": 16, "titulo": "Kanban por voz"}],
                "Revisao": [],
                "Concluido": [],
            },
        }
        with mock.patch("nextor.github_integration.listar_itens_kanban", return_value=kanban_mock):
            resumo = github_integration.resumo_kanban_por_voz()
            self.assertIn("Voce tem 3 tarefas no kanban", resumo)
            self.assertIn("1 em progresso", resumo)
            self.assertIn("1 a fazer", resumo)
            self.assertIn("issue 16", resumo)

        # 2. Kanban limpo
        with mock.patch("nextor.github_integration.listar_itens_kanban", return_value={"ok": True, "total": 0, "colunas": {}}):
            resumo_limpo = github_integration.resumo_kanban_por_voz()
            self.assertIn("kanban esta limpo", resumo_limpo)

    def test_resumo_issues_por_voz(self):
        issues_mock = [
            {"numero": 16, "repo": "Nextor", "titulo": "Integracao GitHub"},
            {"numero": 15, "repo": "Nextor", "titulo": "Organizador"},
        ]
        with mock.patch("nextor.github_integration.listar_issues_atribuidas", return_value=issues_mock):
            resumo = github_integration.resumo_issues_por_voz()
            self.assertIn("Voce tem 2 issues atribuidas", resumo)
            self.assertIn("#16 em Nextor: Integracao GitHub", resumo)

        with mock.patch("nextor.github_integration.listar_issues_atribuidas", return_value=[]):
            resumo_vazio = github_integration.resumo_issues_por_voz()
            self.assertIn("nao possui issues abertas", resumo_vazio)


class TestRegraSegurancaConfirmacaoPrevia(BaseGitHubTestCase):
    def test_propor_criacao_issue_nao_chama_api_de_escrita(self):
        with mock.patch("nextor.github_integration.fazer_requisicao_api") as mock_api:
            res = github_integration.propor_criacao_issue(
                repo="Nextor",
                titulo="Nova funcionalidade por voz",
                corpo="Detalhes da demanda",
            )
            self.assertTrue(res["ok"])
            self.assertTrue(res["requer_confirmacao"])
            self.assertIn("id_acao", res)
            self.assertIn("confirma criacao", res["mensagem"])

            # NENHUMA chamada de escrita feita a API durante a proposta!
            mock_api.assert_not_called()

            # Proposta salva em memoria
            pendente = github_integration.obter_acao_pendente()
            self.assertIsNotNone(pendente)
            self.assertEqual(pendente["tipo"], "criar_issue")
            self.assertEqual(pendente["titulo"], "Nova funcionalidade por voz")
            self.assertEqual(pendente["repo"], "ThiagoVenturim/Nextor")

    def test_propor_movimentacao_cartao_nao_chama_api_de_escrita(self):
        with mock.patch("nextor.github_integration.fazer_requisicao_api") as mock_api:
            res = github_integration.propor_movimentacao_cartao(
                issue_ref=16,
                coluna="Concluido",
            )
            self.assertTrue(res["ok"])
            self.assertTrue(res["requer_confirmacao"])
            self.assertIn("confirma movimentacao", res["mensagem"])
            mock_api.assert_not_called()

            pendente = github_integration.obter_acao_pendente()
            self.assertEqual(pendente["tipo"], "mover_cartao")
            self.assertEqual(pendente["issue_ref"], "16")
            self.assertEqual(pendente["coluna"], "Concluido")

    def test_confirmar_acao_pendente_cria_issue_com_sucesso(self):
        github_integration.propor_criacao_issue(repo="Nextor", titulo="Issue testada")
        resp_mock = {"number": 99, "html_url": "https://github.com/ThiagoVenturim/Nextor/issues/99"}

        with mock.patch("nextor.github_integration.fazer_requisicao_api", return_value=(201, resp_mock)) as mock_api:
            res = github_integration.confirmar_acao_pendente()
            self.assertTrue(res["ok"])
            self.assertEqual(res["acao"], "criar_issue")
            self.assertEqual(res["numero"], 99)
            self.assertIn("Issue #99 criada com sucesso", res["mensagem"])

            mock_api.assert_called_once_with(
                "/repos/ThiagoVenturim/Nextor/issues",
                metodo="POST",
                dados={"title": "Issue testada", "body": ""},
                token=None,
                handler_requisicao=None,
            )
            # Acao limpa apos confirmacao
            self.assertIsNone(github_integration.obter_acao_pendente())

    def test_confirmar_acao_pendente_move_cartao_com_sucesso(self):
        github_integration.propor_movimentacao_cartao(issue_ref=16, coluna="Concluido")
        with mock.patch("nextor.github_integration.fazer_requisicao_api", return_value=(200, {"state": "closed"})) as mock_api:
            res = github_integration.confirmar_acao_pendente()
            self.assertTrue(res["ok"])
            self.assertEqual(res["acao"], "mover_cartao")
            self.assertEqual(res["issue_ref"], "16")
            self.assertIn("movido para 'Concluido'", res["mensagem"])

            mock_api.assert_called_once_with(
                "/repos/ThiagoVenturim/Nextor/issues/16",
                metodo="PATCH",
                dados={"state": "closed"},
                token=None,
                handler_requisicao=None,
            )
            self.assertIsNone(github_integration.obter_acao_pendente())

    def test_cancelar_acao_pendente_descarta_sem_executar(self):
        github_integration.propor_criacao_issue(repo="Nextor", titulo="Issue que sera cancelada")
        self.assertIsNotNone(github_integration.obter_acao_pendente())

        with mock.patch("nextor.github_integration.fazer_requisicao_api") as mock_api:
            res = github_integration.cancelar_acao_pendente()
            self.assertTrue(res["ok"])
            self.assertIn("cancelada com sucesso", res["mensagem"])
            mock_api.assert_not_called()
            self.assertIsNone(github_integration.obter_acao_pendente())

    def test_confirmar_sem_acao_pendente_retorna_erro(self):
        github_integration.limpar_acao_pendente()
        res = github_integration.confirmar_acao_pendente()
        self.assertFalse(res["ok"])
        self.assertEqual(res["erro"], "nenhuma_acao_pendente")


class TestGatilhosRoteador(BaseGitHubTestCase):
    def test_gatilho_kanban(self):
        with mock.patch("nextor.github_integration.resumo_kanban_por_voz", return_value="Voce tem 2 tarefas no kanban.") as mock_kb:
            r1 = roteador.rotear("o que tem no meu kanban")
            self.assertEqual(r1["intencao"], "github_kanban")
            self.assertEqual(r1["resposta"], "Voce tem 2 tarefas no kanban.")

            r2 = roteador.rotear("ver kanban")
            self.assertEqual(r2["intencao"], "github_kanban")
            mock_kb.assert_called()

    def test_gatilho_issues(self):
        with mock.patch("nextor.github_integration.resumo_issues_por_voz", return_value="Voce tem 3 issues abertas.") as mock_iss:
            r1 = roteador.rotear("minhas issues")
            self.assertEqual(r1["intencao"], "github_issues")
            self.assertEqual(r1["resposta"], "Voce tem 3 issues abertas.")

            r2 = roteador.rotear("listar issues")
            self.assertEqual(r2["intencao"], "github_issues")
            mock_iss.assert_called()

    def test_gatilho_cria_issue(self):
        with mock.patch("nextor.github_integration.propor_criacao_issue", return_value={"ok": True, "mensagem": "Vou criar a issue 'arrumar som'."}) as mock_prop:
            r = roteador.rotear("cria uma issue no Nextor: arrumar som")
            self.assertEqual(r["intencao"], "github_propor_issue")
            self.assertEqual(r["resposta"], "Vou criar a issue 'arrumar som'.")
            mock_prop.assert_called_with(repo="Nextor", titulo="arrumar som")

    def test_gatilho_move_cartao(self):
        with mock.patch("nextor.github_integration.propor_movimentacao_cartao", return_value={"ok": True, "mensagem": "Vou mover o cartao da issue #16 para Concluido."}) as mock_mov:
            r = roteador.rotear("move o cartao da issue 16 para Concluido")
            self.assertEqual(r["intencao"], "github_propor_mover")
            self.assertEqual(r["resposta"], "Vou mover o cartao da issue #16 para Concluido.")
            mock_mov.assert_called_with(issue_ref="16", coluna="Concluido")

    def test_gatilho_confirma_acao(self):
        with mock.patch("nextor.github_integration.confirmar_acao_pendente", return_value={"ok": True, "mensagem": "Issue #17 criada com sucesso."}) as mock_conf:
            r = roteador.rotear("confirma criacao")
            self.assertEqual(r["intencao"], "github_confirmar")
            self.assertEqual(r["resposta"], "Issue #17 criada com sucesso.")
            mock_conf.assert_called_once()

    def test_gatilho_cancela_acao(self):
        with mock.patch("nextor.github_integration.cancelar_acao_pendente", return_value={"ok": True, "mensagem": "Operacao cancelada."}) as mock_canc:
            r = roteador.rotear("cancela criacao")
            self.assertEqual(r["intencao"], "github_cancelar")
            self.assertEqual(r["resposta"], "Operacao cancelada.")
            mock_canc.assert_called_once()


class TestEndpointsHTTP(BaseGitHubTestCase):
    def test_bloqueio_sem_token_mestre_retorna_401(self):
        endpoints = [
            ("get", "/v1/github/kanban", None),
            ("get", "/v1/github/issues", None),
            ("post", "/v1/github/issues", {"titulo": "Teste"}),
            ("post", "/v1/github/kanban/mover", {"issue": "1", "coluna": "Done"}),
            ("post", "/v1/github/confirmar", {}),
            ("post", "/v1/github/cancelar", {}),
        ]
        for metodo, url, payload in endpoints:
            with self.subTest(url=url):
                if metodo == "post":
                    resp = self.client.post(url, json=payload)
                else:
                    resp = self.client.get(url)
                self.assertEqual(resp.status_code, 401)

    def test_endpoint_kanban_e_issues_com_token_mestre(self):
        with mock.patch("nextor.github_integration.listar_itens_kanban", return_value={"ok": True, "total": 1, "colunas": {}}):
            resp = self.client.get("/v1/github/kanban", headers=self.h_mestre)
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(resp.get_json()["ok"])

        with mock.patch("nextor.github_integration.listar_issues_atribuidas", return_value=[{"numero": 10}]):
            resp = self.client.get("/v1/github/issues", headers=self.h_mestre)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.get_json()["total"], 1)

    def test_fluxo_em_duas_etapas_criacao_issue_e_confirmacao(self):
        # 1. Proposta (sem confirmar)
        resp_prop = self.client.post(
            "/v1/github/issues",
            json={"repo": "Nextor", "titulo": "Nova tarefa por endpoint", "corpo": "Detalhe"},
            headers=self.h_mestre,
        )
        self.assertEqual(resp_prop.status_code, 200)
        dados_prop = resp_prop.get_json()
        self.assertTrue(dados_prop["ok"])
        self.assertTrue(dados_prop["requer_confirmacao"])
        id_acao = dados_prop["id_acao"]

        # 2. Confirmacao explicita
        with mock.patch("nextor.github_integration.fazer_requisicao_api", return_value=(201, {"number": 105})):
            resp_conf = self.client.post(
                "/v1/github/confirmar",
                json={"id_acao": id_acao},
                headers=self.h_mestre,
            )
            self.assertEqual(resp_conf.status_code, 200)
            dados_conf = resp_conf.get_json()
            self.assertTrue(dados_conf["ok"])
            self.assertEqual(dados_conf["numero"], 105)

    def test_fluxo_em_duas_etapas_mover_cartao_e_cancelar(self):
        # 1. Proposta de movimentacao
        resp_prop = self.client.post(
            "/v1/github/kanban/mover",
            json={"issue": "16", "coluna": "Em Progresso"},
            headers=self.h_mestre,
        )
        self.assertEqual(resp_prop.status_code, 200)
        dados_prop = resp_prop.get_json()
        self.assertTrue(dados_prop["ok"])
        self.assertTrue(dados_prop["requer_confirmacao"])

        # 2. Cancelar
        resp_canc = self.client.post("/v1/github/cancelar", json={}, headers=self.h_mestre)
        self.assertEqual(resp_canc.status_code, 200)
        self.assertTrue(resp_canc.get_json()["ok"])
        self.assertIsNone(github_integration.obter_acao_pendente())

    def test_criacao_com_confirmacao_imediata(self):
        with mock.patch("nextor.github_integration.fazer_requisicao_api", return_value=(201, {"number": 110})):
            resp = self.client.post(
                "/v1/github/issues",
                json={"repo": "Nextor", "titulo": "Criacao automatica", "confirmar": True},
                headers=self.h_mestre,
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.get_json()["numero"], 110)


if __name__ == "__main__":
    unittest.main()
