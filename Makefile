.PHONY: setup build-analyzer build-sample-app test-java test-python test-all run-ui run-cli benchmark clean

MVN_SETTINGS := -s "$(CURDIR)/settings.xml"

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

run-cli:
	cd ai-engine && . ../.venv/bin/activate && python main.py --repository ../sample-apps/merchant-app --mode ADD_PSP --target-provider razorpay

benchmark:
	cd ai-engine && . ../.venv/bin/activate && python -m evaluation.benchmark

clean:
	rm -rf java-analyzer/target sample-apps/merchant-app/target .venv
