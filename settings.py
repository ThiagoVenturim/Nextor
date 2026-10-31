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
# Endereco privado iCal da sua Google Agenda (segredo). Opcional.
AGENDA_ICAL = os.getenv("NEXTOR_AGENDA_ICAL", "")
# Fuso horario (IANA).
FUSO = os.getenv("NEXTOR_FUSO", "America/Sao_Paulo")
# Nome do usuario (o Nextor trata a pessoa por este nome).
NOME = os.getenv("NEXTOR_NOME", "")
# Assunto padrao das noticias.
NOTICIAS_ASSUNTO = os.getenv("NEXTOR_NOTICIAS_ASSUNTO", "inteligencia artificial generativa")
# Rotina matinal: hora (HH:MM) e assunto das noticias (vazio = usa o padrao acima).
ROTINA_HORA = os.getenv("NEXTOR_ROTINA_HORA", "07:00")
ROTINA_ASSUNTO = os.getenv("NEXTOR_ROTINA_ASSUNTO", "")
