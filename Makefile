# Atalhos para Linux/macOS (no Windows, use os .bat da pasta windows/).
# Uso: make install | run | test | lint | typecheck | update-data | retrain
# Para usar outro Python:  make PYTHON=python3.12 install
PYTHON ?= python3
VENV   ?= .venv
BIN    := $(VENV)/bin
PORT   ?= 8501

.PHONY: help install run test lint typecheck check update-data retrain

help:
	@echo "Alvos: install, run, test, lint, typecheck, check, update-data, retrain"

$(BIN)/python:
	$(PYTHON) -m venv $(VENV)

install: $(BIN)/python
	$(BIN)/python -m pip install --upgrade pip
	$(BIN)/python -m pip install -r requirements-dev.txt

run: $(BIN)/python
	$(BIN)/python -m streamlit run app.py --server.port $(PORT)

test: $(BIN)/python
	$(BIN)/python -m pytest -q

lint: $(BIN)/python
	$(BIN)/python -m ruff check .

typecheck: $(BIN)/python
	$(BIN)/python -m mypy src pages app.py desktop_launcher.py scripts

# Os mesmos três comandos do CI.
check: lint typecheck test

# Jogos finalizados do dia anterior e jogos novos (veja docs/ATUALIZACAO_DIARIA.md).
update-data: $(BIN)/python
	$(BIN)/python scripts/update_daily.py

retrain: $(BIN)/python
	$(BIN)/python scripts/retrain_models.py
