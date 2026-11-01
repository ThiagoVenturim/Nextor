"""Configuracao central do Nextor. Le o .env na raiz do projeto."""
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

# Perfil (agente): casa, escritorio, etc. Escolha por variavel de ambiente NEXTOR_PERFIL
# ou escrevendo o nome no arquivo .perfil. Cada perfil e um .env proprio (.env.<perfil>).
PERFIL = os.getenv("NEXTOR_PERFIL", "").strip()
if not PERFIL and (RAIZ / ".perfil").exists():
    PERFIL = (RAIZ / ".perfil").read_text(encoding="utf-8").strip()

_ENV = RAIZ / (f".env.{PERFIL}" if PERFIL else ".env")
if not _ENV.exists():
    _ENV = RAIZ / ".env"

try:
    from dotenv import load_dotenv
    load_dotenv(_ENV)
except ImportError:
    pass

# Identidade e dispositivo
NOME = os.getenv("NEXTOR_NOME", "")
DISPOSITIVO = os.getenv("NEXTOR_DISPOSITIVO", "Nome do dispositivo no Google Home")
PERSONA = os.getenv("NEXTOR_PERSONA", "assistente")

# Servico
TOKEN = os.getenv("NEXTOR_TOKEN", "troque-este-token")
PORTA = int(os.getenv("NEXTOR_PORTA", "5005"))

# Ponte com o NexDeck (stream deck no celular). Vazio = desligado.
DECK_URL = os.getenv("NEXTOR_DECK_URL", "").rstrip("/")
DECK_TOKEN = os.getenv("NEXTOR_DECK_TOKEN", "")

# Cerebro: "local" (Ollama) ou "claude" (API Anthropic). Claude cai para local se falhar.
CEREBRO = os.getenv("NEXTOR_CEREBRO", "local").lower()
# Cerebro local (Ollama)
MODELO = os.getenv("NEXTOR_MODELO", "qwen2.5:3b")
OLLAMA_URL = os.getenv("NEXTOR_OLLAMA_URL", "http://localhost:11434/api/chat")
# Cerebro na nuvem (Claude). A chave vai em ANTHROPIC_API_KEY no .env.
CLAUDE_MODELO = os.getenv("NEXTOR_CLAUDE_MODELO", "claude-haiku-5-5")
# Cerebro via agy/Maestri: agente da canvas que responde.
AGY_AGENTE = os.getenv("NEXTOR_AGY_AGENTE", "Claude Code")
# Pasta onde salvar textos (traducao/resumo/escrita). Vazio = pasta textos/ do projeto.
# Dica: aponte para um cofre do Obsidian para ler no celular.
TEXTOS_DIR = os.getenv("NEXTOR_TEXTOS_DIR", "")
# Gatilho fisico pelo Nest (experimental): ao levar o volume ao nivel abaixo, roda o comando.
NEST_VIGIA_ACAO = os.getenv("NEXTOR_NEST_VIGIA_ACAO", "")  # ex.: "o que tenho hoje"
NEST_VIGIA_VOLUME = int(os.getenv("NEXTOR_NEST_VIGIA_VOLUME", "100"))

# Ouvinte de voz no microfone (offline, Vosk). As frases de chamada ficam em nextor/chamado.py.
VOSK_MODELO = os.getenv("NEXTOR_VOSK_MODELO", str(RAIZ / "models" / "vosk-pt"))
# Segundos que o ouvinte espera um comando depois de "ei Nextor" sem precisar chamar de novo.
JANELA_ESCUTA = float(os.getenv("NEXTOR_JANELA_ESCUTA", "8"))
# Verificar que a voz e a do dono (opcional; precisa de resemblyzer e cadastro).
VERIFICAR_VOZ = os.getenv("NEXTOR_VERIFICAR_VOZ", "false").lower() in ("1", "true", "sim")
VOZ_DONO = RAIZ / "voz_dono.npy"

# Agenda e fuso
AGENDA_ICAL = os.getenv("NEXTOR_AGENDA_ICAL", "")
FUSO = os.getenv("NEXTOR_FUSO", "America/Sao_Paulo")

# Noticias
NOTICIAS_ASSUNTO = os.getenv("NEXTOR_NOTICIAS_ASSUNTO", "inteligencia artificial generativa")

# Rotina matinal
ROTINA_HORA = os.getenv("NEXTOR_ROTINA_HORA", "07:00")
ROTINA_ASSUNTO = os.getenv("NEXTOR_ROTINA_ASSUNTO", "")

# Caminhos de dados (ficam na raiz, fora do git)
ANOTACOES = RAIZ / "anotacoes.md"
MP3 = RAIZ / "nextor_fala.mp3"
LOG_COMANDOS = RAIZ / "comandos.log"
CATT = RAIZ / ".venv" / "Scripts" / "catt.exe"
