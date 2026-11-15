# JDK + Maven are runtime dependencies, not just build-time: the agent's
# compile_project/run_tests nodes shell out to a real `mvn compile`/`mvn test`
# against whatever repo is being analyzed, so that verification step stays
# genuinely real in the deployed container, not simulated.
#
# default-jdk-HEADLESS, not default-jdk: the full JDK package pulls in X11,
# Mesa and a ~23MB LLVM purely for desktop GUI support this service never
# uses, and installing it was OOM-killed outright inside a 4GB Docker VM.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    default-jdk-headless maven \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./requirements.txt
COPY ai-engine/requirements.txt ./ai-engine/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
