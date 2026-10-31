"""
Controle do Nest pela rede local (pychromecast), sem nuvem do Google nem token.

Permite ao Nextor controlar o proprio alto-falante: volume, parar, status. E, de forma
experimental, usar o Nest como gatilho fisico: um vigia observa o estado (ex.: volume)
e dispara um comando quando muda - util como "botao" pelo toque no topo do Nest.

Limite honesto: nao da para ler a voz/intencoes do Nest (microfone fechado). Isto aqui e
controle e leitura de estado, nao captura de fala.
"""
import threading
import time

import pychromecast

from . import config


def _conectar():
    casts, browser = pychromecast.get_listed_chromecasts(friendly_names=[config.DISPOSITIVO])
    if not casts:
        pychromecast.discovery.stop_discovery(browser)
        raise RuntimeError(f"Nest '{config.DISPOSITIVO}' nao encontrado na rede.")
    cc = casts[0]
    cc.wait(timeout=15)
    return cc, browser


def volume(nivel_0a100: int) -> str:
    cc, browser = _conectar()
    try:
        cc.set_volume(max(0, min(100, int(nivel_0a100))) / 100.0)
        time.sleep(0.5)
        return f"Volume do Nest em {int(nivel_0a100)} por cento."
    finally:
        pychromecast.discovery.stop_discovery(browser)


def parar() -> str:
    cc, browser = _conectar()
    try:
        cc.media_controller.stop()
        cc.quit_app()
        return "Parei o que estava tocando no Nest."
    finally:
        pychromecast.discovery.stop_discovery(browser)


def status() -> dict:
    cc, browser = _conectar()
    try:
        return {
            "nome": cc.name,
            "volume": round(cc.status.volume_level * 100),
            "mutado": cc.status.volume_muted,
            "app": cc.status.display_name,
            "midia": cc.media_controller.status.player_state,
        }
    finally:
        pychromecast.discovery.stop_discovery(browser)


# --- Gatilho fisico (experimental): Nest como botao, vigiando o volume ---

def vigiar(ao_disparar, alvo: int = 100, tolerancia: int = 3, intervalo: float = 2.0) -> None:
    """Dispara ao_disparar() quando o volume do Nest chega perto de 'alvo' (0-100).
    Pensado para rodar numa thread. Ex.: deslize o volume ao maximo no topo do Nest."""
    cc, browser = _conectar()
    ultimo = None
    try:
        while True:
            vol = round(cc.status.volume_level * 100)
            perto = abs(vol - alvo) <= tolerancia
            if perto and ultimo is not None and not ultimo:
                try:
                    ao_disparar()
                except Exception as e:
                    print(f"[nest] erro no gatilho: {e}")
            ultimo = perto
            time.sleep(intervalo)
    finally:
        pychromecast.discovery.stop_discovery(browser)


def iniciar_vigia_se_configurado() -> None:
    if not config.NEST_VIGIA_ACAO:
        return

    def acao():
        from .roteador import rotear
        from .voz import falar
        r = rotear(config.NEST_VIGIA_ACAO)
        falar(r["resposta"])

    t = threading.Thread(
        target=lambda: vigiar(acao, alvo=config.NEST_VIGIA_VOLUME),
        name="nextor-nest-vigia", daemon=True,
    )
    t.start()
    print(f"[nest] vigia ativo: volume ~{config.NEST_VIGIA_VOLUME}% dispara '{config.NEST_VIGIA_ACAO}'.")
