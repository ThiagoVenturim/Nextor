"""Configuracao central do Nextor. Le o .env na raiz do projeto."""
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(RAIZ / ".env")
except ImportError:
    pass

# Identidade e dispositivo
NOME = os.getenv("NEXTOR_NOME", "")
DISPOSITIVO = os.getenv("NEXTOR_DISPOSITIVO", "Nome do dispositivo no Google Home")
PERSONA = os.getenv("NEXTOR_PERSONA", "assistente")

# Servico
TOKEN = os.getenv("NEXTOR_TOKEN", "troque-este-token")
PORTA = int(os.getenv("NEXTOR_PORTA", "5005"))

# Cerebro (Ollama)
MODELO = os.getenv("NEXTOR_MODELO", "qwen2.5:3b")
OLLAMA_URL = os.getenv("NEXTOR_OLLAMA_URL", "http://localhost:11434/api/chat")

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
