"""
Configuracao do Nextor. Le os valores do arquivo .env (que nao vai para o git).
Copie .env.example para .env e ajuste. Veja README.md.
"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass  # sem python-dotenv, usa variaveis de ambiente do sistema

# Nome do dispositivo exatamente como aparece no app Google Home.
DISPOSITIVO = os.getenv("NEXTOR_DISPOSITIVO", "Nome do dispositivo no Google Home")
# Token simples para proteger o servico na rede local.
TOKEN = os.getenv("NEXTOR_TOKEN", "troque-este-token")
# Modelo local no Ollama usado como cerebro.
MODELO = os.getenv("NEXTOR_MODELO", "qwen2.5:3b")
# Porta do servico local.
PORTA = int(os.getenv("NEXTOR_PORTA", "5005"))
