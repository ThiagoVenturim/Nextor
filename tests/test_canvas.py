"""Testes unitarios offline do modulo de integracao com Canvas LMS (Issue #17)."""
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

os.environ["NEXTOR_VOZ_SAIDA"] = "nenhuma"

from nextor import canvas_lms, config, pendencias, roteador, servico

# Fuso horario de teste
FUSO_TESTE = ZoneInfo("America/Sao_Paulo")

# Fixtures de teste
MOCK_CURSOS_JSON = [
    {"id": 101, "name": "Fisica I", "course_code": "FIS101", "term": {"name": "2026/2"}},
    {"id": 102, "name": "Calculo Diferencial", "course_code": "MAT201", "term": {"name": "2026/2"}},
    {"id": 103, "name": "   ", "course_code": "VAZIO"},
]

# Agora de referencia: 2026-11-05 14:00 (UTC-3) -> 17:00 UTC
AGORA_REFERENCIA = datetime(2026, 11, 5, 14, 0, tzinfo=FUSO_TESTE)

MOCK_TAREFAS_FISICA = [
    {
        "id": 1001,
        "name": "Lista 1 - Vetores e Forcas",
        "due_at": "2026-11-04T23:59:00Z",  # Ontem no fuso local -> atrasada
        "points_possible": 10.0,
        "has_submitted_submissions": False,
        "html_url": "https://canvas.exemplo.edu/courses/101/assignments/1001",
    },
    {
        "id": 1002,
        "name": "Laboratorio 1 - Movimento Retilineo",
        "due_at": "2026-11-05T15:00:00Z",  # Hoje as 12:00 local (antes das 14:00) -> para hoje e atrasada
        "points_possible": 20.0,
        "has_submitted_submissions": False,
        "html_url": "https://canvas.exemplo.edu/courses/101/assignments/1002",
    },
    {
        "id": 1003,
        "name": "Questionario 1 - Leis de Newton",
        "due_at": "2026-11-05T23:00:00Z",  # Hoje as 20:00 local (depois das 14:00) -> para hoje, nao atrasada
        "points_possible": 5.0,
        "has_submitted_submissions": False,
        "html_url": "https://canvas.exemplo.edu/courses/101/assignments/1003",
    },
    {
        "id": 1004,
        "name": "Relatorio de Experimento",
        "due_at": "2026-11-12T23:59:00Z",  # Semana que vem -> futura
        "points_possible": 15.0,
        "has_submitted_submissions": False,
        "html_url": "https://canvas.exemplo.edu/courses/101/assignments/1004",
    },
    {
        "id": 1005,
        "name": "Pesquisa Extra",
        "due_at": None,  # Sem prazo
        "points_possible": 2.0,
        "has_submitted_submissions": False,
        "html_url": "https://canvas.exemplo.edu/courses/101/assignments/1005",
    },
    {
        "id": 1006,
        "name": "Tarefa Ja Entregue",
        "due_at": "2026-11-06T23:59:00Z",
        "points_possible": 10.0,
        "has_submitted_submissions": True,  # Submetida
        "html_url": "https://canvas.exemplo.edu/courses/101/assignments/1006",
    },
]

MOCK_TAREFAS_CALCULO = [
    {
        "id": 2001,
        "name": "Lista 2 - Limites e Derivadas",
        "due_at": "2026-11-07T23:59:00Z",
        "points_possible": 10.0,
        "has_submitted_submissions": False,
        "html_url": "https://canvas.exemplo.edu/courses/102/assignments/2001",
    },
]

MOCK_AVISOS_JSON = [
    {
        "id": 501,
        "title": "Mudanca na data da prova",
        "message": "<p>Prezados alunos,<br>A prova de <b>Fisica</b> foi alterada para a proxima semana. &amp; Bons estudos!</p>",
        "posted_at": "2026-11-05T08:30:00Z",
        "context_code": "course_101",
        "author": {"display_name": "Prof. Newton"},
        "html_url": "https://canvas.exemplo.edu/courses/101/announcements/501",
    },
    {
        "id": 502,
        "title": "Lista de exercicios disponivel",
        "message": "<p>A lista sobre integrais ja se encontra no ar com material de apoio.</p>",
        "posted_at": "2026-11-04T10:00:00Z",
        "context_code": "course_102",
        "author": {"display_name": "Prof. Leibniz"},
        "html_url": "https://canvas.exemplo.edu/courses/102/announcements/502",
    },
]


def _criar_fake_http_client(
    cursos=None,
    tarefas_fisica=None,
    tarefas_calculo=None,
    avisos=None,
    simular_erro=None,
):
    """Cria um cliente HTTP fake para testes unitarios offline da API do Canvas LMS."""
    def fake_client(url: str, headers: dict) -> str:
        if simular_erro:
            raise simular_erro

        if "/api/v1/courses" in url and "/assignments" not in url:
            return json.dumps(cursos if cursos is not None else MOCK_CURSOS_JSON)
        if "/api/v1/courses/101/assignments" in url:
            return json.dumps(tarefas_fisica if tarefas_fisica is not None else MOCK_TAREFAS_FISICA)
        if "/api/v1/courses/102/assignments" in url:
            return json.dumps(tarefas_calculo if tarefas_calculo is not None else MOCK_TAREFAS_CALCULO)
        if "/api/v1/announcements" in url:
            lista_avisos = avisos if avisos is not None else MOCK_AVISOS_JSON
            if "context_codes" in url:
                codigos = []
                if "course_101" in url:
                    codigos.append("course_101")
                if "course_102" in url:
                    codigos.append("course_102")
                if codigos:
                    return json.dumps([a for a in lista_avisos if a.get("context_code") in codigos])
            return json.dumps(lista_avisos)
        return json.dumps([])

    return fake_client


class TestEstaConfigurado(unittest.TestCase):
    def test_retorna_true_quando_ambos_definidos(self):
        self.assertTrue(canvas_lms.esta_configurado(base_url="https://canvas.exemplo.edu", token="token123"))

    def test_retorna_false_quando_url_ou_token_vazios(self):
        self.assertFalse(canvas_lms.esta_configurado(base_url="", token="token123"))
        self.assertFalse(canvas_lms.esta_configurado(base_url="https://canvas.exemplo.edu", token=""))
        self.assertFalse(canvas_lms.esta_configurado(base_url="   ", token="   "))
        self.assertFalse(canvas_lms.esta_configurado(base_url=None, token=None))

    def test_leitura_a_partir_do_config(self):
        with mock.patch.object(config, "CANVAS_BASE_URL", "https://canvas.exemplo.edu"):
            with mock.patch.object(config, "CANVAS_TOKEN", "meu-token-secreto"):
                self.assertTrue(canvas_lms.esta_configurado())

        with mock.patch.object(config, "CANVAS_BASE_URL", ""):
            with mock.patch.object(config, "CANVAS_TOKEN", "meu-token-secreto"):
                self.assertFalse(canvas_lms.esta_configurado())


class TestListarCursosAtivos(unittest.TestCase):
    def test_sucesso_com_lista_mockada_de_cursos(self):
        http_client = _criar_fake_http_client()
        cursos = canvas_lms.listar_cursos_ativos(
            base_url="https://canvas.exemplo.edu",
            token="token123",
            http_client=http_client,
        )
        # Curso com nome vazio (id 103) deve ser descartado
        self.assertEqual(len(cursos), 2)
        self.assertEqual(cursos[0]["id"], 101)
        self.assertEqual(cursos[0]["nome"], "Fisica I")
        self.assertEqual(cursos[0]["codigo"], "FIS101")
        self.assertEqual(cursos[0]["termo"], "2026/2")
        self.assertEqual(cursos[1]["id"], 102)
        self.assertEqual(cursos[1]["nome"], "Calculo Diferencial")

    def test_tratamento_de_erro_http_ou_timeout_retorna_vazio(self):
        http_client_erro = _criar_fake_http_client(simular_erro=RuntimeError("Timeout de conexao com Canvas"))
        cursos = canvas_lms.listar_cursos_ativos(
            base_url="https://canvas.exemplo.edu",
            token="token123",
            http_client=http_client_erro,
        )
        self.assertEqual(cursos, [])

    def test_retorna_vazio_quando_nao_configurado_sem_http_client(self):
        with mock.patch.object(config, "CANVAS_BASE_URL", ""):
            with mock.patch.object(config, "CANVAS_TOKEN", ""):
                self.assertEqual(canvas_lms.listar_cursos_ativos(), [])

    def test_retorna_vazio_quando_resposta_nao_e_lista(self):
        def fake_invalido(url, headers):
            return json.dumps({"erro": "Nao autorizado"})

        cursos = canvas_lms.listar_cursos_ativos(
            base_url="https://canvas.exemplo.edu",
            token="token123",
            http_client=fake_invalido,
        )
        self.assertEqual(cursos, [])


class TestListarTarefas(unittest.TestCase):
    def setUp(self):
        self.http_client = _criar_fake_http_client()

    def test_filtro_por_curso_id(self):
        tarefas = canvas_lms.listar_tarefas(
            curso_id=101,
            base_url="https://canvas.exemplo.edu",
            token="token123",
            agora=AGORA_REFERENCIA,
            http_client=self.http_client,
        )
        # Todos os itens pertencem ao curso 101
        self.assertTrue(all(t["curso_id"] == 101 for t in tarefas))
        nomes = [t["titulo"] for t in tarefas]
        self.assertIn("Lista 1 - Vetores e Forcas", nomes)

    def test_filtro_por_disciplina_nome_e_codigo(self):
        # Matching por nome
        tarefas_fis = canvas_lms.listar_tarefas(
            disciplina_nome="Fisica",
            base_url="https://canvas.exemplo.edu",
            token="token123",
            agora=AGORA_REFERENCIA,
            http_client=self.http_client,
        )
        self.assertTrue(all("Fisica" in t["curso_nome"] for t in tarefas_fis))

        # Matching por codigo
        tarefas_mat = canvas_lms.listar_tarefas(
            disciplina_nome="MAT201",
            base_url="https://canvas.exemplo.edu",
            token="token123",
            agora=AGORA_REFERENCIA,
            http_client=self.http_client,
        )
        self.assertTrue(all("Calculo" in t["curso_nome"] for t in tarefas_mat))

    def test_classificacao_de_prazos_atrasada_e_para_hoje(self):
        tarefas = canvas_lms.listar_tarefas(
            curso_id=101,
            apenas_pendentes=False,
            base_url="https://canvas.exemplo.edu",
            token="token123",
            agora=AGORA_REFERENCIA,
            http_client=self.http_client,
        )
        mapa = {t["titulo"]: t for t in tarefas}

        # 1. Ontem -> atrasada=True, para_hoje=False
        t_ontem = mapa["Lista 1 - Vetores e Forcas"]
        self.assertTrue(t_ontem["atrasada"])
        self.assertFalse(t_ontem["para_hoje"])

        # 2. Hoje antes das 14h -> atrasada=True, para_hoje=True
        t_hoje_cedo = mapa["Laboratorio 1 - Movimento Retilineo"]
        self.assertTrue(t_hoje_cedo["atrasada"])
        self.assertTrue(t_hoje_cedo["para_hoje"])

        # 3. Hoje depois das 14h -> atrasada=False, para_hoje=True
        t_hoje_tarde = mapa["Questionario 1 - Leis de Newton"]
        self.assertFalse(t_hoje_tarde["atrasada"])
        self.assertTrue(t_hoje_tarde["para_hoje"])

        # 4. Semana que vem -> atrasada=False, para_hoje=False
        t_futura = mapa["Relatorio de Experimento"]
        self.assertFalse(t_futura["atrasada"])
        self.assertFalse(t_futura["para_hoje"])

        # 5. Sem prazo
        t_sem_prazo = mapa["Pesquisa Extra"]
        self.assertFalse(t_sem_prazo["atrasada"])
        self.assertFalse(t_sem_prazo["para_hoje"])
        self.assertIsNone(t_sem_prazo["prazo"])

    def test_filtro_apenas_pendentes_ignora_submetidas(self):
        # Com apenas_pendentes=True, tarefa submetida (1006) deve ser omitida
        pendentes = canvas_lms.listar_tarefas(
            curso_id=101,
            apenas_pendentes=True,
            base_url="https://canvas.exemplo.edu",
            token="token123",
            agora=AGORA_REFERENCIA,
            http_client=self.http_client,
        )
        titulos_pendentes = [t["titulo"] for t in pendentes]
        self.assertNotIn("Tarefa Ja Entregue", titulos_pendentes)

        # Com apenas_pendentes=False, tarefa submetida deve estar presente
        todas = canvas_lms.listar_tarefas(
            curso_id=101,
            apenas_pendentes=False,
            base_url="https://canvas.exemplo.edu",
            token="token123",
            agora=AGORA_REFERENCIA,
            http_client=self.http_client,
        )
        titulos_todas = [t["titulo"] for t in todas]
        self.assertIn("Tarefa Ja Entregue", titulos_todas)

    def test_ordenacao_por_vencimento_mais_proximo(self):
        tarefas = canvas_lms.listar_tarefas(
            curso_id=101,
            apenas_pendentes=True,
            base_url="https://canvas.exemplo.edu",
            token="token123",
            agora=AGORA_REFERENCIA,
            http_client=self.http_client,
        )
        # O primeiro item deve ser a tarefa mais antiga (ontem)
        self.assertEqual(tarefas[0]["titulo"], "Lista 1 - Vetores e Forcas")
        # Tarefa sem prazo fica por ultimo
        self.assertEqual(tarefas[-1]["titulo"], "Pesquisa Extra")


class TestListarAvisos(unittest.TestCase):
    def setUp(self):
        self.http_client = _criar_fake_http_client()

    def test_limpeza_de_tags_html_e_entidades(self):
        avisos = canvas_lms.listar_avisos(
            curso_id=101,
            base_url="https://canvas.exemplo.edu",
            token="token123",
            http_client=self.http_client,
        )
        self.assertEqual(len(avisos), 1)
        aviso = avisos[0]
        self.assertEqual(aviso["titulo"], "Mudanca na data da prova")
        self.assertEqual(aviso["autor"], "Prof. Newton")
        self.assertEqual(aviso["curso_nome"], "Fisica I")
        # Sem tags <p>, <br>, <b> e com &amp; convertido para &
        self.assertNotIn("<p>", aviso["mensagem"])
        self.assertNotIn("<b>", aviso["mensagem"])
        self.assertIn("&", aviso["mensagem"])
        self.assertIn("Bons estudos!", aviso["mensagem"])

    def test_filtro_de_avisos_por_disciplina(self):
        avisos = canvas_lms.listar_avisos(
            disciplina_nome="Calculo",
            base_url="https://canvas.exemplo.edu",
            token="token123",
            http_client=self.http_client,
        )
        self.assertEqual(len(avisos), 1)
        self.assertEqual(avisos[0]["curso_nome"], "Calculo Diferencial")
        self.assertEqual(avisos[0]["autor"], "Prof. Leibniz")

    def test_truncamento_de_mensagem_longa(self):
        aviso_longo = [{
            "id": 999,
            "title": "Aviso Extenso",
            "message": "Palavra " * 50,
            "posted_at": "2026-11-05T10:00:00Z",
            "context_code": "course_101",
            "author": {"display_name": "Coordenador"},
        }]
        client = _criar_fake_http_client(avisos=aviso_longo)
        avisos = canvas_lms.listar_avisos(
            base_url="https://canvas.exemplo.edu",
            token="token123",
            http_client=client,
        )
        self.assertTrue(avisos[0]["mensagem"].endswith("..."))
        self.assertLessEqual(len(avisos[0]["mensagem"]), 163)


class TestColetarPendenciasCanvas(unittest.TestCase):
    def test_retorno_estruturado_no_formato_padrao(self):
        http_client = _criar_fake_http_client()
        pendencias_cv = canvas_lms.coletar_pendencias_canvas(
            base_url="https://canvas.exemplo.edu",
            token="token123",
            agora=AGORA_REFERENCIA,
            http_client=http_client,
        )
        self.assertTrue(len(pendencias_cv) > 0)
        p = pendencias_cv[0]
        self.assertTrue(p["id"].startswith("canvas:"))
        self.assertEqual(p["fonte"], "canvas")
        self.assertIn("titulo", p)
        self.assertIn("disciplina", p)
        self.assertIn("prazo", p)
        self.assertIn("atrasada", p)
        self.assertIn("para_hoje", p)
        self.assertIn("url", p)

    def test_comportamento_seguro_quando_nao_configurado(self):
        with mock.patch.object(config, "CANVAS_BASE_URL", ""):
            with mock.patch.object(config, "CANVAS_TOKEN", ""):
                self.assertEqual(canvas_lms.coletar_pendencias_canvas(), [])


class TestIntegracaoPendenciasMultifonte(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.caminho_anotacoes = Path(self.tmp.name) / "anotacoes.md"
        self.caminho_anotacoes.write_text("- [ ] Estudar fisica\n", encoding="utf-8")

        self.mock_canvas_items = [
            {
                "id": "canvas:101#1001",
                "fonte": "canvas",
                "titulo": "Lista 1 - Vetores e Forcas",
                "disciplina": "Fisica I",
                "prazo": "2026-11-04 20:59",
                "dt_prazo": datetime(2026, 11, 4, 20, 59, tzinfo=FUSO_TESTE),
                "atrasada": True,
                "para_hoje": False,
                "url": "https://canvas.exemplo.edu/courses/101/assignments/1001",
            }
        ]

    def tearDown(self):
        self.tmp.cleanup()

    def test_incluir_canvas_true_agrega_tarefas(self):
        todas = pendencias.coletar_todas_pendencias(
            incluir_anotacoes=True,
            incluir_agenda=False,
            incluir_github=False,
            incluir_canvas=True,
            caminho_anotacoes=self.caminho_anotacoes,
            mock_canvas=self.mock_canvas_items,
        )
        fontes = [p["fonte"] for p in todas]
        self.assertIn("canvas", fontes)
        self.assertIn("anotacoes", fontes)
        self.assertEqual(todas[0]["fonte"], "canvas")  # atrasada tem prioridade maxima

    def test_incluir_canvas_false_ignora_tarefas(self):
        todas = pendencias.coletar_todas_pendencias(
            incluir_anotacoes=True,
            incluir_agenda=False,
            incluir_github=False,
            incluir_canvas=False,
            caminho_anotacoes=self.caminho_anotacoes,
            mock_canvas=self.mock_canvas_items,
        )
        fontes = [p["fonte"] for p in todas]
        self.assertNotIn("canvas", fontes)
        self.assertIn("anotacoes", fontes)


class TestRoteadorCanvas(unittest.TestCase):
    def test_gatilho_tarefas_canvas_sem_filtro(self):
        frases = [
            "Quais sao minhas tarefas do Canvas?",
            "quais sao as tarefas do canvas",
            "tarefas do canvas",
            "o que tenho no canvas",
        ]
        for frase in frases:
            with self.subTest(frase=frase):
                with mock.patch("nextor.roteador._fazer_canvas_tarefas", return_value="Resumo tarefas.") as m:
                    res = roteador.rotear(frase)
                    self.assertEqual(res["intencao"], "canvas_tarefas")
                    self.assertEqual(res["resposta"], "Resumo tarefas.")
                    m.assert_called_once_with()

    def test_gatilho_tarefas_com_filtro_de_disciplina(self):
        casos = [
            ("Tarefas de fisica no Canvas", "fisica"),
            ("quais sao as tarefas de calculo no canvas", "calculo"),
            ("tarefas do canvas de algebra", "algebra"),
        ]
        for frase, disc_esperada in casos:
            with self.subTest(frase=frase):
                with mock.patch("nextor.roteador._fazer_canvas_tarefas", return_value="Resumo disciplina.") as m:
                    res = roteador.rotear(frase)
                    self.assertEqual(res["intencao"], "canvas_tarefas")
                    self.assertEqual(res["resposta"], "Resumo disciplina.")
                    m.assert_called_once_with(disciplina=disc_esperada)

    def test_gatilho_avisos_canvas_sem_filtro(self):
        frases = [
            "Avisos do Canvas",
            "avisos no canvas",
            "anuncios do canvas",
            "ultimos avisos do canvas",
        ]
        for frase in frases:
            with self.subTest(frase=frase):
                with mock.patch("nextor.roteador._fazer_canvas_avisos", return_value="Resumo avisos.") as m:
                    res = roteador.rotear(frase)
                    self.assertEqual(res["intencao"], "canvas_avisos")
                    self.assertEqual(res["resposta"], "Resumo avisos.")
                    m.assert_called_once_with()

    def test_gatilho_avisos_com_filtro_de_disciplina(self):
        casos = [
            ("avisos de calculo no canvas", "calculo"),
            ("anuncios de fisica no canvas", "fisica"),
        ]
        for frase, disc_esperada in casos:
            with self.subTest(frase=frase):
                with mock.patch("nextor.roteador._fazer_canvas_avisos", return_value="Resumo avisos disc.") as m:
                    res = roteador.rotear(frase)
                    self.assertEqual(res["intencao"], "canvas_avisos")
                    self.assertEqual(res["resposta"], "Resumo avisos disc.")
                    m.assert_called_once_with(disciplina=disc_esperada)

    def test_resposta_quando_canvas_nao_configurado(self):
        with mock.patch("nextor.canvas_lms.esta_configurado", return_value=False):
            res_tarefas = roteador.rotear("quais sao minhas tarefas do canvas")
            self.assertIn("O Canvas LMS nao esta configurado", res_tarefas["resposta"])

            res_avisos = roteador.rotear("avisos do canvas")
            self.assertIn("O Canvas LMS nao esta configurado", res_avisos["resposta"])


class TestServicoCanvasEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = servico.app.test_client()
        self.token_mestre = "token-teste-canvas-super-secreto-12345"
        self.headers_auth = {"X-Nextor-Token": self.token_mestre}

        self.p_token = mock.patch.object(config, "TOKEN", self.token_mestre)
        self.p_token.start()

    def tearDown(self):
        self.p_token.stop()

    def test_endpoints_exigem_token_mestre_401(self):
        for endpoint in ("/v1/canvas/cursos", "/v1/canvas/tarefas", "/v1/canvas/avisos"):
            with self.subTest(endpoint=endpoint):
                r = self.client.get(endpoint)
                self.assertEqual(r.status_code, 401)

                r_invalido = self.client.get(endpoint, headers={"X-Nextor-Token": "token-errado"})
                self.assertEqual(r_invalido.status_code, 401)

    def test_endpoints_retornam_503_quando_nao_configurado(self):
        with mock.patch("nextor.canvas_lms.esta_configurado", return_value=False):
            for endpoint in ("/v1/canvas/cursos", "/v1/canvas/tarefas", "/v1/canvas/avisos"):
                with self.subTest(endpoint=endpoint):
                    r = self.client.get(endpoint, headers=self.headers_auth)
                    self.assertEqual(r.status_code, 503)
                    dados = r.get_json()
                    self.assertFalse(dados["ok"])
                    self.assertIn("Canvas LMS nao configurado", dados["erro"])

    def test_cursos_endpoint_retorna_200_quando_configurado(self):
        fake_cursos = [{"id": 101, "nome": "Fisica I", "codigo": "FIS101", "termo": "2026/2"}]
        with mock.patch("nextor.canvas_lms.esta_configurado", return_value=True):
            with mock.patch("nextor.canvas_lms.listar_cursos_ativos", return_value=fake_cursos):
                r = self.client.get("/v1/canvas/cursos", headers=self.headers_auth)
                self.assertEqual(r.status_code, 200)
                dados = r.get_json()
                self.assertTrue(dados["ok"])
                self.assertEqual(dados["total"], 1)
                self.assertEqual(dados["cursos"][0]["nome"], "Fisica I")

    def test_tarefas_endpoint_retorna_200_com_resumo_e_filtros(self):
        fake_tarefas = [
            {
                "id": 1001,
                "titulo": "Lista 1",
                "curso_id": 101,
                "curso_nome": "Fisica I",
                "prazo": "2026-11-05 20:00",
                "dt_prazo": datetime(2026, 11, 5, 20, 0),
                "atrasada": False,
                "para_hoje": True,
                "pontos": 10.0,
                "submetida": False,
                "url": "https://canvas.exemplo.edu/tarefa/1001",
            }
        ]
        with mock.patch("nextor.canvas_lms.esta_configurado", return_value=True):
            with mock.patch("nextor.canvas_lms.listar_tarefas", return_value=fake_tarefas) as m_listar:
                r = self.client.get(
                    "/v1/canvas/tarefas?disciplina=fisica&apenas_pendentes=true",
                    headers=self.headers_auth,
                )
                self.assertEqual(r.status_code, 200)
                dados = r.get_json()
                self.assertTrue(dados["ok"])
                self.assertEqual(dados["total"], 1)
                self.assertIn("tarefas", dados)
                # dt_prazo deve ser removido do payload json
                self.assertNotIn("dt_prazo", dados["tarefas"][0])
                m_listar.assert_called_once_with(
                    curso_id=None,
                    disciplina_nome="fisica",
                    apenas_pendentes=True,
                )

    def test_avisos_endpoint_retorna_200_com_filtros(self):
        fake_avisos = [
            {
                "id": 501,
                "titulo": "Mudanca de sala",
                "curso_nome": "Calculo",
                "autor": "Prof. Newton",
                "mensagem": "Aula na sala 202.",
                "data": "2026-11-05 08:30",
                "url": "https://canvas.exemplo.edu/avisos/501",
            }
        ]
        with mock.patch("nextor.canvas_lms.esta_configurado", return_value=True):
            with mock.patch("nextor.canvas_lms.listar_avisos", return_value=fake_avisos) as m_avisos:
                r = self.client.get("/v1/canvas/avisos?limite=3&disciplina=calculo", headers=self.headers_auth)
                self.assertEqual(r.status_code, 200)
                dados = r.get_json()
                self.assertTrue(dados["ok"])
                self.assertEqual(dados["total"], 1)
                self.assertEqual(dados["avisos"][0]["titulo"], "Mudanca de sala")
                m_avisos.assert_called_once_with(
                    curso_id=None,
                    disciplina_nome="calculo",
                    limite=3,
                )

    def test_pendencias_endpoint_com_filtro_fonte_canvas(self):
        fake_pendencias = [
            {
                "id": "canvas:101#1001",
                "fonte": "canvas",
                "titulo": "Lista 1",
                "disciplina": "Fisica I",
                "prazo": "2026-11-05 20:00",
                "dt_prazo": datetime(2026, 11, 5, 20, 0),
                "atrasada": False,
                "para_hoje": True,
                "url": "https://canvas.exemplo.edu/1001",
            }
        ]
        with mock.patch("nextor.pendencias.coletar_todas_pendencias", return_value=fake_pendencias) as m_todas:
            r = self.client.get("/v1/pendencias?fonte=canvas", headers=self.headers_auth)
            self.assertEqual(r.status_code, 200)
            dados = r.get_json()
            self.assertTrue(dados["ok"])
            self.assertEqual(len(dados["pendencias"]), 1)
            self.assertEqual(dados["pendencias"][0]["fonte"], "canvas")
            m_todas.assert_called_once_with(
                incluir_anotacoes=False,
                incluir_agenda=False,
                incluir_github=False,
                incluir_canvas=True,
            )

        # Teste quando fonte=github desativa o canvas
        with mock.patch("nextor.pendencias.coletar_todas_pendencias", return_value=[]) as m_sem_canvas:
            r_gh = self.client.get("/v1/pendencias?fonte=github", headers=self.headers_auth)
            self.assertEqual(r_gh.status_code, 200)
            m_sem_canvas.assert_called_once_with(
                incluir_anotacoes=False,
                incluir_agenda=False,
                incluir_github=True,
                incluir_canvas=False,
            )


class TestResumosFaladosCanvas(unittest.TestCase):
    def test_resumo_tarefas_falado_vazio(self):
        fala_geral = canvas_lms.resumo_tarefas_falado([])
        self.assertIn("Voce nao tem tarefas pendentes no Canvas.", fala_geral)

        fala_disc = canvas_lms.resumo_tarefas_falado([], disciplina="Fisica")
        self.assertIn("Voce nao tem tarefas pendentes no Canvas em Fisica.", fala_disc)

    def test_resumo_tarefas_falado_com_itens(self):
        tarefas = [
            {"titulo": "Lista 1", "curso_nome": "Fisica I", "atrasada": True, "para_hoje": False},
            {"titulo": "Lab 1", "curso_nome": "Fisica I", "atrasada": False, "para_hoje": True},
        ]
        fala = canvas_lms.resumo_tarefas_falado(tarefas)
        self.assertIn("2 tarefas pendentes", fala)
        self.assertIn("1 para hoje", fala)
        self.assertIn("1 atrasadas", fala)
        self.assertIn("Lista 1 (Fisica I)", fala)

    def test_resumo_avisos_falado_vazio_e_com_itens(self):
        self.assertEqual(canvas_lms.resumo_avisos_falado([]), "Nenhum aviso novo no Canvas.")
        self.assertEqual(
            canvas_lms.resumo_avisos_falado([], disciplina="Calculo"),
            "Nenhum aviso novo no Canvas para Calculo.",
        )

        aviso_unico = [{"titulo": "Prova adiada", "curso_nome": "Fisica I"}]
        fala_1 = canvas_lms.resumo_avisos_falado(aviso_unico)
        self.assertIn("1 aviso de Fisica I: 'Prova adiada'", fala_1)

        avisos_multiplos = [
            {"titulo": "Aviso 1", "curso_nome": "Fisica I"},
            {"titulo": "Aviso 2", "curso_nome": "Calculo"},
        ]
        fala_m = canvas_lms.resumo_avisos_falado(avisos_multiplos)
        self.assertIn("2 avisos recentes", fala_m)
        self.assertIn("'Aviso 1' em Fisica I", fala_m)


if __name__ == "__main__":
    unittest.main()
