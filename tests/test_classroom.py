"""Testes unitarios offline do modulo de integracao com Google Sala de Aula (Issue #18)."""
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

os.environ["NEXTOR_VOZ_SAIDA"] = "nenhuma"

from nextor import config, google_classroom, pendencias, roteador, servico

# Fuso horario padrao de teste
FUSO_TESTE = ZoneInfo("America/Sao_Paulo")

# Fixtures de teste
MOCK_COURSES_JSON = {
    "courses": [
        {
            "id": "101",
            "name": "Fisica I",
            "section": "Turma A",
            "descriptionHeading": "Mecanica Classica",
            "room": "Sala 10",
            "alternateLink": "https://classroom.google.com/c/101",
            "courseState": "ACTIVE",
        },
        {
            "id": "102",
            "name": "Calculo Diferencial",
            "section": "Turma B",
            "descriptionHeading": "Limites e Derivadas",
            "room": "Sala 20",
            "alternateLink": "https://classroom.google.com/c/102",
            "courseState": "ACTIVE",
        },
        {"id": "103", "name": ""},       # Descarta: sem nome
        {"id": "", "name": "Sem ID"},    # Descarta: sem id
    ]
}

# Agora de referencia: 05/11/2026 as 14:00 no fuso America/Sao_Paulo (UTC 17:00)
AGORA_REFERENCIA = datetime(2026, 11, 5, 14, 0, tzinfo=FUSO_TESTE)

MOCK_COURSEWORK_101 = {
    "courseWork": [
        {
            "id": "1001",
            "title": "Lista 1 - Vetores e Forcas",
            "description": "Resolver exercicios do capitulo 2",
            "dueDate": {"year": 2026, "month": 11, "day": 4},
            "dueTime": {"hours": 23, "minutes": 59},  # Ontem -> atrasada
            "maxPoints": 10.0,
            "alternateLink": "https://classroom.google.com/c/101/a/1001",
            "materials": [
                {
                    "driveFile": {
                        "driveFile": {
                            "title": "Lista1.pdf",
                            "alternateLink": "https://drive.google.com/file/1001",
                        }
                    }
                },
                {
                    "link": {
                        "title": "Portal de Apoio",
                        "url": "https://exemplo.org/fisica",
                    }
                },
                {
                    "youtubeVideo": {
                        "title": "Resolucao de Vetores",
                        "alternateLink": "https://youtube.com/watch?v=vetores",
                    }
                },
            ],
        },
        {
            "id": "1002",
            "title": "Laboratorio 1 - Movimento Retilineo",
            "description": "Entrega dos dados coletados em aula",
            "dueDate": {"year": 2026, "month": 11, "day": 5},
            "dueTime": {"hours": 15, "minutes": 0},  # 15:00 UTC -> 12:00 local (ja passou das 14:00) -> para hoje e atrasada
            "maxPoints": 20.0,
            "alternateLink": "https://classroom.google.com/c/101/a/1002",
        },
        {
            "id": "1003",
            "title": "Questionario 1 - Leis de Newton",
            "description": "Questionario conceitual",
            "dueDate": {"year": 2026, "month": 11, "day": 5},
            "dueTime": {"hours": 23, "minutes": 0},  # 23:00 UTC -> 20:00 local (depois das 14:00) -> para hoje, nao atrasada
            "maxPoints": 5.0,
            "alternateLink": "https://classroom.google.com/c/101/a/1003",
        },
        {
            "id": "1004",
            "title": "Relatorio de Gravitacao",
            "description": "Sem hora especificada, apenas data de hoje",
            "dueDate": {"year": 2026, "month": 11, "day": 5},
            "dueTime": None,  # Padrao 23:59:59 local -> para hoje, nao atrasada
            "maxPoints": 15.0,
            "alternateLink": "https://classroom.google.com/c/101/a/1004",
        },
        {
            "id": "1005",
            "title": "Projeto Final - Colisoes",
            "description": "Trabalho em grupo para a proxima semana",
            "dueDate": {"year": 2026, "month": 11, "day": 12},
            "dueTime": {"hours": 23, "minutes": 59},  # Futura
            "maxPoints": 50.0,
            "alternateLink": "https://classroom.google.com/c/101/a/1005",
        },
        {
            "id": "1006",
            "title": "Atividade Sem Prazo",
            "description": "Leitura complementar sem data de entrega",
            "dueDate": None,
            "dueTime": None,
            "alternateLink": "https://classroom.google.com/c/101/a/1006",
        },
        {
            "id": "1007",
            "title": "Tarefa Ja Entregue",
            "description": "Submetida pelo aluno",
            "dueDate": {"year": 2026, "month": 11, "day": 6},
            "dueTime": {"hours": 23, "minutes": 59},
            "alternateLink": "https://classroom.google.com/c/101/a/1007",
        },
    ]
}

MOCK_SUBMISSIONS_101 = {
    "studentSubmissions": [
        {"courseWorkId": "1001", "state": "NEW"},
        {"courseWorkId": "1002", "state": "CREATED"},
        {"courseWorkId": "1007", "state": "TURNED_IN"},  # Entregue
    ]
}

MOCK_COURSEWORK_102 = {
    "courseWork": [
        {
            "id": "2001",
            "title": "Lista 2 - Limites Fundamentais",
            "description": "Exercicios de calculo",
            "dueDate": {"year": 2026, "month": 11, "day": 8},
            "dueTime": {"hours": 23, "minutes": 59},
            "alternateLink": "https://classroom.google.com/c/102/a/2001",
        }
    ]
}

MOCK_ANNOUNCEMENTS_101 = {
    "announcements": [
        {
            "id": "501",
            "text": "A prova bimestral de Fisica foi remarcada para a proxima terca-feira.",
            "creationTime": "2026-11-05T08:00:00Z",
            "alternateLink": "https://classroom.google.com/c/101/p/501",
        },
        {
            "id": "502",
            "text": "Comunicado extenso sobre as normas do laboratorio e seguranca: " + ("detalhes " * 30),
            "creationTime": "2026-11-04T10:00:00Z",
            "alternateLink": "https://classroom.google.com/c/101/p/502",
        },
    ]
}

MOCK_ANNOUNCEMENTS_102 = {
    "announcements": [
        {
            "id": "601",
            "text": "Monitoria de Calculo disponivel hoje as 16h.",
            "creationTime": "2026-11-05T09:00:00Z",
            "alternateLink": "https://classroom.google.com/c/102/p/601",
        }
    ]
}


def _criar_fake_http_client(simular_erro=None):
    """Cria cliente HTTP fake para testes unitarios offline da API Google Classroom."""
    def fake_client(url: str, headers: dict) -> str:
        if simular_erro:
            raise simular_erro

        if "/courses?" in url or url.endswith("/courses"):
            return json.dumps(MOCK_COURSES_JSON)
        if "/courses/101/courseWork/-/studentSubmissions" in url:
            return json.dumps(MOCK_SUBMISSIONS_101)
        if "/courses/101/courseWork" in url:
            return json.dumps(MOCK_COURSEWORK_101)
        if "/courses/102/courseWork" in url:
            return json.dumps(MOCK_COURSEWORK_102)
        if "/courses/101/announcements" in url:
            return json.dumps(MOCK_ANNOUNCEMENTS_101)
        if "/courses/102/announcements" in url:
            return json.dumps(MOCK_ANNOUNCEMENTS_102)
        return json.dumps({})

    return fake_client


class TestEstaConfiguradoEResolverToken(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_esta_configurado_string_direta(self):
        self.assertTrue(google_classroom.esta_configurado(token="ya29.a0AfH6SM...token-direto"))

    def test_esta_configurado_arquivo_json_existente(self):
        arquivo_token = Path(self.tmp.name) / "token.json"
        arquivo_token.write_text(json.dumps({"access_token": "ya29.oauth-token"}), encoding="utf-8")
        self.assertTrue(google_classroom.esta_configurado(token=str(arquivo_token)))

    def test_esta_configurado_vazio_ou_none(self):
        self.assertFalse(google_classroom.esta_configurado(token=""))
        self.assertFalse(google_classroom.esta_configurado(token="   "))
        self.assertFalse(google_classroom.esta_configurado(token=None))

    def test_esta_configurado_arquivo_inexistente(self):
        caminho_inexistente = Path(self.tmp.name) / "inexistente.json"
        self.assertFalse(google_classroom.esta_configurado(token=str(caminho_inexistente)))

    def test_resolver_token_string_direta(self):
        tk = "ya29.token-string-direto"
        self.assertEqual(google_classroom._resolver_bearer_token(tk), tk)

    def test_resolver_token_json_com_access_token(self):
        arquivo_token = Path(self.tmp.name) / "token_access.json"
        arquivo_token.write_text(json.dumps({"access_token": "token-bearer-123"}), encoding="utf-8")
        self.assertEqual(google_classroom._resolver_bearer_token(str(arquivo_token)), "token-bearer-123")

    def test_resolver_token_json_com_token(self):
        arquivo_token = Path(self.tmp.name) / "token_field.json"
        arquivo_token.write_text(json.dumps({"token": "token-bearer-456"}), encoding="utf-8")
        self.assertEqual(google_classroom._resolver_bearer_token(str(arquivo_token)), "token-bearer-456")

    def test_resolver_token_caminho_inexistente(self):
        caminho_inexistente = str(Path(self.tmp.name) / "nao_existe.json")
        self.assertEqual(google_classroom._resolver_bearer_token(caminho_inexistente), "")

    def test_leitura_a_partir_do_config(self):
        with mock.patch.object(config, "GOOGLE_CLASSROOM_TOKEN", "ya29.mock-config-token"):
            self.assertTrue(google_classroom.esta_configurado())
            self.assertEqual(google_classroom._resolver_bearer_token(), "ya29.mock-config-token")


class TestConverterDueDateTime(unittest.TestCase):
    def test_due_date_e_due_time_utc_para_local(self):
        due_date = {"year": 2026, "month": 11, "day": 10}
        due_time = {"hours": 15, "minutes": 30, "seconds": 0}  # 15:30 UTC -> 12:30 America/Sao_Paulo (UTC-3)
        str_prazo, dt_local = google_classroom._converter_due_date_time(due_date, due_time, FUSO_TESTE)

        self.assertEqual(str_prazo, "10/11/2026 12:30")
        self.assertEqual(dt_local, datetime(2026, 11, 10, 12, 30, tzinfo=FUSO_TESTE))

    def test_due_time_omitido_padrao_fim_do_dia_local(self):
        due_date = {"year": 2026, "month": 11, "day": 10}
        str_prazo, dt_local = google_classroom._converter_due_date_time(due_date, None, FUSO_TESTE)

        self.assertEqual(str_prazo, "10/11/2026")
        self.assertEqual(dt_local, datetime(2026, 11, 10, 23, 59, 59, tzinfo=FUSO_TESTE))

    def test_due_date_vazio_ou_invalido(self):
        self.assertEqual(google_classroom._converter_due_date_time(None, None, FUSO_TESTE), (None, None))
        self.assertEqual(google_classroom._converter_due_date_time({}, None, FUSO_TESTE), (None, None))
        self.assertEqual(google_classroom._converter_due_date_time({"year": 2026}, None, FUSO_TESTE), (None, None))


class TestListarCursosAtivos(unittest.TestCase):
    def test_sucesso_com_lista_mockada(self):
        client = _criar_fake_http_client()
        cursos = google_classroom.listar_cursos_ativos(token="fake-token", http_client=client)

        # Cursos 103 (nome vazio) e sem ID devem ser descartados
        self.assertEqual(len(cursos), 2)
        c1 = cursos[0]
        self.assertEqual(c1["id"], "101")
        self.assertEqual(c1["nome"], "Fisica I")
        self.assertEqual(c1["secao"], "Turma A")
        self.assertEqual(c1["sala"], "Sala 10")
        self.assertEqual(c1["estado"], "ACTIVE")

        c2 = cursos[1]
        self.assertEqual(c2["id"], "102")
        self.assertEqual(c2["nome"], "Calculo Diferencial")

    def test_tratamento_gracioso_de_erros(self):
        client_erro = _criar_fake_http_client(simular_erro=RuntimeError("Timeout no Classroom"))
        cursos = google_classroom.listar_cursos_ativos(token="fake-token", http_client=client_erro)
        self.assertEqual(cursos, [])

    def test_retorno_vazio_quando_nao_configurado(self):
        with mock.patch.object(config, "GOOGLE_CLASSROOM_TOKEN", ""):
            self.assertEqual(google_classroom.listar_cursos_ativos(), [])


class TestListarAtividades(unittest.TestCase):
    def setUp(self):
        self.client = _criar_fake_http_client()

    def test_filtro_por_curso_id_e_disciplina(self):
        # Filtro por ID
        at_id = google_classroom.listar_atividades(
            curso_id="101",
            token="fake-token",
            http_client=self.client,
            agora=AGORA_REFERENCIA,
        )
        self.assertTrue(all(a["curso_id"] == "101" for a in at_id))

        # Filtro por nome da disciplina
        at_calc = google_classroom.listar_atividades(
            disciplina_nome="Calculo",
            token="fake-token",
            http_client=self.client,
            agora=AGORA_REFERENCIA,
        )
        self.assertTrue(all("Calculo" in a["disciplina"] for a in at_calc))

        # Filtro por secao
        at_secao = google_classroom.listar_atividades(
            disciplina_nome="Turma A",
            token="fake-token",
            http_client=self.client,
            agora=AGORA_REFERENCIA,
        )
        self.assertTrue(all(a["curso_id"] == "101" for a in at_secao))

    def test_identificacao_tarefas_atrasadas_e_para_hoje(self):
        atividades = google_classroom.listar_atividades(
            curso_id="101",
            apenas_pendentes=False,
            token="fake-token",
            http_client=self.client,
            agora=AGORA_REFERENCIA,
        )
        mapa = {a["titulo"]: a for a in atividades}

        # 1. Ontem (04/11) -> atrasada=True, para_hoje=False
        t_ontem = mapa["Lista 1 - Vetores e Forcas"]
        self.assertTrue(t_ontem["atrasada"])
        self.assertFalse(t_ontem["para_hoje"])

        # 2. Hoje as 12:00 local (agora e 14:00) -> atrasada=True, para_hoje=True
        t_hoje_cedo = mapa["Laboratorio 1 - Movimento Retilineo"]
        self.assertTrue(t_hoje_cedo["atrasada"])
        self.assertTrue(t_hoje_cedo["para_hoje"])

        # 3. Hoje as 20:00 local -> atrasada=False, para_hoje=True
        t_hoje_tarde = mapa["Questionario 1 - Leis de Newton"]
        self.assertFalse(t_hoje_tarde["atrasada"])
        self.assertTrue(t_hoje_tarde["para_hoje"])

        # 4. Hoje sem hora (23:59:59) -> atrasada=False, para_hoje=True
        t_hoje_sem_hora = mapa["Relatorio de Gravitacao"]
        self.assertFalse(t_hoje_sem_hora["atrasada"])
        self.assertTrue(t_hoje_sem_hora["para_hoje"])

        # 5. Semana que vem (12/11) -> atrasada=False, para_hoje=False
        t_futura = mapa["Projeto Final - Colisoes"]
        self.assertFalse(t_futura["atrasada"])
        self.assertFalse(t_futura["para_hoje"])

        # 6. Sem prazo -> atrasada=False, para_hoje=False, prazo=None
        t_sem_prazo = mapa["Atividade Sem Prazo"]
        self.assertFalse(t_sem_prazo["atrasada"])
        self.assertFalse(t_sem_prazo["para_hoje"])
        self.assertIsNone(t_sem_prazo["prazo"])

    def test_submissoes_apenas_pendentes_vs_todas(self):
        # apenas_pendentes=True omite tarefas entregues (ex: 1007 com estado TURNED_IN)
        pendentes = google_classroom.listar_atividades(
            curso_id="101",
            apenas_pendentes=True,
            token="fake-token",
            http_client=self.client,
            agora=AGORA_REFERENCIA,
        )
        titulos_pendentes = [a["titulo"] for a in pendentes]
        self.assertNotIn("Tarefa Ja Entregue", titulos_pendentes)

        # apenas_pendentes=False inclui tarefas entregues
        todas = google_classroom.listar_atividades(
            curso_id="101",
            apenas_pendentes=False,
            token="fake-token",
            http_client=self.client,
            agora=AGORA_REFERENCIA,
        )
        titulos_todas = [a["titulo"] for a in todas]
        self.assertIn("Tarefa Ja Entregue", titulos_todas)

    def test_extracao_de_materiais_anexados(self):
        atividades = google_classroom.listar_atividades(
            curso_id="101",
            token="fake-token",
            http_client=self.client,
            agora=AGORA_REFERENCIA,
        )
        t_mat = next(a for a in atividades if a["titulo"] == "Lista 1 - Vetores e Forcas")
        tipos = [m["tipo"] for m in t_mat["materiais"]]
        self.assertIn("drive", tipos)
        self.assertIn("link", tipos)
        self.assertIn("youtube", tipos)

    def test_ordenacao_por_vencimento_mais_proximo(self):
        atividades = google_classroom.listar_atividades(
            curso_id="101",
            token="fake-token",
            http_client=self.client,
            agora=AGORA_REFERENCIA,
        )
        # O primeiro item deve ser a tarefa atrasada para hoje (prioridade maxima atrasada + hoje)
        self.assertEqual(atividades[0]["titulo"], "Laboratorio 1 - Movimento Retilineo")
        # A ultima deve ser a sem prazo
        self.assertEqual(atividades[-1]["titulo"], "Atividade Sem Prazo")


class TestListarAvisos(unittest.TestCase):
    def setUp(self):
        self.client = _criar_fake_http_client()

    def test_extracao_e_truncamento_de_resumo(self):
        avisos = google_classroom.listar_avisos(
            curso_id="101",
            token="fake-token",
            http_client=self.client,
        )
        self.assertEqual(len(avisos), 2)

        # Aviso curto mantem texto original
        a_curto = next(a for a in avisos if a["id"] == "501")
        self.assertIn("remarcada para a proxima terca-feira", a_curto["resumo"])

        # Aviso longo e truncado em 160 caracteres com reticencias
        a_longo = next(a for a in avisos if a["id"] == "502")
        self.assertTrue(a_longo["resumo"].endswith("..."))
        self.assertLessEqual(len(a_longo["resumo"]), 160)

    def test_filtro_por_disciplina(self):
        avisos_calc = google_classroom.listar_avisos(
            disciplina_nome="Calculo",
            token="fake-token",
            http_client=self.client,
        )
        self.assertEqual(len(avisos_calc), 1)
        self.assertEqual(avisos_calc[0]["disciplina"], "Calculo Diferencial")
        self.assertIn("Monitoria de Calculo", avisos_calc[0]["texto"])

    def test_ordenacao_decrescente_criado_em(self):
        avisos = google_classroom.listar_avisos(
            curso_id="101",
            token="fake-token",
            http_client=self.client,
        )
        # 501 foi criado em 05/11 e 502 em 04/11 -> 501 primeiro
        self.assertEqual(avisos[0]["id"], "501")
        self.assertEqual(avisos[1]["id"], "502")


class TestColetarPendenciasClassroomEIntegracao(unittest.TestCase):
    def setUp(self):
        self.client = _criar_fake_http_client()
        self.tmp = tempfile.TemporaryDirectory()
        self.caminho_anotacoes = Path(self.tmp.name) / "anotacoes.md"
        self.caminho_anotacoes.write_text("- [ ] Estudar fisica\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_formato_padronizado_pendencia(self):
        pendencias_cr = google_classroom.coletar_pendencias_classroom(
            token="fake-token",
            http_client=self.client,
            agora=AGORA_REFERENCIA,
        )
        self.assertTrue(len(pendencias_cr) > 0)
        p = pendencias_cr[0]
        self.assertTrue(p["id"].startswith("classroom:"))
        self.assertEqual(p["fonte"], "classroom")
        self.assertIn("titulo", p)
        self.assertIn("disciplina", p)
        self.assertIn("prazo", p)
        self.assertIn("atrasada", p)
        self.assertIn("para_hoje", p)
        self.assertIn("url", p)
        self.assertIn("curso_id", p)

    def test_integracao_coletar_todas_pendencias_incluir_true(self):
        mock_cr = [
            {
                "id": "classroom:1001",
                "fonte": "classroom",
                "titulo": "Lista 1 - Vetores e Forcas",
                "disciplina": "Fisica I",
                "prazo": "04/11/2026",
                "dt_prazo": datetime(2026, 11, 4, 23, 59, tzinfo=FUSO_TESTE),
                "atrasada": True,
                "para_hoje": False,
                "url": "https://classroom.google.com/1001",
            }
        ]
        todas = pendencias.coletar_todas_pendencias(
            incluir_anotacoes=True,
            incluir_agenda=False,
            incluir_github=False,
            incluir_canvas=False,
            incluir_classroom=True,
            caminho_anotacoes=self.caminho_anotacoes,
            mock_classroom=mock_cr,
        )
        fontes = [p["fonte"] for p in todas]
        self.assertIn("classroom", fontes)
        self.assertIn("anotacoes", fontes)
        self.assertEqual(todas[0]["fonte"], "classroom")  # atrasada tem prioridade maxima

    def test_integracao_coletar_todas_pendencias_incluir_false(self):
        mock_cr = [
            {
                "id": "classroom:1001",
                "fonte": "classroom",
                "titulo": "Lista 1",
                "disciplina": "Fisica I",
                "prazo": "04/11/2026",
                "atrasada": True,
            }
        ]
        todas = pendencias.coletar_todas_pendencias(
            incluir_anotacoes=True,
            incluir_agenda=False,
            incluir_github=False,
            incluir_canvas=False,
            incluir_classroom=False,
            caminho_anotacoes=self.caminho_anotacoes,
            mock_classroom=mock_cr,
        )
        fontes = [p["fonte"] for p in todas]
        self.assertNotIn("classroom", fontes)
        self.assertIn("anotacoes", fontes)


class TestRoteadorClassroom(unittest.TestCase):
    def test_gatilhos_atividades_sem_filtro(self):
        frases = [
            "Quais sao minhas atividades do Google Sala de Aula?",
            "Atividades do Classroom",
            "atividades do google sala de aula",
            "tarefas do sala de aula",
            "minhas atividades do classroom",
        ]
        for frase in frases:
            with self.subTest(frase=frase):
                with mock.patch("nextor.roteador._fazer_classroom_atividades", return_value="Resumo atividades.") as m:
                    res = roteador.rotear(frase)
                    self.assertEqual(res["intencao"], "classroom_atividades")
                    self.assertEqual(res["resposta"], "Resumo atividades.")
                    m.assert_called_once_with()

    def test_gatilho_tarefas_com_filtro_disciplina(self):
        casos = [
            ("Tarefas do Sala de Aula de fisica", "fisica"),
            ("atividades de calculo no classroom", "calculo"),
            ("tarefas de quimica no google sala de aula", "quimica"),
            ("atividades do classroom de biologia", "biologia"),
        ]
        for frase, disc_esperada in casos:
            with self.subTest(frase=frase):
                with mock.patch("nextor.roteador._fazer_classroom_atividades", return_value="Resumo disc.") as m:
                    res = roteador.rotear(frase)
                    self.assertEqual(res["intencao"], "classroom_atividades")
                    self.assertEqual(res["resposta"], "Resumo disc.")
                    m.assert_called_once_with(disciplina=disc_esperada)

    def test_gatilhos_avisos(self):
        casos_avisos = [
            ("Avisos do Classroom", ""),
            ("avisos do google sala de aula", ""),
            ("comunicados do classroom", ""),
            ("Avisos do Sala de Aula de historia", "historia"),
            ("avisos de fisica no classroom", "fisica"),
            ("comunicados de matematica no google sala de aula", "matematica"),
        ]
        for frase, disc_esperada in casos_avisos:
            with self.subTest(frase=frase):
                with mock.patch("nextor.roteador._fazer_classroom_avisos", return_value="Resumo avisos.") as m:
                    res = roteador.rotear(frase)
                    self.assertEqual(res["intencao"], "classroom_avisos")
                    self.assertEqual(res["resposta"], "Resumo avisos.")
                    if disc_esperada:
                        m.assert_called_once_with(disciplina=disc_esperada)
                    else:
                        m.assert_called_once_with()

    def test_resposta_quando_nao_configurado(self):
        with mock.patch("nextor.google_classroom.esta_configurado", return_value=False):
            res_at = roteador.rotear("quais sao minhas atividades do google sala de aula")
            self.assertIn("O Google Sala de Aula nao esta configurado", res_at["resposta"])

            res_av = roteador.rotear("avisos do classroom")
            self.assertIn("O Google Sala de Aula nao esta configurado", res_av["resposta"])


class TestServicoClassroomEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = servico.app.test_client()
        self.token_mestre = "token-teste-classroom-1234567890"
        self.headers_auth = {"X-Nextor-Token": self.token_mestre}

        self.p_token = mock.patch.object(config, "TOKEN", self.token_mestre)
        self.p_token.start()

    def tearDown(self):
        self.p_token.stop()

    def test_endpoints_exigem_token_401(self):
        for ep in ("/v1/classroom/cursos", "/v1/classroom/atividades", "/v1/classroom/avisos"):
            with self.subTest(endpoint=ep):
                r = self.client.get(ep)
                self.assertEqual(r.status_code, 401)

                r_err = self.client.get(ep, headers={"X-Nextor-Token": "token-invalido"})
                self.assertEqual(r_err.status_code, 401)

    def test_endpoints_retornam_503_quando_nao_configurado(self):
        with mock.patch("nextor.google_classroom.esta_configurado", return_value=False):
            for ep in ("/v1/classroom/cursos", "/v1/classroom/atividades", "/v1/classroom/avisos"):
                with self.subTest(endpoint=ep):
                    r = self.client.get(ep, headers=self.headers_auth)
                    self.assertEqual(r.status_code, 503)
                    dados = r.get_json()
                    self.assertFalse(dados["ok"])
                    self.assertIn("Google Sala de Aula nao configurado", dados["erro"])

    def test_cursos_endpoint_retorna_200_quando_configurado(self):
        fake_cursos = [{"id": "101", "nome": "Fisica I", "secao": "Turma A", "sala": "Sala 10"}]
        with mock.patch("nextor.google_classroom.esta_configurado", return_value=True):
            with mock.patch("nextor.google_classroom.listar_cursos_ativos", return_value=fake_cursos):
                r = self.client.get("/v1/classroom/cursos", headers=self.headers_auth)
                self.assertEqual(r.status_code, 200)
                dados = r.get_json()
                self.assertTrue(dados["ok"])
                self.assertEqual(dados["total"], 1)
                self.assertEqual(dados["cursos"][0]["nome"], "Fisica I")

    def test_atividades_endpoint_retorna_200_com_filtros_e_payload(self):
        fake_atividades = [
            {
                "id": "1001",
                "titulo": "Lista 1",
                "curso_id": "101",
                "disciplina": "Fisica I",
                "prazo": "05/11/2026 20:00",
                "dt_prazo": datetime(2026, 11, 5, 20, 0),
                "atrasada": False,
                "para_hoje": True,
                "pontos_maximos": 10.0,
                "url": "https://classroom.google.com/1001",
            }
        ]
        with mock.patch("nextor.google_classroom.esta_configurado", return_value=True):
            with mock.patch("nextor.google_classroom.listar_atividades", return_value=fake_atividades) as m_listar:
                r = self.client.get(
                    "/v1/classroom/atividades?disciplina=fisica&apenas_pendentes=true",
                    headers=self.headers_auth,
                )
                self.assertEqual(r.status_code, 200)
                dados = r.get_json()
                self.assertTrue(dados["ok"])
                self.assertEqual(dados["total"], 1)
                self.assertIn("atividades", dados)
                # dt_prazo removido para serializacao JSON
                self.assertNotIn("dt_prazo", dados["atividades"][0])
                m_listar.assert_called_once_with(
                    curso_id=None,
                    disciplina_nome="fisica",
                    apenas_pendentes=True,
                )

    def test_avisos_endpoint_retorna_200_com_filtros(self):
        fake_avisos = [
            {
                "id": "501",
                "curso_id": "101",
                "disciplina": "Fisica I",
                "texto": "Prova adiada",
                "resumo": "Prova adiada",
                "criado_em": "2026-11-05T08:00:00Z",
                "url": "https://classroom.google.com/501",
            }
        ]
        with mock.patch("nextor.google_classroom.esta_configurado", return_value=True):
            with mock.patch("nextor.google_classroom.listar_avisos", return_value=fake_avisos) as m_avisos:
                r = self.client.get("/v1/classroom/avisos?limite=2&disciplina=fisica", headers=self.headers_auth)
                self.assertEqual(r.status_code, 200)
                dados = r.get_json()
                self.assertTrue(dados["ok"])
                self.assertEqual(dados["total"], 1)
                self.assertEqual(dados["avisos"][0]["id"], "501")
                m_avisos.assert_called_once_with(
                    curso_id=None,
                    disciplina_nome="fisica",
                    limite=2,
                )

    def test_pendencias_com_fonte_classroom(self):
        fake_pendencias = [
            {
                "id": "classroom:1001",
                "fonte": "classroom",
                "titulo": "Lista 1",
                "disciplina": "Fisica I",
                "prazo": "05/11/2026",
                "dt_prazo": datetime(2026, 11, 5, 20, 0),
                "atrasada": False,
                "para_hoje": True,
                "url": "https://classroom.google.com/1001",
            }
        ]
        with mock.patch("nextor.pendencias.coletar_todas_pendencias", return_value=fake_pendencias) as m_todas:
            r = self.client.get("/v1/pendencias?fonte=classroom", headers=self.headers_auth)
            self.assertEqual(r.status_code, 200)
            dados = r.get_json()
            self.assertTrue(dados["ok"])
            self.assertEqual(len(dados["pendencias"]), 1)
            self.assertEqual(dados["pendencias"][0]["fonte"], "classroom")
            m_todas.assert_called_once_with(
                incluir_anotacoes=False,
                incluir_agenda=False,
                incluir_github=False,
                incluir_canvas=False,
                incluir_classroom=True,
            )


class TestResumosFaladosClassroom(unittest.TestCase):
    def test_resumo_atividades_falado(self):
        # Vazio sem disciplina
        self.assertEqual(
            google_classroom.resumo_atividades_falado([]),
            "Voce nao possui nenhuma atividade pendente no Google Sala de Aula.",
        )

        # Vazio com disciplina
        self.assertEqual(
            google_classroom.resumo_atividades_falado([], disciplina="Fisica"),
            "Voce nao possui nenhuma atividade pendente no Google Sala de Aula em Fisica.",
        )

        # Item unico
        at_1 = [{"titulo": "Lista 1", "disciplina": "Fisica", "prazo": "10/11/2026", "atrasada": False, "para_hoje": False}]
        fala_1 = google_classroom.resumo_atividades_falado(at_1)
        self.assertIn("1 atividade pendente", fala_1)
        self.assertIn("'Lista 1' de Fisica", fala_1)
        self.assertIn("prazo para 10/11/2026", fala_1)

        # Multiplos itens com contadores
        at_m = [
            {"titulo": "Lista 1", "disciplina": "Fisica", "prazo": "04/11/2026", "atrasada": True, "para_hoje": False},
            {"titulo": "Lab 1", "disciplina": "Fisica", "prazo": "05/11/2026", "atrasada": False, "para_hoje": True},
        ]
        fala_m = google_classroom.resumo_atividades_falado(at_m)
        self.assertIn("2 atividades no Google Sala de Aula", fala_m)
        self.assertIn("1 atrasada", fala_m)
        self.assertIn("1 para hoje", fala_m)

    def test_resumo_avisos_falado(self):
        # Vazio sem disciplina
        self.assertEqual(
            google_classroom.resumo_avisos_falado([]),
            "Nenhum aviso novo no Google Sala de Aula.",
        )

        # Vazio com disciplina
        self.assertEqual(
            google_classroom.resumo_avisos_falado([], disciplina="Matematica"),
            "Nenhum aviso novo no Google Sala de Aula de Matematica.",
        )

        # Item unico
        av_1 = [{"disciplina": "Fisica", "resumo": "Aula cancelada"}]
        fala_1 = google_classroom.resumo_avisos_falado(av_1)
        self.assertIn("1 aviso no Google Sala de Aula em Fisica: 'Aula cancelada'", fala_1)

        # Multiplos itens
        av_m = [
            {"disciplina": "Fisica", "resumo": "Aula cancelada"},
            {"disciplina": "Calculo", "resumo": "Monitoria"},
        ]
        fala_m = google_classroom.resumo_avisos_falado(av_m)
        self.assertIn("2 avisos no Google Sala de Aula", fala_m)
        self.assertIn("O mais recente em Fisica: 'Aula cancelada'", fala_m)


if __name__ == "__main__":
    unittest.main()
