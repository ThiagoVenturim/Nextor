"""Testes unitarios offline do modulo organizador de pastas (issue #15).

Sem rede, sem hardware real, sem audio, sem chamada externa.
Isolamento total com tempfile.TemporaryDirectory.
Cobre:
1) validar_pasta_permitida (aceitacao, rejeicao fora da lista, path traversal, raiz/home);
2) resolver_destino_sem_colisao (manutencao de nomes novos, incremento _1, _2);
3) categorias de extensao (classificacao correta e Outros);
4) gerar_previa (tipo, data, disciplina, garantia de que nenhum arquivo e movido);
5) executar_organizacao (movimentacao para subpastas, colisao, registro em historico JSON);
6) desfazer_ultima_organizacao (restauracao, limpeza de subpastas vazias, flag desfeita);
7) gatilhos no roteador ('organiza minha pasta X', 'confirma organizacao', 'desfaz organizacao');
8) endpoints HTTP em servico.py (bloqueio 401, pasta nao permitida 403, sucesso 200).
"""
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

os.environ["NEXTOR_VOZ_SAIDA"] = "nenhuma"

from nextor import config, organizador, roteador, servico


class BaseOrganizadorTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.caminho_base = Path(self.tmp_dir.name).resolve()
        self.pasta_permitida = (self.caminho_base / "DownloadsPermitidos").resolve()
        self.pasta_permitida.mkdir(parents=True, exist_ok=True)
        self.pasta_historico = (self.caminho_base / "dados").resolve()
        self.arquivo_historico = self.pasta_historico / "historico_organizacoes.json"

        # Mock das pastas permitidas e do arquivo de historico
        self.patch_pastas = mock.patch.object(
            organizador,
            "obter_pastas_permitidas",
            return_value=[self.pasta_permitida],
        )
        self.patch_config_hist = mock.patch.object(
            config,
            "HISTORICO_ORGANIZACOES",
            self.arquivo_historico,
        )
        self.patch_token = mock.patch.object(
            config,
            "TOKEN",
            "token-mestre-super-seguro-1234567890",
        )
        self.patch_pastas.start()
        self.patch_config_hist.start()
        self.patch_token.start()

        # Limpa estado em memoria
        organizador._PREVIAS_PENDENTES.clear()
        organizador._ULTIMA_PREVIA = None

        self.client = servico.app.test_client()
        self.h_mestre = {"X-Nextor-Token": "token-mestre-super-seguro-1234567890"}

    def tearDown(self):
        self.patch_pastas.stop()
        self.patch_config_hist.stop()
        self.patch_token.stop()
        self.tmp_dir.cleanup()


class TestValidarPastaPermitida(BaseOrganizadorTestCase):
    def test_pasta_permitida_aceita(self):
        subpasta = self.pasta_permitida / "Projetos"
        subpasta.mkdir()
        self.assertEqual(organizador.validar_pasta_permitida(self.pasta_permitida), self.pasta_permitida)
        self.assertEqual(organizador.validar_pasta_permitida(subpasta), subpasta)

    def test_pasta_fora_da_lista_rejeitada(self):
        pasta_estranha = (self.caminho_base / "NaoAutorizada").resolve()
        pasta_estranha.mkdir()
        with self.assertRaises(organizador.PastaNaoPermitidaError):
            organizador.validar_pasta_permitida(pasta_estranha)

    def test_path_traversal_com_pontos_rejeitado(self):
        traversal = f"{self.pasta_permitida}/../../"
        with self.assertRaises(organizador.PastaNaoPermitidaError):
            organizador.validar_pasta_permitida(traversal)

    def test_raiz_e_home_rejeitados(self):
        home = Path.home().resolve()
        with self.assertRaises(organizador.PastaNaoPermitidaError):
            organizador.validar_pasta_permitida(home)

        raiz_disco = Path(self.pasta_permitida.anchor).resolve()
        with self.assertRaises(organizador.PastaNaoPermitidaError):
            organizador.validar_pasta_permitida(raiz_disco)

    def test_caminho_inexistente_ou_arquivo_rejeitados(self):
        inexistente = self.pasta_permitida / "fantasma"
        with self.assertRaises(organizador.PastaNaoPermitidaError):
            organizador.validar_pasta_permitida(inexistente)

        arquivo = self.pasta_permitida / "arquivo.txt"
        arquivo.write_text("conteudo", encoding="utf-8")
        with self.assertRaises(organizador.PastaNaoPermitidaError):
            organizador.validar_pasta_permitida(arquivo)

    def test_caminho_vazio_ou_nulo(self):
        with self.assertRaises(organizador.PastaNaoPermitidaError):
            organizador.validar_pasta_permitida("")
        with self.assertRaises(organizador.PastaNaoPermitidaError):
            organizador.validar_pasta_permitida(None)


class TestResolverDestinoSemColisao(BaseOrganizadorTestCase):
    def test_destino_novo_mantido(self):
        destino = self.pasta_permitida / "Documentos" / "novo.pdf"
        self.assertEqual(organizador.resolver_destino_sem_colisao(destino), destino)

    def test_destino_existente_vira_sufixo_1(self):
        pasta_dest = self.pasta_permitida / "Documentos"
        pasta_dest.mkdir(parents=True, exist_ok=True)
        existente = pasta_dest / "relatorio.pdf"
        existente.write_text("versao 0", encoding="utf-8")

        resolvido = organizador.resolver_destino_sem_colisao(existente)
        self.assertEqual(resolvido, pasta_dest / "relatorio_1.pdf")

    def test_destino_com_colisao_multipla_incrementa(self):
        pasta_dest = self.pasta_permitida / "Documentos"
        pasta_dest.mkdir(parents=True, exist_ok=True)
        (pasta_dest / "relatorio.pdf").write_text("v0", encoding="utf-8")
        (pasta_dest / "relatorio_1.pdf").write_text("v1", encoding="utf-8")
        (pasta_dest / "relatorio_2.pdf").write_text("v2", encoding="utf-8")

        resolvido = organizador.resolver_destino_sem_colisao(pasta_dest / "relatorio.pdf")
        self.assertEqual(resolvido, pasta_dest / "relatorio_3.pdf")


class TestCategoriasExtensao(unittest.TestCase):
    def test_classificacao_categorias(self):
        casos = [
            (".pdf", "Documentos"),
            (".docx", "Documentos"),
            (".txt", "Documentos"),
            (".png", "Imagens"),
            (".jpg", "Imagens"),
            (".jpeg", "Imagens"),
            (".xlsx", "Planilhas"),
            (".csv", "Planilhas"),
            (".pptx", "Apresentacoes"),
            (".mp3", "Audio"),
            (".wav", "Audio"),
            (".mp4", "Video"),
            (".mkv", "Video"),
            (".zip", "Compactados"),
            (".rar", "Compactados"),
            (".exe", "Instaladores"),
            (".msi", "Instaladores"),
            (".py", "Codigo"),
            (".json", "Codigo"),
            (".extensao_estranha_xyz", "Outros"),
            ("", "Outros"),
        ]
        for ext, cat_esperada in casos:
            with self.subTest(extensao=ext):
                self.assertEqual(organizador.obter_categoria_por_extensao(ext), cat_esperada)


class TestGerarPrevia(BaseOrganizadorTestCase):
    def test_previa_por_tipo_e_garantia_de_nenhum_arquivo_movido(self):
        arq_pdf = self.pasta_permitida / "contrato.pdf"
        arq_png = self.pasta_permitida / "foto.png"
        arq_py = self.pasta_permitida / "script.py"
        arq_pdf.write_text("pdf", encoding="utf-8")
        arq_png.write_text("png", encoding="utf-8")
        arq_py.write_text("py", encoding="utf-8")

        previa = organizador.gerar_previa(self.pasta_permitida, criterio="tipo")
        self.assertTrue(previa["ok"])
        self.assertEqual(previa["total_arquivos"], 3)
        self.assertEqual(previa["resumo_categorias"]["Documentos"], 1)
        self.assertEqual(previa["resumo_categorias"]["Imagens"], 1)
        self.assertEqual(previa["resumo_categorias"]["Codigo"], 1)

        # Garantia de que NENHUM arquivo foi movido durante a previa
        self.assertTrue(arq_pdf.exists())
        self.assertTrue(arq_png.exists())
        self.assertTrue(arq_py.exists())
        self.assertFalse((self.pasta_permitida / "Documentos").exists())
        self.assertFalse((self.pasta_permitida / "Imagens").exists())
        self.assertFalse((self.pasta_permitida / "Codigo").exists())

    def test_previa_por_data(self):
        arq = self.pasta_permitida / "antigo.txt"
        arq.write_text("antigo", encoding="utf-8")

        previa = organizador.gerar_previa(self.pasta_permitida, criterio="data")
        self.assertTrue(previa["ok"])
        self.assertEqual(previa["total_arquivos"], 1)
        mov = previa["movimentacoes"][0]
        agora = datetime.now()
        ano_mes = f"{agora.year}/{agora.year}-{agora.month:02d}"
        self.assertEqual(mov["categoria"], ano_mes)
        self.assertIn(str(agora.year), mov["destino"])
        self.assertIn(f"{agora.year}-{agora.month:02d}", mov["destino"])
        # Nada movido
        self.assertTrue(arq.exists())

    def test_previa_por_disciplina(self):
        arq_dir = self.pasta_permitida / "resumo_direito_civil.docx"
        arq_dir.write_text("civil", encoding="utf-8")

        with mock.patch("nextor.estudos.listar_disciplinas", return_value=[{"nome": "Direito Civil", "slug": "direito-civil"}]):
            previa = organizador.gerar_previa(self.pasta_permitida, criterio="disciplina")
        self.assertTrue(previa["ok"])
        self.assertEqual(previa["total_arquivos"], 1)
        self.assertIn("Direito Civil", previa["movimentacoes"][0]["destino"])
        self.assertTrue(arq_dir.exists())

    def test_previa_pasta_vazia(self):
        previa = organizador.gerar_previa(self.pasta_permitida)
        self.assertTrue(previa["ok"])
        self.assertEqual(previa["total_arquivos"], 0)
        self.assertEqual(len(previa["movimentacoes"]), 0)


class TestExecutarOrganizacao(BaseOrganizadorTestCase):
    def test_executar_organizacao_move_arquivos_corretamente(self):
        p1 = self.pasta_permitida / "documento.pdf"
        p2 = self.pasta_permitida / "imagem.png"
        p1.write_text("conteudo 1", encoding="utf-8")
        p2.write_text("conteudo 2", encoding="utf-8")

        previa = organizador.gerar_previa(self.pasta_permitida, criterio="tipo")
        resultado = organizador.executar_organizacao(id_sessao=previa["id_sessao"])

        self.assertTrue(resultado["ok"])
        self.assertEqual(resultado["total_movidos"], 2)

        # Arquivos foram para as subpastas
        dest_pdf = self.pasta_permitida / "Documentos" / "documento.pdf"
        dest_png = self.pasta_permitida / "Imagens" / "imagem.png"
        self.assertTrue(dest_pdf.exists())
        self.assertTrue(dest_png.exists())
        self.assertEqual(dest_pdf.read_text(encoding="utf-8"), "conteudo 1")
        self.assertEqual(dest_png.read_text(encoding="utf-8"), "conteudo 2")

        # Nao estao mais na raiz
        self.assertFalse(p1.exists())
        self.assertFalse(p2.exists())

        # Historico gravado no JSON
        self.assertTrue(self.arquivo_historico.exists())
        historico = json.loads(self.arquivo_historico.read_text(encoding="utf-8"))
        self.assertEqual(len(historico), 1)
        self.assertEqual(historico[0]["id_operacao"], resultado["id_operacao"])
        self.assertFalse(historico[0]["desfeita"])

    def test_executar_organizacao_trata_colisao(self):
        sub_docs = self.pasta_permitida / "Documentos"
        sub_docs.mkdir(parents=True, exist_ok=True)
        (sub_docs / "doc.pdf").write_text("versao antiga ja existente", encoding="utf-8")

        p_novo = self.pasta_permitida / "doc.pdf"
        p_novo.write_text("versao nova da raiz", encoding="utf-8")

        previa = organizador.gerar_previa(self.pasta_permitida, criterio="tipo")
        resultado = organizador.executar_organizacao(id_sessao=previa["id_sessao"])

        self.assertTrue(resultado["ok"])
        # Ambos arquivos continuam existindo sem sobrescrita
        self.assertEqual((sub_docs / "doc.pdf").read_text(encoding="utf-8"), "versao antiga ja existente")
        self.assertTrue((sub_docs / "doc_1.pdf").exists())
        self.assertEqual((sub_docs / "doc_1.pdf").read_text(encoding="utf-8"), "versao nova da raiz")


class TestDesfazerOrganizacao(BaseOrganizadorTestCase):
    def test_desfazer_restaura_arquivos_e_remove_subpastas_vazias(self):
        p1 = self.pasta_permitida / "relatorio.pdf"
        p2 = self.pasta_permitida / "figura.png"
        p1.write_text("pdf data", encoding="utf-8")
        p2.write_text("png data", encoding="utf-8")

        organizador.gerar_previa(self.pasta_permitida, criterio="tipo")
        res_exec = organizador.executar_organizacao()
        self.assertTrue(res_exec["ok"])
        self.assertEqual(res_exec["total_movidos"], 2)

        # Desfazer
        res_desfazer = organizador.desfazer_ultima_organizacao(pasta=str(self.pasta_permitida))
        self.assertTrue(res_desfazer["ok"])
        self.assertEqual(res_desfazer["total_desfeitos"], 2)

        # Arquivos voltaram para a raiz
        self.assertTrue(p1.exists())
        self.assertTrue(p2.exists())
        self.assertEqual(p1.read_text(encoding="utf-8"), "pdf data")

        # Subpastas vazias Documentos e Imagens foram removidas
        self.assertFalse((self.pasta_permitida / "Documentos").exists())
        self.assertFalse((self.pasta_permitida / "Imagens").exists())

        # Operacao marcada como desfeita no historico
        historico = json.loads(self.arquivo_historico.read_text(encoding="utf-8"))
        self.assertTrue(historico[0]["desfeita"])
        self.assertIn("desfeita_em", historico[0])

    def test_desfazer_sem_operacoes_ativas(self):
        res = organizador.desfazer_ultima_organizacao(pasta=str(self.pasta_permitida))
        self.assertFalse(res["ok"])
        self.assertEqual(res["erro"], "nenhuma_operacao_encontrada")


class TestGatilhosRoteador(BaseOrganizadorTestCase):
    def test_gatilhos_organizar_previa(self):
        with mock.patch("nextor.organizador.gerar_previa_por_frase", return_value="Previa gerada: 5 arquivos.") as mock_prev:
            r1 = roteador.rotear("organiza minha pasta downloads")
            self.assertEqual(r1["intencao"], "organizador_previa")
            self.assertEqual(r1["resposta"], "Previa gerada: 5 arquivos.")
            mock_prev.assert_called_with("downloads", criterio="tipo")

            r2 = roteador.rotear("organizar a pasta documentos por data")
            self.assertEqual(r2["intencao"], "organizador_previa")
            mock_prev.assert_called_with("documentos", criterio="data")

    def test_gatilhos_confirmar(self):
        with mock.patch("nextor.organizador.confirmar_organizacao_pendente", return_value="Organizacao concluida: 3 arquivos movidos.") as mock_conf:
            r = roteador.rotear("confirma organizacao")
            self.assertEqual(r["intencao"], "organizador_confirmar")
            self.assertEqual(r["resposta"], "Organizacao concluida: 3 arquivos movidos.")
            mock_conf.assert_called_once()

    def test_gatilhos_desfazer(self):
        with mock.patch("nextor.organizador.desfazer_organizacao_por_frase", return_value="Organizacao desfeita: 3 arquivos restaurados.") as mock_desf:
            r = roteador.rotear("desfaz a organizacao")
            self.assertEqual(r["intencao"], "organizador_desfazer")
            self.assertEqual(r["resposta"], "Organizacao desfeita: 3 arquivos restaurados.")
            mock_desf.assert_called_once()


class TestEndpointsHTTP(BaseOrganizadorTestCase):
    def test_bloqueio_sem_token_mestre_retorna_401(self):
        endpoints = [
            ("post", "/v1/organizador/previa", {"pasta": str(self.pasta_permitida)}),
            ("post", "/v1/organizador/executar", {}),
            ("post", "/v1/organizador/desfazer", {}),
            ("get", "/v1/organizador/historico", None),
        ]
        for metodo, url, payload in endpoints:
            with self.subTest(url=url):
                if metodo == "post":
                    resp = self.client.post(url, json=payload)
                else:
                    resp = self.client.get(url)
                self.assertEqual(resp.status_code, 401)

    def test_pasta_nao_permitida_retorna_403(self):
        pasta_proibida = (self.caminho_base / "NaoAutorizada").resolve()
        pasta_proibida.mkdir(parents=True, exist_ok=True)
        resp = self.client.post(
            "/v1/organizador/previa",
            json={"pasta": str(pasta_proibida)},
            headers=self.h_mestre,
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.get_json()["erro"], "pasta_nao_permitida")

    def test_fluxo_completo_endpoints_http(self):
        arq = self.pasta_permitida / "plano.docx"
        arq.write_text("documento docx", encoding="utf-8")

        # 1. Previa
        resp_previa = self.client.post(
            "/v1/organizador/previa",
            json={"pasta": str(self.pasta_permitida), "criterio": "tipo"},
            headers=self.h_mestre,
        )
        self.assertEqual(resp_previa.status_code, 200)
        dados_prev = resp_previa.get_json()
        self.assertTrue(dados_prev["ok"])
        id_sessao = dados_prev["id_sessao"]
        self.assertEqual(dados_prev["total_arquivos"], 1)

        # 2. Executar
        resp_exec = self.client.post(
            "/v1/organizador/executar",
            json={"id_sessao": id_sessao},
            headers=self.h_mestre,
        )
        self.assertEqual(resp_exec.status_code, 200)
        self.assertEqual(resp_exec.get_json()["total_movidos"], 1)
        self.assertTrue((self.pasta_permitida / "Documentos" / "plano.docx").exists())

        # 3. Historico
        resp_hist = self.client.get("/v1/organizador/historico", headers=self.h_mestre)
        self.assertEqual(resp_hist.status_code, 200)
        historico = resp_hist.get_json()["historico"]
        self.assertEqual(len(historico), 1)
        self.assertEqual(historico[0]["total_movidos"], 1)

        # 4. Desfazer
        resp_desf = self.client.post(
            "/v1/organizador/desfazer",
            json={"pasta": str(self.pasta_permitida)},
            headers=self.h_mestre,
        )
        self.assertEqual(resp_desf.status_code, 200)
        self.assertEqual(resp_desf.get_json()["total_desfeitos"], 1)
        self.assertTrue(arq.exists())
        self.assertFalse((self.pasta_permitida / "Documentos").exists())


if __name__ == "__main__":
    unittest.main()
