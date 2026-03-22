FROM pgvector/pgvector:pg16

RUN apt-get update && apt-get install -y \
    python3 \
    curl \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv and add to PATH
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    mv /root/.local/bin/uv /usr/local/bin/uv && \
    mv /root/.local/bin/uvx /usr/local/bin/uvx

# Create virtual environment with uv
RUN uv venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV VIRTUAL_ENV="/opt/venv"

# Install CPU-only PyTorch and dependencies
RUN uv pip install --no-cache \
    torch --index-url https://download.pytorch.org/whl/cpu

RUN uv pip install --no-cache \
    numpy>=1.24.0 \
    psycopg2-binary>=2.9.0 \
    sentence-transformers>=2.2.0

COPY init.sql /docker-entrypoint-initdb.d/01-init.sql

COPY data/data /app/data

COPY data/scripts/db_loader.py /app/db_loader.py

RUN echo '#!/bin/bash\n\
    set -e\n\
    \n\
    docker-entrypoint.sh postgres &\n\
    PG_PID=$!\n\
    \n\
    echo "Waiting for PostgreSQL to start..."\n\
    until pg_isready -U postgres -d interiit_nlp3; do\n\
    sleep 2\n\
    done\n\
    echo "PostgreSQL is ready!"\n\
    \n\
    LOADED=$(psql -U postgres -d interiit_nlp3 -tAc "SELECT COUNT(*) FROM transcripts;" 2>/dev/null || echo "0")\n\
    if [ "$LOADED" = "0" ] || [ -z "$LOADED" ]; then\n\
    echo "Loading data into database..."\n\
    cd /app && python db_loader.py\n\
    else\n\
    echo "Data already loaded ($LOADED transcripts found). Skipping load."\n\
    fi\n\
    \n\
    wait $PG_PID\n\
    ' > /usr/local/bin/start-with-loader.sh && chmod +x /usr/local/bin/start-with-loader.sh

ENV POSTGRES_HOST=localhost
ENV POSTGRES_PORT=5432

CMD ["/usr/local/bin/start-with-loader.sh"]
