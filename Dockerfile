FROM python:3.12-slim

ARG EXTRAS="postgres,mysql"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NEXTOR_PORTA=5005 \
    NEXTOR_VOZ_SAIDA=nenhuma

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        gcc \
        python3-dev \
        unixodbc \
        unixodbc-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml README.md LICENSE ./
RUN pip install --upgrade pip && \
    pip install -r requirements.txt && \
    if [ -n "${EXTRAS}" ]; then \
        case ",${EXTRAS}," in \
            *,postgres,*) pip install "psycopg[binary]>=3.1.0" ;; \
        esac; \
        case ",${EXTRAS}," in \
            *,mysql,*) pip install "pymysql>=1.1.0" "cryptography>=41.0.0" ;; \
        esac; \
        case ",${EXTRAS}," in \
            *,mssql,*) pip install "pyodbc>=5.0.0" ;; \
        esac; \
    fi

COPY . .

RUN useradd --create-home --shell /bin/bash nextor && \
    mkdir -p /data && \
    chown -R nextor:nextor /app /data

USER nextor
VOLUME ["/data"]
EXPOSE 5005

ENTRYPOINT ["python", "-m", "nextor"]
CMD []
