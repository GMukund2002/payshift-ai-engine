# JDK + Maven are runtime dependencies, not just build-time: the agent's
# compile_project/run_tests nodes shell out to a real `mvn compile`/`mvn test`
# against whatever repo is being analyzed, so that verification step stays
# genuinely real in the deployed container, not simulated.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    default-jdk maven \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./requirements.txt
COPY ai-engine/requirements.txt ./ai-engine/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
