"""
Nextor - configuracao de primeira vez.

Cria (ou atualiza) o arquivo .env perguntando o essencial: seu nome, o nome do
dispositivo no Google Home, o token e, se quiser, o endereco iCal da agenda.

Rodar uma vez:
    .venv/Scripts/python.exe nextor_setup.py
"""
from pathlib import Path

PASTA = Path(__file__).resolve().parent
ENV = PASTA / ".env"

CAMPOS = [
    ("NEXTOR_NOME", "Seu nome", ""),
    ("NEXTOR_DISPOSITIVO", "Nome do dispositivo no Google Home", "Nome do dispositivo no Google Home"),
    ("NEXTOR_TOKEN", "Token (uma senha so sua para o servico)", "troque-este-token"),
    ("NEXTOR_MODELO", "Modelo do Ollama", "qwen2.5:3b"),
    ("NEXTOR_PORTA", "Porta do servico", "5005"),
    ("NEXTOR_FUSO", "Fuso horario (IANA)", "America/Sao_Paulo"),
    ("NEXTOR_AGENDA_ICAL", "Endereco secreto iCal da Google Agenda (opcional)", ""),
    ("NEXTOR_NOTICIAS_ASSUNTO", "Assunto das noticias", "inteligencia artificial generativa"),
]


def carregar_atual() -> dict:
    atual = {}
    if ENV.exists():
        for linha in ENV.read_text(encoding="utf-8").splitlines():
            if "=" in linha and not linha.strip().startswith("#"):
                k, v = linha.split("=", 1)
                atual[k.strip()] = v.strip()
    return atual


def main():
    print("Configuracao do Nextor. Enter mantem o valor atual (entre colchetes).\n")
    atual = carregar_atual()
    novo = {}
    for chave, rotulo, padrao in CAMPOS:
        valor_atual = atual.get(chave, padrao)
        resp = input(f"{rotulo} [{valor_atual}]: ").strip()
        novo[chave] = resp or valor_atual
    linhas = [f"{k}={v}" for k, v in novo.items()]
    ENV.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    print(f"\nPronto. Salvo em {ENV}.")
    nome = novo.get("NEXTOR_NOME")
    if nome:
        print(f"Ola, {nome}. Agora rode: .venv/Scripts/python.exe nextor_service.py")


if __name__ == "__main__":
    main()
