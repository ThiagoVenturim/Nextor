"""Testes unitarios offline do modulo de gravacao de reunioes e tela (issue #14).

Sem rede, sem hardware real (sem microfone nem tela real), sem audio.
Isolamento total com tempfile.TemporaryDirectory e mocks offline.
Cobre:
1) GravadorReuniao (aviso obrigatorio de consentimento em AVISO_CONSENTIMENTO_REUNIAO,
   bloqueio de gravacao simultanea, parada com transcritor mock gerando decisoes e
   itens de acao estruturados, salvamento da ata_reuniao.md e integracao com anotacoes.md);
2) GravadorTela (aviso obrigatorio de consentimento em AVISO_CONSENTIMENTO_TELA,
   inicio com mock de processo ffmpeg, insercao de marcadores de voz com tempo relativo
   formatado MM:SS, parada com encerramento do ffmpeg e geracao de marcadores.json e registro_tarefa.md);
3) Gatilhos no roteador ('gravar reuniao sobre X', 'gravar tela da tarefa Y', 'marca: ponto', 'parar gravacao');
4) Endpoints HTTP em servico.py (/v1/reuniao/iniciar, /v1/reuniao/parar, /v1/tela/iniciar,
   /v1/tela/marcar, /v1/tela/parar; bloqueio sem token mestre 401, sucesso 200 e erros 400).
"""
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

os.environ["NEXTOR_VOZ_SAIDA"] = "nenhuma"

from nextor import config, reuniao_tela, roteador, servico


class BaseReuniaoTelaTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.caminho_base = Path(self.tmp_dir.name).resolve()
        self.pasta_reunioes = self.caminho_base / "reunioes"
        self.pasta_reunioes.mkdir(parents=True, exist_ok=True)
        self.pasta_telas = self.caminho_base / "gravacoes_tela"
        self.pasta_telas.mkdir(parents=True, exist_ok=True)
        self.arquivo_anotacoes = self.caminho_base / "anotacoes.md"

        self.patch_reunioes_dir = mock.patch.object(
            config,
            "REUNIOES_DIR",
            self.pasta_reunioes,
        )
        self.patch_telas_dir = mock.patch.object(
            config,
            "GRAVACOES_TELA_DIR",
            self.pasta_telas,
        )
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

        # Garante que sounddevice nao abra fluxo de audio real
        self.patch_sd = mock.patch.object(reuniao_tela, "sd", None)

        # Mock global de processo ffmpeg
        self.fake_proc = mock.MagicMock()
        self.fake_proc.stdin = mock.MagicMock()
        self.fake_proc.terminate = mock.MagicMock()
        self.patch_popen = mock.patch(
            "subprocess.Popen",
            return_value=self.fake_proc,
        )

        self.patch_reunioes_dir.start()
        self.patch_telas_dir.start()
        self.patch_anotacoes.start()
        self.patch_token.start()
        self.patch_sd.start()
        self.patch_popen.start()

        # Reseta estado de gravadores globais
        self._limpar_gravadores()

        self.client = servico.app.test_client()
        self.h_mestre = {"X-Nextor-Token": "token-mestre-super-seguro-1234567890"}

    def tearDown(self):
        self._limpar_gravadores()
        self.patch_popen.stop()
        self.patch_sd.stop()
        self.patch_token.stop()
        self.patch_anotacoes.stop()
        self.patch_telas_dir.stop()
        self.patch_reunioes_dir.stop()
        self.tmp_dir.cleanup()

    def _limpar_gravadores(self):
        with reuniao_tela.gravador_reuniao._lock:
            reuniao_tela.gravador_reuniao._gravando = False
            reuniao_tela.gravador_reuniao._tema = ""
            reuniao_tela.gravador_reuniao._participantes = ""
            reuniao_tela.gravador_reuniao._frames = []
        with reuniao_tela.gravador_tela._lock:
            reuniao_tela.gravador_tela._gravando = False
            reuniao_tela.gravador_tela._tarefa = ""
            reuniao_tela.gravador_tela._marcadores = []
            reuniao_tela.gravador_tela._processo = None


class TestFuncoesAuxiliares(BaseReuniaoTelaTestCase):
    def test_formatar_segundos(self):
        self.assertEqual(reuniao_tela.formatar_segundos(0), "00:00")
        self.assertEqual(reuniao_tela.formatar_segundos(45), "00:45")
        self.assertEqual(reuniao_tela.formatar_segundos(65), "01:05")
        self.assertEqual(reuniao_tela.formatar_segundos(3665), "01:01:05")

    def test_normalizar_slug(self):
        self.assertEqual(reuniao_tela.normalizar_slug("Reuniao de Planejamento 2026!"), "reuniao_de_planejamento_2026")
        self.assertEqual(reuniao_tela.normalizar_slug("Ajustar Bug #14 & Testes"), "ajustar_bug_14_testes")
        self.assertEqual(reuniao_tela.normalizar_slug(""), "sem_titulo")


class TestGravadorReuniao(BaseReuniaoTelaTestCase):
    def test_aviso_obrigatorio_de_consentimento_no_inicio(self):
        gravador = reuniao_tela.GravadorReuniao()
        res = gravador.iniciar(
            tema="Planejamento de Sprint",
            participantes="Thiago, Ana",
            diretorio_saida=self.pasta_reunioes,
            backend_gravador=lambda: None,
        )
        self.assertTrue(res["ok"])
        self.assertTrue(res["consentimento_anunciado"])
        self.assertEqual(res["aviso"], reuniao_tela.AVISO_CONSENTIMENTO_REUNIAO)
        self.assertEqual(res["tema"], "Planejamento de Sprint")
        self.assertEqual(res["participantes"], "Thiago, Ana")
        self.assertTrue(gravador.gravando)
        self.assertEqual(gravador.tema, "Planejamento de Sprint")

    def test_bloqueio_de_gravacao_simultanea(self):
        gravador = reuniao_tela.GravadorReuniao()
        r1 = gravador.iniciar(tema="Primeira Reuniao", backend_gravador=lambda: None, diretorio_saida=self.pasta_reunioes)
        self.assertTrue(r1["ok"])

        # Segunda tentativa deve ser bloqueada
        r2 = gravador.iniciar(tema="Segunda Reuniao", backend_gravador=lambda: None, diretorio_saida=self.pasta_reunioes)
        self.assertFalse(r2["ok"])
        self.assertIn("Ja existe uma gravacao de reuniao em andamento", r2["erro"])

    def test_parada_sem_gravacao_ativa_retorna_erro(self):
        gravador = reuniao_tela.GravadorReuniao()
        res = gravador.parar()
        self.assertFalse(res["ok"])
        self.assertEqual(res["erro"], "nenhuma_reuniao_em_andamento")

    def test_parada_com_transcritor_mock_gera_decisoes_acoes_ata_e_anotacoes(self):
        gravador = reuniao_tela.GravadorReuniao()
        gravador.iniciar(
            tema="Migracao de Banco de Dados",
            participantes="Thiago, Viga",
            diretorio_saida=self.pasta_reunioes,
            backend_gravador=lambda: None,
        )

        def mock_transcritor(caminho_wav):
            return [
                {
                    "inicio": "00:05",
                    "fim": "00:20",
                    "texto": "Bom dia a todos. Vamos iniciar a discussao sobre a migracao da arquitetura.",
                },
                {
                    "inicio": "00:25",
                    "fim": "00:40",
                    "texto": "Ficou acordado: migrar para banco Postgres com suporte JSONB.",
                },
                {
                    "inicio": "00:45",
                    "fim": "01:00",
                    "texto": "Viga vai fazer: implementar testes de carga na sexta-feira.",
                },
            ]

        res = gravador.parar(transcritor=mock_transcritor, salvar_anotacoes=True)
        self.assertTrue(res["ok"])
        self.assertFalse(gravador.gravando)
        self.assertEqual(res["tema"], "Migracao de Banco de Dados")

        # Valida decisoes extraidas
        self.assertEqual(len(res["decisoes"]), 1)
        self.assertIn("migrar para banco Postgres com suporte JSONB", res["decisoes"][0])

        # Valida itens de acao extraidos
        self.assertEqual(len(res["itens_acao"]), 1)
        self.assertIn("implementar testes de carga", res["itens_acao"][0]["descricao"])
        self.assertEqual(res["itens_acao"][0]["responsavel"], "Viga")
        self.assertEqual(res["itens_acao"][0]["momento"], "00:45")

        # Valida geracao de ata_reuniao.md
        caminho_ata = Path(res["arquivo_md"])
        self.assertTrue(caminho_ata.exists())
        conteudo_ata = caminho_ata.read_text(encoding="utf-8")
        self.assertIn("# Reuniao: Migracao de Banco de Dados", conteudo_ata)
        self.assertIn(reuniao_tela.AVISO_CONSENTIMENTO_REUNIAO, conteudo_ata)
        self.assertIn("## Decisoes Tomadas", conteudo_ata)
        self.assertIn("migrar para banco Postgres", conteudo_ata)
        self.assertIn("## Itens de Acao", conteudo_ata)
        self.assertIn("implementar testes de carga", conteudo_ata)

        # Valida integracao com anotacoes.md
        self.assertTrue(self.arquivo_anotacoes.exists())
        conteudo_anotacoes = self.arquivo_anotacoes.read_text(encoding="utf-8")
        self.assertIn("[Reuniao: Migracao de Banco de Dados]", conteudo_anotacoes)
        self.assertIn("implementar testes de carga na sexta-feira (Viga)", conteudo_anotacoes)

    def test_parada_com_salvar_anotacoes_falso_nao_altera_anotacoes(self):
        gravador = reuniao_tela.GravadorReuniao()
        gravador.iniciar(
            tema="Reuniao Privada",
            diretorio_saida=self.pasta_reunioes,
            backend_gravador=lambda: None,
        )

        def mock_transcritor(caminho):
            return [{"inicio": "00:01", "fim": "00:10", "texto": "Ficou de revisar documentacao."}]

        res = gravador.parar(transcritor=mock_transcritor, salvar_anotacoes=False)
        self.assertTrue(res["ok"])
        self.assertFalse(self.arquivo_anotacoes.exists())


class TestGravadorTela(BaseReuniaoTelaTestCase):
    def test_aviso_obrigatorio_de_consentimento_tela_e_backend_mock(self):
        gravador = reuniao_tela.GravadorTela()
        comando_capturado = []

        def mock_backend(cmd):
            comando_capturado.extend(cmd)
            return self.fake_proc

        res = gravador.iniciar(
            tarefa="Depurar API Flask",
            backend_processo=mock_backend,
            diretorio_saida=self.pasta_telas,
        )
        self.assertTrue(res["ok"])
        self.assertTrue(res["consentimento_anunciado"])
        self.assertEqual(res["aviso"], reuniao_tela.AVISO_CONSENTIMENTO_TELA)
        self.assertEqual(res["tarefa"], "Depurar API Flask")
        self.assertTrue(gravador.gravando)
        self.assertIn("ffmpeg", comando_capturado)
        self.assertIn("desktop", comando_capturado)

    def test_bloqueio_de_gravacao_de_tela_simultanea(self):
        gravador = reuniao_tela.GravadorTela()
        r1 = gravador.iniciar(tarefa="Tarefa 1", backend_processo=lambda cmd: self.fake_proc, diretorio_saida=self.pasta_telas)
        self.assertTrue(r1["ok"])

        r2 = gravador.iniciar(tarefa="Tarefa 2", backend_processo=lambda cmd: self.fake_proc, diretorio_saida=self.pasta_telas)
        self.assertFalse(r2["ok"])
        self.assertIn("Ja existe uma gravacao de tela em andamento", r2["erro"])

    def test_adicionar_marcador_por_voz_e_tempo_relativo(self):
        gravador = reuniao_tela.GravadorTela()
        gravador.iniciar(tarefa="Refatoracao", backend_processo=lambda cmd: self.fake_proc, diretorio_saida=self.pasta_telas)

        # Adiciona marcador valido
        m1 = gravador.adicionar_marcador("Abrindo arquivo de configuracao")
        self.assertTrue(m1["ok"])
        self.assertEqual(m1["nota"], "Abrindo arquivo de configuracao")
        self.assertEqual(m1["total_marcadores"], 1)
        self.assertRegex(m1["tempo"], r"^\d{2}:\d{2}$")

        m2 = gravador.adicionar_marcador("Ocorreu erro 500 no endpoint")
        self.assertTrue(m2["ok"])
        self.assertEqual(m2["total_marcadores"], 2)

        # Marcador com nota vazia deve falhar
        m_vazio = gravador.adicionar_marcador("   ")
        self.assertFalse(m_vazio["ok"])
        self.assertEqual(m_vazio["erro"], "nota_vazia")

    def test_adicionar_marcador_sem_gravacao_ativa_retorna_erro(self):
        gravador = reuniao_tela.GravadorTela()
        res = gravador.adicionar_marcador("Ponto fora de hora")
        self.assertFalse(res["ok"])
        self.assertEqual(res["erro"], "nenhuma_gravacao_de_tela_em_andamento")

    def test_parada_encerra_ffmpeg_e_gera_json_e_markdown(self):
        gravador = reuniao_tela.GravadorTela()
        gravador.iniciar(tarefa="Testes de UI", backend_processo=lambda cmd: self.fake_proc, diretorio_saida=self.pasta_telas)
        gravador.adicionar_marcador("Inicio do teste de login")
        gravador.adicionar_marcador("Validacao de formulario concluida")

        res = gravador.parar()
        self.assertTrue(res["ok"])
        self.assertFalse(gravador.gravando)
        self.assertEqual(res["total_marcadores"], 2)

        # Valida chamada para finalizar o processo ffmpeg
        self.fake_proc.stdin.write.assert_called_with(b"q")
        self.fake_proc.terminate.assert_called_once()

        # Valida geracao de marcadores.json e registro_tarefa.md
        pasta_saida = gravador._pasta_saida
        self.assertIsNotNone(pasta_saida)
        arquivo_json = pasta_saida / "marcadores.json"
        arquivo_md = pasta_saida / "registro_tarefa.md"

        self.assertTrue(arquivo_json.exists())
        self.assertTrue(arquivo_md.exists())

        dados_json = json.loads(arquivo_json.read_text(encoding="utf-8"))
        self.assertEqual(len(dados_json), 2)
        self.assertEqual(dados_json[0]["nota"], "Inicio do teste de login")

        conteudo_md = arquivo_md.read_text(encoding="utf-8")
        self.assertIn("# Gravacao de Tarefa: Testes de UI", conteudo_md)
        self.assertIn("Inicio do teste de login", conteudo_md)
        self.assertIn("Validacao de formulario concluida", conteudo_md)

    def test_parada_sem_gravacao_de_tela_ativa_retorna_erro(self):
        gravador = reuniao_tela.GravadorTela()
        res = gravador.parar()
        self.assertFalse(res["ok"])
        self.assertEqual(res["erro"], "nenhuma_gravacao_de_tela_em_andamento")

    def test_parar_qualquer_gravacao(self):
        # Nenhuma ativa
        r0 = reuniao_tela.parar_qualquer_gravacao()
        self.assertFalse(r0["ok"])
        self.assertEqual(r0["erro"], "nenhuma_gravacao_ativa")

        # Com reuniao ativa
        reuniao_tela.gravador_reuniao.iniciar(
            tema="Reuniao X",
            backend_gravador=lambda: None,
            diretorio_saida=self.pasta_reunioes,
        )
        r_reuniao = reuniao_tela.parar_qualquer_gravacao()
        self.assertTrue(r_reuniao["ok"])
        self.assertEqual(r_reuniao["tipo"], "reuniao")

        # Com tela ativa
        reuniao_tela.gravador_tela.iniciar(
            tarefa="Tarefa Y",
            backend_processo=lambda cmd: self.fake_proc,
            diretorio_saida=self.pasta_telas,
        )
        r_tela = reuniao_tela.parar_qualquer_gravacao()
        self.assertTrue(r_tela["ok"])
        self.assertEqual(r_tela["tipo"], "tela")


class TestGatilhosRoteador(BaseReuniaoTelaTestCase):
    def test_gatilho_gravar_reuniao(self):
        res = roteador.rotear("gravar reuniao sobre Alinhamento de Produto")
        self.assertEqual(res["intencao"], "reuniao_iniciar")
        self.assertIn("Aviso de gravacao", res["resposta"])
        self.assertIn("Alinhamento de Produto", res["resposta"])
        self.assertTrue(reuniao_tela.gravador_reuniao.gravando)

    def test_gatilho_gravar_tela_tarefa(self):
        res = roteador.rotear("gravar tela da tarefa Ajuste de Rota")
        self.assertEqual(res["intencao"], "tela_iniciar")
        self.assertIn("Aviso de gravacao", res["resposta"])
        self.assertIn("Ajuste de Rota", res["resposta"])
        self.assertTrue(reuniao_tela.gravador_tela.gravando)

    def test_gatilho_marcador_de_voz(self):
        # Inicia tela primeiro
        reuniao_tela.gravador_tela.iniciar(
            tarefa="Ajuste",
            backend_processo=lambda cmd: self.fake_proc,
            diretorio_saida=self.pasta_telas,
        )

        res = roteador.rotear("marca: erro encontrado no log")
        self.assertEqual(res["intencao"], "tela_marcar")
        self.assertIn("Marcado", res["resposta"])
        self.assertIn("erro encontrado no log", res["resposta"])
        self.assertEqual(len(reuniao_tela.gravador_tela.marcadores), 1)

    def test_gatilho_parar_gravacao_reuniao(self):
        reuniao_tela.gravador_reuniao.iniciar(
            tema="Arquitetura",
            backend_gravador=lambda: None,
            diretorio_saida=self.pasta_reunioes,
        )
        res = roteador.rotear("parar gravacao")
        self.assertEqual(res["intencao"], "estudos_parar_gravacao")
        self.assertIn("Reuniao encerrada", res["resposta"])
        self.assertFalse(reuniao_tela.gravador_reuniao.gravando)

    def test_gatilho_parar_gravacao_tela(self):
        reuniao_tela.gravador_tela.iniciar(
            tarefa="Debug",
            backend_processo=lambda cmd: self.fake_proc,
            diretorio_saida=self.pasta_telas,
        )
        reuniao_tela.gravador_tela.adicionar_marcador("Ponto 1")
        res = roteador.rotear("para a gravacao")
        self.assertEqual(res["intencao"], "estudos_parar_gravacao")
        self.assertIn("Gravacao de tela encerrada", res["resposta"])
        self.assertIn("1 marcadores salvos", res["resposta"])
        self.assertFalse(reuniao_tela.gravador_tela.gravando)


class TestEndpointsHTTP(BaseReuniaoTelaTestCase):
    def test_bloqueio_sem_token_mestre_retorna_401(self):
        self.assertEqual(self.client.post("/v1/reuniao/iniciar", json={"tema": "X"}).status_code, 401)
        self.assertEqual(self.client.post("/v1/reuniao/parar", json={}).status_code, 401)
        self.assertEqual(self.client.post("/v1/tela/iniciar", json={"tarefa": "Y"}).status_code, 401)
        self.assertEqual(self.client.post("/v1/tela/marcar", json={"nota": "Z"}).status_code, 401)
        self.assertEqual(self.client.post("/v1/tela/parar", json={}).status_code, 401)

    def test_ciclo_completo_reuniao_via_http(self):
        # Iniciar reuniao
        r_ini = self.client.post(
            "/v1/reuniao/iniciar",
            json={"tema": "Review Semanal", "participantes": "Time Dev"},
            headers=self.h_mestre,
        )
        self.assertEqual(r_ini.status_code, 200)
        dados_ini = r_ini.get_json()
        self.assertTrue(dados_ini["ok"])
        self.assertEqual(dados_ini["tema"], "Review Semanal")
        self.assertIn("Aviso de gravacao", dados_ini["aviso"])

        # Iniciar novamente deve retornar 400
        r_dup = self.client.post("/v1/reuniao/iniciar", json={"tema": "Outra"}, headers=self.h_mestre)
        self.assertEqual(r_dup.status_code, 400)
        self.assertFalse(r_dup.get_json()["ok"])

        # Parar reuniao
        r_fim = self.client.post(
            "/v1/reuniao/parar",
            json={"salvar_anotacoes": True},
            headers=self.h_mestre,
        )
        self.assertEqual(r_fim.status_code, 200)
        dados_fim = r_fim.get_json()
        self.assertTrue(dados_fim["ok"])
        self.assertEqual(dados_fim["tema"], "Review Semanal")

        # Parar novamente deve retornar 400
        r_fim2 = self.client.post("/v1/reuniao/parar", json={}, headers=self.h_mestre)
        self.assertEqual(r_fim2.status_code, 400)

    def test_ciclo_completo_tela_via_http(self):
        # Iniciar gravacao de tela
        r_ini = self.client.post(
            "/v1/tela/iniciar",
            json={"tarefa": "Implementacao #14"},
            headers=self.h_mestre,
        )
        self.assertEqual(r_ini.status_code, 200)
        dados_ini = r_ini.get_json()
        self.assertTrue(dados_ini["ok"])
        self.assertEqual(dados_ini["tarefa"], "Implementacao #14")
        self.assertIn("Aviso de gravacao", dados_ini["aviso"])

        # Iniciar repetido retorna 400
        r_dup = self.client.post("/v1/tela/iniciar", json={"tarefa": "Outra"}, headers=self.h_mestre)
        self.assertEqual(r_dup.status_code, 400)

        # Adicionar marcador sem nota retorna 400
        r_sem_nota = self.client.post("/v1/tela/marcar", json={"nota": ""}, headers=self.h_mestre)
        self.assertEqual(r_sem_nota.status_code, 400)
        self.assertEqual(r_sem_nota.get_json()["erro"], "nota_obrigatoria")

        # Adicionar marcador valido
        r_marcar = self.client.post("/v1/tela/marcar", json={"nota": "Checkpoint de testes"}, headers=self.h_mestre)
        self.assertEqual(r_marcar.status_code, 200)
        self.assertTrue(r_marcar.get_json()["ok"])
        self.assertEqual(r_marcar.get_json()["nota"], "Checkpoint de testes")

        # Parar gravacao de tela
        r_fim = self.client.post("/v1/tela/parar", json={}, headers=self.h_mestre)
        self.assertEqual(r_fim.status_code, 200)
        dados_fim = r_fim.get_json()
        self.assertTrue(dados_fim["ok"])
        self.assertEqual(dados_fim["total_marcadores"], 1)

        # Parar repetido retorna 400
        r_fim2 = self.client.post("/v1/tela/parar", json={}, headers=self.h_mestre)
        self.assertEqual(r_fim2.status_code, 400)


if __name__ == "__main__":
    unittest.main()
