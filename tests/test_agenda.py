"""Testes unitarios offline para o modulo de calendario, reunioes e timeboxing (Issue #51).

Verificacoes sem rede (NEXTOR_VOZ_SAIDA=nenhuma, mocks de relogio e notificacoes):
1. Parsing de eventos com e sem link de videoconferencia / participantes e classificacao de reuniao.
2. Deteccao de conflitos de horario e calculo de blocos livres a partir de agenda sintetica.
3. Sugestoes de timeboxing nos espacos livres e aviso de dia cheio / sobrecarga.
4. Disparo de lembretes antecipados e abertura de link no horario com relogio mock.
5. Ferramentas MCP (agenda_dia, proxima_reuniao, blocos_livres) sobre dados sinteticos.
6. Roteamento de comandos de voz ('qual minha proxima reuniao', 'como esta meu dia').
7. Integracao com GTD: criacao de tarefa a partir de evento e evento a partir de tarefa com prazo.
8. Seguranca: novos endpoints HTTP em servico.py exigem token mestre (401 sem token, 200 com token).
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

from nextor import agenda, config, mcp_server, roteador, servico
from nextor.gtd import ArmazenamentoGTD, agenda_do_dia, criar_tarefa_de_evento, criar_evento_de_tarefa
from nextor.gtd.configuracao import carregar_config, salvar_config

TZ = agenda.TZ


class TestAgendaParsing(unittest.TestCase):
    """Testa parsing de eventos e classificacao de reunioes."""

    def setUp(self):
        agenda.limpar_alertas_reuniao()

    def test_deteccao_links_videoconferencia(self):
        texto_meet = "Acesso pela sala: https://meet.google.com/abc-defg-hij."
        texto_zoom = "Reuniao Zoom: https://us02web.zoom.us/j/123456789?pwd=xyz"
        texto_teams = "Entre no Teams: https://teams.microsoft.com/l/meetup-join/19%3ameeting"
        texto_sem = "Almoco presencial no refeitorio da firma."

        self.assertEqual(agenda.extrair_link_video(texto_meet), "https://meet.google.com/abc-defg-hij")
        self.assertEqual(agenda.extrair_link_video(texto_zoom), "https://us02web.zoom.us/j/123456789?pwd=xyz")
        self.assertTrue(agenda.extrair_link_video(texto_teams).startswith("https://teams.microsoft.com"))
        self.assertIsNone(agenda.extrair_link_video(texto_sem))

    def test_parsing_evento_sintetico_com_link_video_eh_reuniao(self):
        ev = {
            "titulo": "Daily de Alinhamento",
            "inicio": datetime(2026, 11, 9, 9, 0, tzinfo=TZ),
            "fim": datetime(2026, 11, 9, 9, 30, tzinfo=TZ),
            "descricao": "Link: https://meet.google.com/abc-defg-hij",
        }
        norm = agenda._normaliza(ev)
        self.assertTrue(norm["eh_reuniao"])
        self.assertEqual(norm["link_video"], "https://meet.google.com/abc-defg-hij")
        self.assertEqual(norm["duracao_minutos"], 30)

    def test_parsing_evento_com_participantes_eh_reuniao(self):
        ev = {
            "titulo": "Entrevista Tecnica",
            "inicio": datetime(2026, 11, 9, 14, 0, tzinfo=TZ),
            "fim": datetime(2026, 11, 9, 15, 0, tzinfo=TZ),
            "participantes": ["candidato@exemplo.com", "techlead@exemplo.com"],
        }
        norm = agenda._normaliza(ev)
        self.assertTrue(norm["eh_reuniao"])
        self.assertEqual(len(norm["participantes"]), 2)

    def test_evento_individual_sem_link_nem_participantes_nao_eh_reuniao(self):
        ev = {
            "titulo": "Estudo de Algoritmos",
            "inicio": datetime(2026, 11, 9, 10, 0, tzinfo=TZ),
            "fim": datetime(2026, 11, 9, 11, 30, tzinfo=TZ),
            "descricao": "Capitulo 4 do livro",
        }
        norm = agenda._normaliza(ev)
        self.assertFalse(norm["eh_reuniao"])
        self.assertIsNone(norm["link_video"])

    def test_parser_ics_conteudo_leve(self):
        ics_sintetico = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Nextor//Teste//PT\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:reuniao-planejamento-123\r\n"
            "SUMMARY:Planejamento de Sprint\r\n"
            "DTSTART:20261109T100000\r\n"
            "DTEND:20261109T110000\r\n"
            "DESCRIPTION:Link da sala https://meet.google.com/xyz-uvw-rst\r\n"
            "ATTENDEE:mailto:colega@exemplo.com\r\n"
            "END:VEVENT\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:evento-foco-456\r\n"
            "SUMMARY:Foco em Codigo\r\n"
            "DTSTART:20261109T140000\r\n"
            "DTEND:20261109T160000\r\n"
            "DESCRIPTION:Trabalho individual\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        eventos = agenda.parsear_ics(ics_sintetico)
        self.assertEqual(len(eventos), 2)

        ev_reuniao = eventos[0]
        self.assertEqual(ev_reuniao["titulo"], "Planejamento de Sprint")
        self.assertTrue(ev_reuniao["eh_reuniao"])
        self.assertEqual(ev_reuniao["link_video"], "https://meet.google.com/xyz-uvw-rst")
        self.assertIn("colega@exemplo.com", ev_reuniao["participantes"])

        ev_foco = eventos[1]
        self.assertEqual(ev_foco["titulo"], "Foco em Codigo")
        self.assertFalse(ev_foco["eh_reuniao"])


class TestBlocosLivresEConflitos(unittest.TestCase):
    """Testa deteccao de sobreposicoes e calculo de janelas livres."""

    def setUp(self):
        self.data_ref = date(2026, 11, 9)

    def test_detectar_conflitos_sobreposicao(self):
        ev1 = {
            "titulo": "Reuniao Equipe A",
            "inicio": datetime(2026, 11, 9, 10, 0, tzinfo=TZ),
            "fim": datetime(2026, 11, 9, 11, 0, tzinfo=TZ),
            "dia_inteiro": False,
        }
        ev2 = {
            "titulo": "Reuniao Cliente B",
            "inicio": datetime(2026, 11, 9, 10, 30, tzinfo=TZ),
            "fim": datetime(2026, 11, 9, 11, 30, tzinfo=TZ),
            "dia_inteiro": False,
        }
        ev3 = {
            "titulo": "Almoco",
            "inicio": datetime(2026, 11, 9, 12, 0, tzinfo=TZ),
            "fim": datetime(2026, 11, 9, 13, 0, tzinfo=TZ),
            "dia_inteiro": False,
        }

        conflitos = agenda.detectar_conflitos([ev1, ev2, ev3])
        self.assertEqual(len(conflitos), 1)
        c = conflitos[0]
        self.assertEqual(c["evento1"], "Reuniao Equipe A")
        self.assertEqual(c["evento2"], "Reuniao Cliente B")
        self.assertEqual(c["duracao_minutos"], 30)

    def test_calcular_blocos_livres_no_expediente(self):
        # Expediente 08:00 as 18:00
        # Evento 1: 10:00 as 11:00 -> Bloco 1: 08:00 as 10:00 (120 min)
        # Evento 2: 14:00 as 15:30 -> Bloco 2: 11:00 as 14:00 (180 min)
        #                          -> Bloco 3: 15:30 as 18:00 (150 min)
        ev1 = {
            "titulo": "Alinhamento",
            "inicio": datetime(2026, 11, 9, 10, 0, tzinfo=TZ),
            "fim": datetime(2026, 11, 9, 11, 0, tzinfo=TZ),
            "dia_inteiro": False,
        }
        ev2 = {
            "titulo": "Apresentacao",
            "inicio": datetime(2026, 11, 9, 14, 0, tzinfo=TZ),
            "fim": datetime(2026, 11, 9, 15, 30, tzinfo=TZ),
            "dia_inteiro": False,
        }

        blocos = agenda.calcular_blocos_livres([ev1, ev2], data_ref=self.data_ref, inicio_dia="08:00", fim_dia="18:00")
        self.assertEqual(len(blocos), 3)

        self.assertEqual(blocos[0]["inicio_str"], "08:00")
        self.assertEqual(blocos[0]["fim_str"], "10:00")
        self.assertEqual(blocos[0]["duracao_minutos"], 120)

        self.assertEqual(blocos[1]["inicio_str"], "11:00")
        self.assertEqual(blocos[1]["fim_str"], "14:00")
        self.assertEqual(blocos[1]["duracao_minutos"], 180)

        self.assertEqual(blocos[2]["inicio_str"], "15:30")
        self.assertEqual(blocos[2]["fim_str"], "18:00")
        self.assertEqual(blocos[2]["duracao_minutos"], 150)


class TestTimeboxingEAnaliseDia(unittest.TestCase):
    """Testa sugestoes de timeboxing (estudos, academia, leitura) e aviso de dia cheio."""

    def test_sugestoes_timeboxing_distribui_contextos(self):
        blocos = [
            {"inicio": datetime(2026, 11, 9, 8, 0, tzinfo=TZ), "fim": datetime(2026, 11, 9, 10, 0, tzinfo=TZ), "inicio_str": "08:00", "fim_str": "10:00", "duracao_minutos": 120},
            {"inicio": datetime(2026, 11, 9, 11, 0, tzinfo=TZ), "fim": datetime(2026, 11, 9, 12, 0, tzinfo=TZ), "inicio_str": "11:00", "fim_str": "12:00", "duracao_minutos": 60},
            {"inicio": datetime(2026, 11, 9, 16, 0, tzinfo=TZ), "fim": datetime(2026, 11, 9, 16, 30, tzinfo=TZ), "inicio_str": "16:00", "fim_str": "16:30", "duracao_minutos": 30},
        ]
        sugestoes = agenda.sugerir_timeboxing(blocos)
        self.assertEqual(len(sugestoes), 3)

        contextos = [s["contexto"] for s in sugestoes]
        self.assertIn("@faculdade", contextos)
        self.assertIn("@academia", contextos)
        self.assertIn("@leitura", contextos)

    def test_analisar_dia_cheio_detecta_sobrecarga(self):
        # 4 eventos de 1h30m cada = 6 horas ocupadas
        data_ref = date(2026, 11, 9)
        eventos = [
            {"titulo": f"Compromisso {i}", "inicio": datetime(2026, 11, 9, 8 + i * 2, 0, tzinfo=TZ), "fim": datetime(2026, 11, 9, 9 + i * 2, 30, tzinfo=TZ), "dia_inteiro": False, "duracao_minutos": 90, "eh_reuniao": True}
            for i in range(4)
        ]
        analise = agenda.analisar_dia(eventos, data_ref=data_ref, limite_horas_cheio=5.0)
        self.assertTrue(analise["dia_cheio"])
        self.assertGreaterEqual(analise["horas_ocupadas"], 6.0)
        self.assertTrue(len(analise["motivo_dia_cheio"]) > 0)

    def test_analisar_dia_tranquilo(self):
        data_ref = date(2026, 11, 9)
        eventos = [
            {"titulo": "Reuniao Curta", "inicio": datetime(2026, 11, 9, 10, 0, tzinfo=TZ), "fim": datetime(2026, 11, 9, 10, 30, tzinfo=TZ), "dia_inteiro": False, "duracao_minutos": 30, "eh_reuniao": True}
        ]
        analise = agenda.analisar_dia(eventos, data_ref=data_ref, limite_horas_cheio=6.0)
        self.assertFalse(analise["dia_cheio"])
        self.assertEqual(analise["horas_ocupadas"], 0.5)


class TestLembretesEAberturaReunioes(unittest.TestCase):
    """Testa disparo antecipado de lembretes e abertura no horario com relogio mock."""

    def setUp(self):
        agenda.limpar_alertas_reuniao()

    def test_disparo_lembrete_10_minutos_antes(self):
        inicio_reuniao = datetime(2026, 11, 9, 10, 0, tzinfo=TZ)
        fim_reuniao = datetime(2026, 11, 9, 11, 0, tzinfo=TZ)
        ev = {
            "uid": "reuniao-sprint-99",
            "titulo": "Sprint Review",
            "inicio": inicio_reuniao,
            "fim": fim_reuniao,
            "eh_reuniao": True,
            "link_video": "https://meet.google.com/abc-test-xyz",
        }

        notificacoes_mock = []

        def despachante_fake(evento, titulo, corpo, canais_especificos=None):
            notificacoes_mock.append({
                "evento": evento,
                "titulo": titulo,
                "corpo": corpo,
                "canais": canais_especificos,
            })

        # Relogio mock: 09:52 (faltando 8 minutos, dentro da janela de 10 min)
        agora_mock = datetime(2026, 11, 9, 9, 52, tzinfo=TZ)
        res = agenda.lembrar_e_abrir_reunioes(
            [ev],
            agora=agora_mock,
            config_usuario={"agenda": {"lembrete_minutos_antes": 10}},
            despachante_notificacao=despachante_fake,
        )

        self.assertEqual(len(res["lembretes_enviados"]), 1)
        self.assertEqual(len(notificacoes_mock), 1)
        self.assertIn("Sprint Review", notificacoes_mock[0]["corpo"])
        self.assertIn("https://meet.google.com/abc-test-xyz", notificacoes_mock[0]["corpo"])

        # Chamada repetida no mesmo minuto nao duplica alerta
        res2 = agenda.lembrar_e_abrir_reunioes(
            [ev],
            agora=agora_mock,
            despachante_notificacao=despachante_fake,
        )
        self.assertEqual(len(res2["lembretes_enviados"]), 0)
        self.assertEqual(len(notificacoes_mock), 1)

    def test_abertura_reuniao_no_horario(self):
        inicio_reuniao = datetime(2026, 11, 9, 10, 0, tzinfo=TZ)
        fim_reuniao = datetime(2026, 11, 9, 11, 0, tzinfo=TZ)
        ev = {
            "uid": "reuniao-sprint-99",
            "titulo": "Sprint Review",
            "inicio": inicio_reuniao,
            "fim": fim_reuniao,
            "eh_reuniao": True,
            "link_video": "https://meet.google.com/abc-test-xyz",
        }

        urls_abertas = []

        def abridor_fake(url):
            urls_abertas.append(url)

        notificacoes_mock = []

        def despachante_fake(evento, titulo, corpo, canais_especificos=None):
            notificacoes_mock.append({"titulo": titulo, "corpo": corpo})

        # Relogio mock: 10:00 (hora exata do inicio da reuniao)
        agora_mock = datetime(2026, 11, 9, 10, 0, tzinfo=TZ)
        res = agenda.lembrar_e_abrir_reunioes(
            [ev],
            agora=agora_mock,
            despachante_notificacao=despachante_fake,
            abridor_url=abridor_fake,
            abrir_link_automatico=True,
        )

        self.assertEqual(len(res["aberturas_realizadas"]), 1)
        self.assertEqual(urls_abertas, ["https://meet.google.com/abc-test-xyz"])
        self.assertEqual(len(notificacoes_mock), 1)
        self.assertIn("Reuniao Iniciada", notificacoes_mock[0]["titulo"])


class TestMCPAgenda(unittest.TestCase):
    """Testa ferramentas expostas no servidor MCP sobre dados sinteticos."""

    def setUp(self):
        self.dt_amanha = datetime.now(TZ) + timedelta(days=1)
        self.evs_mock = [
            {
                "uid": "mcp-ev-1",
                "titulo": "Sincronizacao de Arquitetura",
                "inicio": self.dt_amanha.replace(hour=10, minute=0, second=0, microsecond=0),
                "fim": self.dt_amanha.replace(hour=11, minute=0, second=0, microsecond=0),
                "dia_inteiro": False,
                "duracao_minutos": 60,
                "eh_reuniao": True,
                "link_video": "https://meet.google.com/teste-mcp-123",
            },
            {
                "uid": "mcp-ev-2",
                "titulo": "Foco em Refatoracao",
                "inicio": self.dt_amanha.replace(hour=14, minute=0, second=0, microsecond=0),
                "fim": self.dt_amanha.replace(hour=16, minute=0, second=0, microsecond=0),
                "dia_inteiro": False,
                "duracao_minutos": 120,
                "eh_reuniao": False,
                "link_video": None,
            },
        ]

    def test_mcp_proxima_reuniao(self):
        with mock.patch("nextor.agenda.eventos_proximos", return_value=self.evs_mock):
            resposta = mcp_server.proxima_reuniao()
            self.assertIn("Sincronizacao de Arquitetura", resposta)
            self.assertIn("https://meet.google.com/teste-mcp-123", resposta)

    def test_mcp_agenda_dia_com_sugestoes(self):
        with mock.patch("nextor.agenda.eventos_dia", return_value=self.evs_mock):
            resposta = mcp_server.agenda_dia()
            self.assertIn("Compromissos de hoje", resposta)
            self.assertIn("Sincronizacao de Arquitetura", resposta)
            self.assertIn("Espacos livres", resposta)

    def test_mcp_blocos_livres(self):
        with mock.patch("nextor.agenda.eventos_dia", return_value=self.evs_mock):
            resposta = mcp_server.blocos_livres()
            self.assertIn("Blocos livres de hoje", resposta)
            self.assertIn("Sugestoes de foco", resposta)


class TestRoteadorVozAgenda(unittest.TestCase):
    """Testa intencoes de voz para consulta de reunioes e dia no roteador."""

    def test_comando_qual_minha_proxima_reuniao(self):
        ev_mock = {
            "uid": "voz-ev-1",
            "titulo": "Reuniao de Equipe",
            "inicio": datetime(2026, 11, 10, 15, 30, tzinfo=TZ),
            "fim": datetime(2026, 11, 10, 16, 30, tzinfo=TZ),
            "eh_reuniao": True,
            "link_video": "https://meet.google.com/voz-123-abc",
        }
        with mock.patch("nextor.agenda.proxima_reuniao", return_value=ev_mock):
            res = roteador.rotear("qual minha proxima reuniao")
            self.assertEqual(res["intencao"], "proxima_reuniao")
            self.assertIn("Reuniao de Equipe", res["resposta"])
            self.assertIn("15:30", res["resposta"])
            self.assertIn("https://meet.google.com/voz-123-abc", res["resposta"])

    def test_comando_como_esta_meu_dia(self):
        gtd_dia_mock = {
            "resumo_falado": "Voce tem 2 compromissos na agenda, sendo 1 reuniao. 3 proximas acoes.",
        }
        with mock.patch("nextor.gtd.agenda_do_dia", return_value=gtd_dia_mock):
            res = roteador.rotear("como esta meu dia")
            self.assertEqual(res["intencao"], "agenda_dia")
            self.assertIn("Voce tem 2 compromissos", res["resposta"])


class TestGTDIntegracaoAgenda(unittest.TestCase):
    """Testa integracao bidirecional entre GTD e Agenda."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.caminho_db = Path(self.tmp.name) / "gtd_teste.db"
        self.banco = ArmazenamentoGTD(caminho_db=self.caminho_db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_criar_tarefa_a_partir_de_evento(self):
        evento = {
            "uid": "ev-reuniao-projeto-x",
            "titulo": "Alinhamento Projeto X",
            "inicio": datetime(2026, 11, 10, 14, 0, tzinfo=TZ),
            "fim": datetime(2026, 11, 10, 15, 0, tzinfo=TZ),
            "descricao": "Definir metas da sprint",
            "link_video": "https://meet.google.com/proj-x",
        }
        item = criar_tarefa_de_evento(evento, contexto="@trabalho", db=self.banco)
        self.assertEqual(item.titulo, "Alinhamento Projeto X")
        self.assertEqual(item.contexto, "@trabalho")
        self.assertEqual(item.prazo, "2026-11-10")
        self.assertEqual(item.origem, "agenda")
        self.assertIn("https://meet.google.com/proj-x", item.nota)

        # Idempotencia: segunda chamada retorna o item existente sem duplicar
        item_duplicado = criar_tarefa_de_evento(evento, contexto="@trabalho", db=self.banco)
        self.assertEqual(item.id, item_duplicado.id)
        self.assertEqual(len(self.banco.listar_itens()), 1)

    def test_criar_evento_a_partir_de_tarefa_com_prazo(self):
        from nextor.gtd.gtd import capturar
        item = capturar(
            titulo="Preparar Apresentacao do Modulo",
            nota="Slides de 1 a 15",
            contexto="@faculdade",
            prazo="2026-11-12",
            db=self.banco,
        )
        evento = criar_evento_de_tarefa(item.id, horario="14:30", duracao_minutos=90, db=self.banco)
        self.assertEqual(evento["titulo"], "Preparar Apresentacao do Modulo")
        self.assertEqual(evento["duracao_minutos"], 90)
        self.assertEqual(evento["inicio"].strftime("%H:%M"), "14:30")
        self.assertEqual(evento["fim"].strftime("%H:%M"), "16:00")

        # Verifica marcacao na nota do item
        item_atualizado = self.banco.obter_item(item.id)
        self.assertIn("[Agendado para 2026-11-12 14:30]", item_atualizado.nota)


class TestConfiguracaoAgenda(unittest.TestCase):
    """Testa persistencia e validacao das configuracoes da agenda."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.caminho_cfg = Path(self.tmp.name) / "config.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_salvar_config_agenda_validacao(self):
        dados_novos = {
            "agenda": {
                "lembrete_minutos_antes": 15,
                "abrir_link_automatico": False,
                "canais_aviso": ["telegram", "webpush"],
                "expediente_inicio": "09:00",
                "expediente_fim": "19:00",
                "limite_horas_dia_cheio": 7.5,
            }
        }
        salvo = salvar_config(dados_novos, caminho_customizado=self.caminho_cfg)
        cfg_carregada = carregar_config(caminho_customizado=self.caminho_cfg)

        self.assertEqual(cfg_carregada["agenda"]["lembrete_minutos_antes"], 15)
        self.assertFalse(cfg_carregada["agenda"]["abrir_link_automatico"])
        self.assertEqual(cfg_carregada["agenda"]["canais_aviso"], ["telegram", "webpush"])
        self.assertEqual(cfg_carregada["agenda"]["limite_horas_dia_cheio"], 7.5)


class TestServicoRotasAgenda(unittest.TestCase):
    """Testa endpoints HTTP da agenda em servico.py e exigencia de autenticacao com token mestre."""

    def setUp(self):
        self.token_mestre = "token-teste-agenda-super-seguro-12345"
        self.patch_token = mock.patch.object(config, "TOKEN", self.token_mestre)
        self.patch_token.start()
        self.app = servico.app.test_client()

    def tearDown(self):
        self.patch_token.stop()

    def test_rotas_agenda_bloqueadas_sem_token(self):
        rotas = [
            ("GET", "/gtd/agenda/dia", None),
            ("GET", "/gtd/agenda/semana", None),
            ("GET", "/gtd/agenda/proxima-reuniao", None),
            ("GET", "/gtd/agenda/blocos-livres", None),
            ("POST", "/gtd/agenda/tarefa-de-evento", {"evento": {"titulo": "Teste"}}),
            ("POST", "/gtd/agenda/evento-de-tarefa", {"item_id": "123"}),
            ("POST", "/gtd/agenda/abrir-reuniao", {"link": "https://meet.google.com/test"}),
        ]
        for metodo, rota, corpo in rotas:
            if metodo == "GET":
                resp = self.app.get(rota)
            else:
                resp = self.app.post(rota, json=corpo)
            self.assertEqual(
                resp.status_code,
                401,
                msg=f"Rota {rota} deveria exigir autenticacao mas retornou {resp.status_code}",
            )
            dados = json.loads(resp.data.decode("utf-8"))
            self.assertFalse(dados.get("ok"))

    def test_rotas_agenda_sucesso_com_token(self):
        headers = {"Authorization": f"Bearer {self.token_mestre}"}
        evs_mock = [
            {
                "uid": "ev-servico-1",
                "titulo": "Reuniao de Alinhamento",
                "inicio": datetime(2026, 11, 9, 10, 0, tzinfo=TZ),
                "fim": datetime(2026, 11, 9, 10, 45, tzinfo=TZ),
                "dia_inteiro": False,
                "duracao_minutos": 45,
                "eh_reuniao": True,
                "link_video": "https://meet.google.com/servico-test",
            }
        ]

        with mock.patch("nextor.agenda.eventos_dia", return_value=evs_mock):
            resp = self.app.get("/gtd/agenda/dia", headers=headers)
            self.assertEqual(resp.status_code, 200)
            dados = json.loads(resp.data.decode("utf-8"))
            self.assertTrue(dados["ok"])
            self.assertEqual(len(dados["eventos"]), 1)
            self.assertEqual(dados["eventos"][0]["titulo"], "Reuniao de Alinhamento")


if __name__ == "__main__":
    unittest.main()
