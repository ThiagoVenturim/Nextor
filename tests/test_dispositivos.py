"""Testes unitarios offline do gerenciamento de dispositivos (issue #11).

Sem rede, sem hardware real, sem audio, sem chamada externa.
Cobre:
1) Cadastro de aparelhos (celular, tablet, notebook, pc, tv) com token sha256/prefixo no json e pareamento;
2) Revogacao e ativacao estritas por id;
3) Presenca e identificacao do dispositivo ativo;
4) Permissoes (TV so visualiza, PC executa deck);
5) Hand-off ('mostra na tv', 'continua no celular') e fila de mensagens;
6) Criterio de conclusao da issue #11: cadastrar dois aparelhos, enviar resposta para um e revogar o outro.
"""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from nextor import config, dispositivos, roteador, servico
from nextor.companheiro import companheiro


class BaseDispositivosTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.caminho_tmp = Path(self.tmp_dir.name)
        self.patch_arq = mock.patch.object(dispositivos, "ARQUIVO", self.caminho_tmp / "dispositivos.json")
        self.patch_token = mock.patch.object(config, "TOKEN", "token-mestre-teste")
        self.patch_porta = mock.patch.object(config, "PORTA", 5005)
        self.patch_arq.start()
        self.patch_token.start()
        self.patch_porta.start()
        dispositivos.resetar_estado_testes()
        self.client = servico.app.test_client()
        self.h_mestre = {"X-Nextor-Token": "token-mestre-teste"}

    def tearDown(self):
        dispositivos.resetar_estado_testes()
        self.patch_arq.stop()
        self.patch_token.stop()
        self.patch_porta.stop()
        self.tmp_dir.cleanup()


class TestCadastroDispositivos(BaseDispositivosTestCase):
    def test_cadastrar_todos_os_cinco_tipos_permitidos(self):
        tipos = ("celular", "tablet", "notebook", "pc", "tv")
        for tipo in tipos:
            id_disp = f"disp-{tipo}"
            item = dispositivos.cadastrar(id_disp, f"Meu {tipo}", tipo=tipo)
            self.assertEqual(item["id"], id_disp)
            self.assertEqual(item["tipo"], tipo)
            self.assertTrue(item["token"].startswith("nxt_dev_"))
            self.assertTrue(item["ativo"])

    def test_rejeita_tipo_invalido_ou_id_vazio(self):
        with self.assertRaises(ValueError):
            dispositivos.cadastrar("disp-invalido", "Relogio", tipo="smartwatch")
        with self.assertRaises(ValueError):
            dispositivos.cadastrar("   ", "Nome", tipo="celular")

    def test_rejeita_id_duplicado(self):
        dispositivos.cadastrar("tv-sala", "TV Sala", tipo="tv")
        with self.assertRaises(ValueError):
            dispositivos.cadastrar("tv-sala", "TV Sala 2", tipo="tv")

    def test_token_puro_nao_e_gravado_no_json(self):
        token_custom = "nxt_dev_segredo_exclusivo_998877"
        item = dispositivos.cadastrar("celular-thiago", "Celular", tipo="celular", token=token_custom)
        self.assertEqual(item["token"], token_custom)

        conteudo_disco = dispositivos.ARQUIVO.read_text(encoding="utf-8")
        self.assertNotIn(token_custom, conteudo_disco)
        self.assertIn(dispositivos._hash_token(token_custom), conteudo_disco)
        self.assertIn("nxt_dev_se...", conteudo_disco)

    def test_geracao_url_pareamento(self):
        item = dispositivos.cadastrar("tv-quarto", "TV Quarto", tipo="tv")
        url = dispositivos.gerar_url_pareamento(item["id"], token_puro=item["token"], host="192.168.1.50", porta=5005)
        self.assertIn("http://192.168.1.50:5005/dispositivo/conectar?", url)
        self.assertIn("id=tv-quarto", url)
        self.assertIn(f"token={item['token']}", url)

    def test_endpoint_admin_cadastrar_e_listar(self):
        # Sem token mestre -> 401
        self.assertEqual(self.client.post("/v1/dispositivos", json={"id": "tv", "tipo": "tv"}).status_code, 401)

        # Cadastro via token mestre
        resp = self.client.post(
            "/v1/dispositivos",
            json={"id": "notebook-dell", "nome": "Dell XPS", "tipo": "notebook"},
            headers=self.h_mestre,
        )
        self.assertEqual(resp.status_code, 201)
        dados = resp.get_json()
        self.assertTrue(dados["ok"])
        self.assertEqual(dados["dispositivo"]["id"], "notebook-dell")
        self.assertIn("/dispositivo/conectar?", dados["url_pareamento"])

        # Listagem padrao mascara token_hash e nao possui token puro
        list_resp = self.client.get("/v1/dispositivos", headers=self.h_mestre)
        self.assertEqual(list_resp.status_code, 200)
        itens = list_resp.get_json()["dispositivos"]
        self.assertEqual(len(itens), 1)
        self.assertNotIn("token", itens[0])
        self.assertNotIn("token_hash", itens[0])
        self.assertIn("prefixo", itens[0])


class TestRevogacaoEAtivacao(BaseDispositivosTestCase):
    def test_revogacao_e_ativacao_estritas_por_id(self):
        item = dispositivos.cadastrar("tablet-sala", "Tablet Sala", tipo="tablet", token="token-tablet-123")

        # Tentar revogar passando token puro falha
        self.assertFalse(dispositivos.revogar("token-tablet-123"))
        self.assertTrue(dispositivos.buscar_por_id("tablet-sala")["ativo"])

        # Revogar por id funciona
        self.assertTrue(dispositivos.revogar("tablet-sala"))
        disp = dispositivos.buscar_por_id("tablet-sala")
        self.assertFalse(disp["ativo"])
        self.assertIn("revogado_em", disp)

        # Buscar por token de aparelho revogado ainda retorna o item com ativo=False
        encontrado = dispositivos.buscar_por_token("token-tablet-123")
        self.assertIsNotNone(encontrado)
        self.assertFalse(encontrado["ativo"])

        # Tentar reativar passando token puro falha
        self.assertFalse(dispositivos.ativar("token-tablet-123"))
        self.assertFalse(dispositivos.buscar_por_id("tablet-sala")["ativo"])

        # Reativar por id funciona
        self.assertTrue(dispositivos.ativar("tablet-sala"))
        self.assertTrue(dispositivos.buscar_por_id("tablet-sala")["ativo"])
        self.assertIn("reativado_em", dispositivos.buscar_por_id("tablet-sala"))

    def test_remover_estrito_por_id(self):
        dispositivos.cadastrar("pc-escritorio", "PC", tipo="pc")
        self.assertFalse(dispositivos.remover("token-falso"))
        self.assertTrue(dispositivos.remover("pc-escritorio"))
        self.assertIsNone(dispositivos.buscar_por_id("pc-escritorio"))

    def test_endpoints_admin_revogar_e_ativar(self):
        dispositivos.cadastrar("tv-sala", "TV Sala", tipo="tv")

        # Revogar
        r_rev = self.client.post("/v1/dispositivos/tv-sala/revogar", headers=self.h_mestre)
        self.assertEqual(r_rev.status_code, 200)
        self.assertTrue(r_rev.get_json()["revogado"])
        self.assertFalse(dispositivos.buscar_por_id("tv-sala")["ativo"])

        # Ativar
        r_ativ = self.client.post("/v1/dispositivos/tv-sala/ativar", headers=self.h_mestre)
        self.assertEqual(r_ativ.status_code, 200)
        self.assertTrue(r_ativ.get_json()["ativo"])
        self.assertTrue(dispositivos.buscar_por_id("tv-sala")["ativo"])


class TestPresencaEDispositivoAtivo(BaseDispositivosTestCase):
    def test_registrar_presenca_unitario(self):
        dispositivos.cadastrar("celular-1", "Celular 1", tipo="celular")
        disp = dispositivos.registrar_presenca("celular-1", ip="192.168.1.100", user_agent="Mozilla/5.0")
        self.assertIsNotNone(disp)
        self.assertTrue(disp["presenca"]["online"])
        self.assertEqual(disp["presenca"]["ip"], "192.168.1.100")
        self.assertEqual(disp["presenca"]["user_agent"], "Mozilla/5.0")
        self.assertIsNotNone(disp["ultimo_visto"])

    def test_dispositivo_ativo_seleciona_o_mais_recente(self):
        dispositivos.cadastrar("tv-1", "TV 1", tipo="tv")
        dispositivos.cadastrar("pc-1", "PC 1", tipo="pc")

        # Sem presenca de nenhum, retorna o primeiro ativo
        primeiro = dispositivos.dispositivo_ativo()
        self.assertEqual(primeiro["id"], "tv-1")

        # Registra presenca no PC
        dispositivos.registrar_presenca("pc-1")
        ativo = dispositivos.dispositivo_ativo()
        self.assertEqual(ativo["id"], "pc-1")

        # Definicao explicita de ativo tem precedencia
        dispositivos.definir_ativo("tv-1")
        self.assertEqual(dispositivos.dispositivo_ativo()["id"], "tv-1")

    def test_endpoint_presenca_com_token_do_proprio_dispositivo(self):
        item = dispositivos.cadastrar("celular-2", "Celular 2", tipo="celular")
        resp = self.client.post(
            "/v1/dispositivos/celular-2/presenca",
            headers={"Authorization": f"Bearer {item['token']}"},
        )
        self.assertEqual(resp.status_code, 200)
        dados = resp.get_json()
        self.assertTrue(dados["ok"])
        self.assertTrue(dados["dispositivo"]["presenca"]["online"])

    def test_endpoint_dispositivo_ativo(self):
        dispositivos.cadastrar("notebook-1", "Notebook", tipo="notebook")
        dispositivos.definir_ativo("notebook-1")
        resp = self.client.get("/v1/dispositivos/ativo", headers=self.h_mestre)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["ativo"]["id"], "notebook-1")


class TestPermissoes(BaseDispositivosTestCase):
    def test_permissoes_padrao_por_tipo(self):
        tv = dispositivos.cadastrar("tv-p", "TV", tipo="tv")
        pc = dispositivos.cadastrar("pc-p", "PC", tipo="pc")
        celular = dispositivos.cadastrar("cel-p", "Celular", tipo="celular")

        self.assertEqual(tv["permissoes"], ["visualizar"])
        self.assertEqual(sorted(pc["permissoes"]), ["executar", "interagir", "visualizar"])
        self.assertEqual(sorted(celular["permissoes"]), ["interagir", "visualizar"])

    def test_tv_so_visualiza_e_pc_executa(self):
        dispositivos.cadastrar("tv-teste", "TV", tipo="tv")
        dispositivos.cadastrar("pc-teste", "PC", tipo="pc")

        self.assertTrue(dispositivos.tem_permissao("tv-teste", "visualizar"))
        self.assertFalse(dispositivos.tem_permissao("tv-teste", "executar"))
        self.assertFalse(dispositivos.tem_permissao("tv-teste", "interagir"))

        self.assertTrue(dispositivos.tem_permissao("pc-teste", "executar"))
        self.assertTrue(dispositivos.tem_permissao("pc-teste", "visualizar"))
        self.assertTrue(dispositivos.tem_permissao("pc-teste", "interagir"))

    def test_roteador_bloqueia_deck_para_dispositivo_sem_permissao_executar(self):
        dispositivos.cadastrar("tv-sala", "TV Sala", tipo="tv")
        dispositivos.cadastrar("pc-quarto", "PC Quarto", tipo="pc")

        with mock.patch("nextor.roteador._registra"):
            # Comando disparado pela TV (sem permissao 'executar')
            r_tv = roteador.rotear("no pc, bloquear", id_dispositivo="tv-sala")
            self.assertEqual(r_tv["intencao"], "deck")
            self.assertIn("nao tem permissao", r_tv["resposta"])

            # Comando disparado pelo PC (com permissao 'executar')
            with mock.patch("nextor.roteador._fazer_deck", return_value="Computador bloqueado."):
                r_pc = roteador.rotear("no pc, bloquear", id_dispositivo="pc-quarto")
                self.assertEqual(r_pc["intencao"], "deck")
                self.assertEqual(r_pc["resposta"], "Computador bloqueado.")


class TestHandOffEFilaMensagens(BaseDispositivosTestCase):
    def test_handoff_roteador_mostra_na_tv_e_continua_no_celular(self):
        dispositivos.cadastrar("tv-sala", "TV da Sala", tipo="tv")
        dispositivos.cadastrar("celular-1", "Meu Celular", tipo="celular")
        companheiro.atualizar(ultima_resposta="O sol nasce a leste.")

        with mock.patch("nextor.roteador._registra"):
            # Hand-off sem resto de comando: envia ultima resposta do companheiro
            r_tv = roteador.rotear("mostra na tv")
            self.assertEqual(r_tv["intencao"], "dispositivo")
            self.assertIn("Mostrando na TV da Sala", r_tv["resposta"])

            msgs_tv = dispositivos.obter_mensagens_pendentes("tv-sala", limpar=True)
            self.assertEqual(len(msgs_tv), 1)
            self.assertEqual(msgs_tv[0]["texto"], "O sol nasce a leste.")

            # Hand-off com resto: roteia e envia resposta
            with mock.patch("nextor.roteador.rotear", side_effect=lambda f: {"resposta": "Previsao de sol", "intencao": "tempo"} if f == "como esta o tempo" else {"resposta": "Mostrando no Meu Celular.", "intencao": "dispositivo"}):
                r_cel = roteador._fazer_dispositivo("celular", resto="como esta o tempo")
                self.assertIn("Mostrando no Meu Celular", r_cel)

            msgs_cel = dispositivos.obter_mensagens_pendentes("celular-1", limpar=True)
            self.assertEqual(len(msgs_cel), 1)
            self.assertEqual(msgs_cel[0]["texto"], "Previsao de sol")

    def test_endpoint_handoff(self):
        dispositivos.cadastrar("tv-sala", "TV Sala", tipo="tv")
        resp = self.client.post(
            "/v1/dispositivos/hand-off",
            json={"alvo": "tv-sala", "texto": "Grafico de despesas", "titulo": "Financas"},
            headers=self.h_mestre,
        )
        self.assertEqual(resp.status_code, 200)
        dados = resp.get_json()
        self.assertTrue(dados["ok"])
        self.assertEqual(dados["dispositivo_alvo"], "tv-sala")

        # Consultar mensagens da TV via endpoint
        msgs_resp = self.client.get("/v1/dispositivos/tv-sala/mensagens", headers=self.h_mestre)
        self.assertEqual(msgs_resp.status_code, 200)
        msgs = msgs_resp.get_json()["mensagens"]
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["texto"], "Grafico de despesas")
        self.assertEqual(msgs[0]["titulo"], "Financas")

    def test_pagina_conectar_dispositivo_valido_e_invalido(self):
        item = dispositivos.cadastrar("tv-display", "TV Display", tipo="tv")

        # Acesso sem token ou token invalido -> 401
        r_err = self.client.get(f"/dispositivo/conectar?id={item['id']}&token=token-errado")
        self.assertEqual(r_err.status_code, 401)

        # Acesso valido -> 200 HTML
        r_ok = self.client.get(f"/dispositivo/conectar?id={item['id']}&token={item['token']}")
        self.assertEqual(r_ok.status_code, 200)
        self.assertIn("text/html", r_ok.headers.get("Content-Type", ""))
        self.assertIn("TV Display", r_ok.get_data(as_text=True))


class TestCriterioDeConclusaoIssue11(BaseDispositivosTestCase):
    """Criterio de conclusao da issue #11:

    Cadastrar dois aparelhos (ex: TV e celular), mandar uma resposta para um deles
    e revogar o outro, garantindo isolamento de estado e bloqueio do revogado.
    """
    def test_cadastrar_dois_aparelhos_enviar_resposta_e_revogar_outro(self):
        # 1. Cadastrar dois aparelhos
        tv = dispositivos.cadastrar("tv-sala", "TV da Sala", tipo="tv")
        celular = dispositivos.cadastrar("celular-thiago", "Celular de Thiago", tipo="celular")

        self.assertEqual(len(dispositivos.listar()), 2)
        self.assertTrue(tv["ativo"])
        self.assertTrue(celular["ativo"])

        # 2. Mandar uma resposta para um deles (TV da Sala)
        msg_enviada = dispositivos.enviar_resposta_dispositivo(
            id_dispositivo="tv-sala",
            texto="Lembrete importante exibido na tela.",
            titulo="Aviso",
        )
        self.assertEqual(msg_enviada["dispositivo_alvo"], "tv-sala")
        self.assertEqual(msg_enviada["texto"], "Lembrete importante exibido na tela.")

        # Verificar presenca da mensagem na fila da TV e nenhuma no celular
        msgs_tv = dispositivos.obter_mensagens_pendentes("tv-sala", limpar=False)
        msgs_cel = dispositivos.obter_mensagens_pendentes("celular-thiago", limpar=False)
        self.assertEqual(len(msgs_tv), 1)
        self.assertEqual(msgs_tv[0]["texto"], "Lembrete importante exibido na tela.")
        self.assertEqual(len(msgs_cel), 0)

        # 3. Revogar o outro aparelho (Celular)
        revogado = dispositivos.revogar("celular-thiago")
        self.assertTrue(revogado)

        disp_cel = dispositivos.buscar_por_id("celular-thiago")
        self.assertFalse(disp_cel["ativo"])
        self.assertIn("revogado_em", disp_cel)

        # 4. Validar que enviar resposta para o aparelho revogado agora falha
        with self.assertRaises(ValueError) as ctx:
            dispositivos.enviar_resposta_dispositivo("celular-thiago", "Tentativa de envio")
        self.assertIn("desativado ou revogado", str(ctx.exception))

        # 5. Validar que endpoint de hand-off para o revogado retorna 403
        resp_handoff = self.client.post(
            "/v1/dispositivos/hand-off",
            json={"alvo": "celular-thiago", "texto": "Ola"},
            headers=self.h_mestre,
        )
        self.assertEqual(resp_handoff.status_code, 403)
        self.assertIn("revogado", resp_handoff.get_json()["erro"])

        # 6. Validar que o primeiro aparelho (TV) continua ativo e operando normalmente
        self.assertTrue(dispositivos.buscar_por_id("tv-sala")["ativo"])
        msgs_tv_restantes = dispositivos.obter_mensagens_pendentes("tv-sala", limpar=True)
        self.assertEqual(len(msgs_tv_restantes), 1)
        self.assertEqual(len(dispositivos.obter_mensagens_pendentes("tv-sala")), 0)


if __name__ == "__main__":
    unittest.main()
