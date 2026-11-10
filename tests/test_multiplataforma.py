"""Testes unitarios offline do suporte multiplataforma e PWA universal (Issue #52)."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ["NEXTOR_VOZ_SAIDA"] = "nenhuma"

from nextor import config, janela, multiplataforma, servico
from scripts import empacotar_desktop


class TestPwaUniversalEndpoints(unittest.TestCase):
    def setUp(self):
        self.token_mestre = "nxt_mestre_seguro_123456789012345"
        self.patch_token = mock.patch.object(config, "TOKEN", self.token_mestre)
        self.patch_token.start()
        self.client = servico.app.test_client()

    def tearDown(self):
        self.patch_token.stop()

    def test_raiz_e_painel_servem_pwa_universal(self):
        for rota in ("/", "/painel"):
            with self.subTest(rota=rota):
                res = self.client.get(rota)
                self.assertEqual(res.status_code, 200)
                html = res.get_data(as_text=True)
                self.assertIn('rel="manifest" href="/manifest.webmanifest"', html)
                self.assertIn('/web/painel.js', html)
                self.assertIn('/web/painel.css', html)
                self.assertIn('id="btn-instalar-pwa"', html)

    def test_manifest_universal_valido_e_instalavel(self):
        res = self.client.get("/manifest.webmanifest")
        self.assertEqual(res.status_code, 200)
        self.assertIn("application/manifest+json", res.content_type)
        dados = json.loads(res.get_data(as_text=True))
        self.assertEqual(dados["short_name"], "Nextor")
        self.assertEqual(dados["start_url"], "/painel")
        self.assertEqual(dados["scope"], "/")
        self.assertEqual(dados["display"], "standalone")
        tamanhos = {ic["sizes"] for ic in dados["icons"]}
        self.assertIn("192x192", tamanhos)
        self.assertIn("512x512", tamanhos)
        urls_atalhos = {s["url"] for s in dados.get("shortcuts", [])}
        self.assertIn("/painel", urls_atalhos)
        self.assertIn("/gtd", urls_atalhos)
        self.assertIn("/download", urls_atalhos)

    def test_service_worker_universal_servido_na_raiz(self):
        res = self.client.get("/sw.js")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("Service-Worker-Allowed"), "/")
        self.assertIn("no-cache", res.headers.get("Cache-Control", ""))
        codigo = res.get_data(as_text=True)
        self.assertIn("nextor-pwa-shell-v1", codigo)
        self.assertIn("/painel", codigo)
        self.assertIn("/gtd", codigo)
        self.assertIn("/download", codigo)
        self.assertIn("ehRotaApi", codigo)

    def test_icones_pwa_retornam_png_valido(self):
        for rota in ("/icone-192.png", "/icone-512.png"):
            with self.subTest(rota=rota):
                res = self.client.get(rota)
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.mimetype, "image/png")
                self.assertTrue(res.data.startswith(b"\x89PNG"))

    def test_rosto_inclui_manifest_e_service_worker(self):
        res = self.client.get("/rosto")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn('rel="manifest" href="/manifest.webmanifest"', html)
        res_js = self.client.get("/web/rosto.js")
        self.assertEqual(res_js.status_code, 200)
        self.assertIn("serviceWorker.register('/sw.js'", res_js.get_data(as_text=True))

    def test_painel_js_usa_header_token_e_limpa_url(self):
        res = self.client.get("/web/painel.js")
        self.assertEqual(res.status_code, 200)
        js = res.get_data(as_text=True)
        self.assertIn("X-Nextor-Token", js)
        self.assertIn("history.replaceState", js)
        self.assertIn("beforeinstallprompt", js)
        self.assertIn("serviceWorker.register('/sw.js'", js)


class TestPaginaDownloadECatalogoPlataformas(unittest.TestCase):
    def setUp(self):
        self.client = servico.app.test_client()

    def test_pagina_download_e_instalar(self):
        for rota in ("/download", "/instalar"):
            with self.subTest(rota=rota):
                res = self.client.get(rota)
                self.assertEqual(res.status_code, 200)
                html = res.get_data(as_text=True)
                for plat in ("windows", "linux", "macos", "android", "ios", "web"):
                    self.assertIn(f'data-plat="{plat}"', html)
                self.assertIn("Tailscale", html)
                self.assertIn("Nunca abra portas no roteador", html)

    def test_endpoint_v1_plataformas_detecta_sistema_pelo_user_agent(self):
        casos = {
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64)": "windows",
            "Mozilla/5.0 (X11; Linux x86_64)": "linux",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0)": "macos",
            "Mozilla/5.0 (Linux; Android 14; Pixel 8)": "android",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X)": "ios",
            "Mozilla/5.0 (iPad; CPU OS 17_4 like Mac OS X)": "ios",
            "": "web",
        }
        for ua, esperado in casos.items():
            with self.subTest(ua=ua):
                res = self.client.get("/v1/plataformas", headers={"User-Agent": ua})
                self.assertEqual(res.status_code, 200)
                dados = res.get_json()
                self.assertTrue(dados["ok"])
                self.assertEqual(dados["plataforma_detectada"], esperado)
                self.assertTrue(dados["pwa"]["ok"])
                ids = [p["id"] for p in dados["plataformas"]]
                self.assertEqual(ids, ["web", "windows", "linux", "macos", "android", "ios"])


class TestModuloMultiplataforma(unittest.TestCase):
    def test_obter_plataforma_e_apelidos(self):
        self.assertEqual(multiplataforma.obter_plataforma("win")["id"], "windows")
        self.assertEqual(multiplataforma.obter_plataforma("mac")["id"], "macos")
        self.assertEqual(multiplataforma.obter_plataforma("iphone")["id"], "ios")
        self.assertEqual(multiplataforma.obter_plataforma("android")["id"], "android")
        self.assertIsNone(multiplataforma.obter_plataforma("symbian"))

    def test_verificar_requisitos_pwa_detecta_arquivos_ausentes(self):
        status_real = multiplataforma.verificar_requisitos_pwa()
        self.assertTrue(status_real["ok"])
        self.assertEqual(status_real["arquivos_ausentes"], [])

        with tempfile.TemporaryDirectory() as tmp:
            status_vazio = multiplataforma.verificar_requisitos_pwa(Path(tmp))
            self.assertFalse(status_vazio["ok"])
            self.assertIn("manifest.webmanifest", status_vazio["arquivos_ausentes"])

    def test_configs_empacotamento_reaproveitam_pwa_sem_segredos(self):
        tauri = multiplataforma.gerar_config_tauri(porta=5005)
        self.assertEqual(tauri["build"]["frontendDist"], "../../nextor/web")
        self.assertIn("msi", tauri["bundle"]["targets"])
        self.assertIn("appimage", tauri["bundle"]["targets"])
        self.assertIn("dmg", tauri["bundle"]["targets"])
        texto_tauri = json.dumps(tauri)
        self.assertNotIn(config.TOKEN, texto_tauri)

        cap = multiplataforma.gerar_config_capacitor()
        self.assertEqual(cap["webDir"], "../../nextor/web")
        self.assertNotIn(config.TOKEN, json.dumps(cap))


class TestJanelaEEmpacotamentoScript(unittest.TestCase):
    def test_localizar_navegador_app_por_plataforma(self):
        with mock.patch("pathlib.Path.is_file", return_value=True):
            self.assertIsNotNone(janela.localizar_navegador_app("win32"))
            self.assertIsNotNone(janela.localizar_navegador_app("darwin"))

        with mock.patch("shutil.which", return_value="/usr/bin/chromium"):
            self.assertEqual(janela.localizar_navegador_app("linux"), Path("/usr/bin/chromium"))

    def test_abrir_app_usa_modo_aplicativo(self):
        with mock.patch.object(janela, "localizar_navegador_app", return_value=Path("/usr/bin/chromium")), \
                mock.patch("subprocess.Popen") as popen:
            ok = janela.abrir_app("/painel", largura=900, altura=600)
            self.assertTrue(ok)
            args = popen.call_args[0][0]
            self.assertTrue(any(a.startswith("--app=http://localhost:") for a in args))
            self.assertIn("--window-size=900,600", args)

    def test_script_empacotar_desktop(self):
        with tempfile.TemporaryDirectory() as tmp:
            arqs = empacotar_desktop.sincronizar_arquivos_empacotamento(Path(tmp))
            self.assertTrue(Path(arqs["tauri"]).is_file())
            self.assertTrue(Path(arqs["capacitor"]).is_file())

        self.assertEqual(empacotar_desktop.main(["--plataforma", "windows"]), 0)
        self.assertEqual(empacotar_desktop.main(["--plataforma", "android"]), 0)
        self.assertEqual(empacotar_desktop.main(["--plataforma", "inexistente"]), 2)


if __name__ == "__main__":
    unittest.main()
