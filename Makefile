.PHONY: setup build-analyzer build-sample-app test-java test-python test-all run-ui run-server run-cli benchmark clean \
        docker-build docker-run docker-stop docker-shell docker-test docker-test-java docker-build-analyzer docker-eval

MVN_SETTINGS := -s "$(CURDIR)/settings.xml"

# ---------------------------------------------------------------------------
# Docker workflow (recommended): needs only Docker, no local JDK/Maven/Python.
# The dev targets bind-mount this checkout over /app so they always run the
# current working tree, and reuse a named volume as the Maven cache.
# ---------------------------------------------------------------------------
IMAGE      ?= payshift-ai:local
CONTAINER  ?= payshift-local
M2_VOLUME  ?= payshift-m2
DOCKER_DEV := docker run --rm -v "$(CURDIR)":/app -v $(M2_VOLUME):/root/.m2 -w /app
ENV_FILE   := $(if $(wildcard .env),--env-file .env,)

docker-build:
	docker build -t $(IMAGE) .

docker-run: docker-stop
	docker run -d --name $(CONTAINER) -p 8000:8000 $(ENV_FILE) \
		-v "$(CURDIR)":/app -v $(M2_VOLUME):/root/.m2 $(IMAGE)
	@echo "PayShift running at http://localhost:8000"

docker-stop:
	-@docker rm -f $(CONTAINER) >/dev/null 2>&1 || true

docker-shell:
	$(DOCKER_DEV) -it $(ENV_FILE) $(IMAGE) bash

docker-test:
	$(DOCKER_DEV) $(IMAGE) sh -c "cd ai-engine && python -m pytest tests/ -q -p no:cacheprovider"

docker-test-java:
	$(DOCKER_DEV) $(IMAGE) sh -c "cd java-analyzer && mvn -s /app/settings.xml -q test && cd ../sample-apps/merchant-app && mvn -s /app/settings.xml -q -DforkCount=0 test"

# Rebuilds java-analyzer and refreshes the committed deploy copy in dist/.
docker-build-analyzer:
	$(DOCKER_DEV) $(IMAGE) sh -c "cd java-analyzer && mvn -s /app/settings.xml -q package && cp target/java-analyzer.jar dist/java-analyzer.jar"

# Live evaluation across the sample-repo corpus (makes real, paid LLM calls).
docker-eval:
	$(DOCKER_DEV) $(ENV_FILE) $(IMAGE) sh -c "cd ai-engine && python -m evaluation.live_eval $(EVAL_ARGS)"

setup:
	python3 -m venv .venv
	. .venv/bin/activate && pip install --upgrade pip && pip install -r ai-engine/requirements.txt

build-analyzer:
	cd java-analyzer && mvn $(MVN_SETTINGS) -q -DskipTests package

build-sample-app:
	cd sample-apps/merchant-app && mvn $(MVN_SETTINGS) -q -DskipTests package

test-java:
	cd java-analyzer && mvn $(MVN_SETTINGS) -q test
	cd sample-apps/merchant-app && mvn $(MVN_SETTINGS) -q test

test-python:
	cd ai-engine && . ../.venv/bin/activate && python -m pytest tests/ -v

test-all: test-java test-python

run-ui:
	cd ai-engine && . ../.venv/bin/activate && streamlit run ../frontend/app.py

run-server:
	. .venv/bin/activate && uvicorn backend.main:app --reload --port 8000

run-cli:
	cd ai-engine && . ../.venv/bin/activate && python main.py --repository ../sample-apps/merchant-app --mode ADD_PSP --target-provider razorpay

benchmark:
	cd ai-engine && . ../.venv/bin/activate && python -m evaluation.benchmark

clean:
	rm -rf java-analyzer/target sample-apps/merchant-app/target .venv
