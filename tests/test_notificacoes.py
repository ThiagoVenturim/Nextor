"""Testes dos canais de notificacao e roteador multicanal."""

from __future__ import annotations

from datetime import time
import unittest
from unittest.mock import MagicMock, patch

from nextor.notificacoes import (
    CanalDiscord,
    CanalTelegram,
    CanalVoz,
    CanalWebPush,
    CanalWhatsApp,
    RoteadorNotificacoes,
)


class TestCanaisNotificacao(unittest.TestCase):
    def test_canal_discord_mock(self) -> None:
        chamadas = []

        def mock_client(url: str, payload: dict) -> bool:
            chamadas.append((url, payload))
            return True

        canal = CanalDiscord(webhook_url="https://discord.com/api/webhooks/test", http_client=mock_client)
        self.assertTrue(canal.configurado())
        ok = canal.enviar(titulo="Titulo", corpo="Alerta de teste")
        self.assertTrue(ok)
        self.assertEqual(len(chamadas), 1)

    def test_canal_whatsapp_mock(self) -> None:
        chamadas = []

        def mock_client(url: str, headers: dict, payload: dict) -> bool:
            chamadas.append((url, headers, payload))
            return True

        canal = CanalWhatsApp(
            token="token123",
            phone_id="phone123",
            destinatario="5511999999999",
            http_client=mock_client,
        )
        self.assertTrue(canal.configurado())
        ok = canal.enviar(titulo="Aviso", corpo="Mensagem WhatsApp")
        self.assertTrue(ok)
        self.assertEqual(len(chamadas), 1)

    def test_canal_webpush_mock(self) -> None:
        chamadas = []

        def mock_enviador(payload: dict, auth: dict) -> bool:
            chamadas.append((payload, auth))
            return True

        canal = CanalWebPush(
            public_key="pub123",
            private_key="priv123",
            subscriber_email="user@example.com",
            enviador_mock=mock_enviador,
        )
        self.assertTrue(canal.configurado())

        ok = canal.enviar(titulo="GTD", corpo="Notificacao Push")
        self.assertTrue(ok)
        self.assertEqual(len(chamadas), 1)

    def test_canal_voz(self) -> None:
        falas = []

        def mock_falar(msg: str) -> None:
            falas.append(msg)

        canal = CanalVoz(fn_falar=mock_falar)
        self.assertTrue(canal.configurado())
        ok = canal.enviar(titulo="Bom dia", corpo="Hora do foco")
        self.assertTrue(ok)
        self.assertEqual(falas, ["Bom dia. Hora do foco"])

    def test_canal_telegram_mock(self) -> None:
        canal = CanalTelegram(bot_token="bot123", chat_id="12345")
        self.assertTrue(canal.configurado())
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.return_value.__enter__.return_value.read.return_value = b'{"ok": true}'
            ok = canal.enviar(titulo="Alerta", corpo="Mensagem telegram")
            self.assertTrue(ok)


class TestRoteadorNotificacoes(unittest.TestCase):
    def test_roteamento_por_evento(self) -> None:
        chamadas_discord = []
        canal_discord = CanalDiscord(
            webhook_url="https://discord.com/webhook",
            http_client=lambda u, p: chamadas_discord.append(p) or True,
        )

        falas = []
        canal_voz = CanalVoz(fn_falar=lambda msg: falas.append(msg))

        roteador = RoteadorNotificacoes(
            canais={"discord": canal_discord, "voz": canal_voz}
        )

        config_usuario = {
            "canais_ativos": ["discord", "voz"],
            "eventos_notificacao": {
                "tarefa_concluida": ["discord"],
                "pomodoro_fim": ["voz"],
            },
            "horario_silencio": {"ativo": False},
        }

        res = roteador.notificar(
            evento="tarefa_concluida",
            titulo="Concluido",
            corpo="Tarefa feita",
            config_usuario=config_usuario,
        )
        self.assertTrue(res["sucesso"])
        self.assertIn("discord", res["despachados"])
        self.assertEqual(len(chamadas_discord), 1)
        self.assertEqual(len(falas), 0)

        res_voz = roteador.notificar(
            evento="pomodoro_fim",
            titulo="Pausa",
            corpo="Hora do descanso",
            config_usuario=config_usuario,
        )
        self.assertTrue(res_voz["sucesso"])
        self.assertIn("voz", res_voz["despachados"])
        self.assertEqual(len(falas), 1)

    def test_janela_silencio_bloqueia(self) -> None:
        falas = []
        canal_voz = CanalVoz(fn_falar=lambda msg: falas.append(msg))
        roteador = RoteadorNotificacoes(canais={"voz": canal_voz})

        config_usuario = {
            "canais_ativos": ["voz"],
            "eventos_notificacao": {"lembrete": ["voz"]},
            "horario_silencio": {"ativo": True, "inicio": "22:00", "fim": "07:00"},
        }

        # 23:30 esta dentro da janela de silencio
        res = roteador.notificar(
            evento="lembrete",
            titulo="Noite",
            corpo="Dormir",
            config_usuario=config_usuario,
            hora_referencia=time(23, 30),
        )
        self.assertTrue(res["silenciado"])
        self.assertEqual(len(res["despachados"]), 0)
        self.assertEqual(len(falas), 0)

    def test_falha_em_canal_nao_interrompe_outros(self) -> None:
        def erro_discord(u, p):
            raise RuntimeError("Conexao recusada")

        canal_discord = CanalDiscord(
            webhook_url="https://discord.com/webhook",
            http_client=erro_discord,
        )

        falas = []
        canal_voz = CanalVoz(fn_falar=lambda msg: falas.append(msg))

        roteador = RoteadorNotificacoes(
            canais={"discord": canal_discord, "voz": canal_voz}
        )

        config_usuario = {
            "canais_ativos": ["discord", "voz"],
            "eventos_notificacao": {"alerta": ["discord", "voz"]},
            "horario_silencio": {"ativo": False},
        }

        res = roteador.notificar(
            evento="alerta",
            titulo="Alerta",
            corpo="Falha no sistema",
            config_usuario=config_usuario,
        )
        self.assertIn("discord", res["falhas"])
        self.assertIn("voz", res["despachados"])
        self.assertEqual(len(falas), 1)


if __name__ == "__main__":
    unittest.main()
