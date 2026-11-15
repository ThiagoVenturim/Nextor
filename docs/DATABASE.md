# Configuracao de Banco de Dados Plugavel

O Nextor suporta persistencia de dados plugavel atraves do SQLAlchemy Core, mantendo o SQLite como padrao com zero configuracao e permitindo utilizar bancos de dados relacionais externos (PostgreSQL, MySQL, SQL Server via ODBC).

## Padrao: SQLite local (zero configuracao)

Se a variavel `DB_URL` (ou `NEXTOR_DB_URL`) nao for configurada, o Nextor utiliza automaticamente o banco SQLite local em:
- GTD: `~/.nextor/gtd.db` (ou caminho definido em `NEXTOR_GTD_DB`)
- Coach: `~/.nextor/coach.db` (ou caminho definido em `NEXTOR_COACH_DB`)

Nao e necessario instalar drivers adicionais nem rodar servidores externos para comecar.

## Banco personalizado via DB_URL

Para apontar o Nextor para um banco de dados externo, configure a variavel `DB_URL` no seu ambiente ou no arquivo `.env`. Copie o modelo `.env.example`:

```bash
cp .env.example .env
```

A variavel segue o padrao de URL de conexao do SQLAlchemy:
`dialeto+driver://usuario:senha@host:porta/banco`

### PostgreSQL

Instale o driver opcional de PostgreSQL:

```bash
pip install ".[postgres]"
```

Configure `DB_URL`:

```env
DB_URL=postgresql+psycopg://nextor:senha@localhost:5432/nextor
```

### MySQL / MariaDB

Instale o driver opcional de MySQL:

```bash
pip install ".[mysql]"
```

Configure `DB_URL`:

```env
DB_URL=mysql+pymysql://nextor:senha@localhost:3306/nextor
```

### Microsoft SQL Server (ODBC)

Instale o wrapper ODBC do SQLAlchemy:

```bash
pip install ".[mssql]"
```

Configure `DB_URL` apontando para o driver ODBC instalado no sistema:

```env
DB_URL=mssql+pyodbc://nextor:senha@localhost:1433/nextor?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes
```

Tambem e possivel utilizar DSN configurado no sistema:

```env
DB_URL=mssql+pyodbc:///?odbc_connect=DSN=MeuDSN;UID=nextor;PWD=senha
```

## Conteineres (Docker e Docker Compose)

A raiz do repositorio disponibiliza `Dockerfile` e `docker-compose.yml`.

### Execucao padrao com SQLite em volume

```bash
docker compose up --build
```

Os dados do SQLite sao salvos no volume `nextor_data` mapeado em `/data`.

### Execucao com PostgreSQL integrado

Utilize o perfil `postgres` do Docker Compose para subir uma instancia PostgreSQL junto ao Nextor:

```bash
docker compose --profile postgres up --build
```

## Kubernetes (k8s)

Manifestos de exemplo estao disponiveis no diretorio `k8s/`:

- `k8s/deployment.yaml`: Deployment com limites de CPU/memoria, volume persistente e usuario nao-root.
- `k8s/service.yaml`: Servico ClusterIP na porta 5005.
- `k8s/configmap.yaml`: Variaveis nao-sensiveis (`NEXTOR_PORTA`, `NEXTOR_VOZ_SAIDA`, etc.).
- `k8s/secret.yaml`: Credenciais e segredos (`NEXTOR_TOKEN` e `DB_URL`).

Para aplicar no cluster:

```bash
kubectl apply -f k8s/
```

## Scripts de execucao multiplataforma

Os scripts facilitam a execucao em qualquer sistema operacional:

- Windows (PowerShell):
  ```powershell
  .\scripts\run.ps1 local             # Executa o Nextor
  .\scripts\run.ps1 test              # Executa testes e verificacoes
  .\scripts\run.ps1 docker            # Sobe via Docker Compose
  .\scripts\run.ps1 docker-postgres   # Sobe via Docker Compose com PostgreSQL
  ```

- Linux / macOS (Bash):
  ```bash
  ./scripts/run.sh local
  ./scripts/run.sh test
  ./scripts/run.sh docker
  ./scripts/run.sh docker-postgres
  ```
