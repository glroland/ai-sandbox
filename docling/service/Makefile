IMAGE_NAME   ?= docling-service
IMAGE_TAG    ?= latest
REGISTRY     ?= quay.io/$(USER)
FULL_IMAGE   := $(REGISTRY)/$(IMAGE_NAME):$(IMAGE_TAG)
PORT         ?= 8080
PYTHONPATH   := $(CURDIR)/src

.PHONY: help install install-dev run test lint build push clean

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "Targets:"
	@echo "  install      Install production dependencies"
	@echo "  install-dev  Install dev + test dependencies"
	@echo "  run          Run the service locally with uvicorn (hot-reload)"
	@echo "  test         Run unit tests"
	@echo "  lint         Run ruff linter"
	@echo "  build        Build the container image"
	@echo "  push         Push the container image to REGISTRY"
	@echo "  clean        Remove __pycache__ and .pytest_cache"

install:
	pip install --no-cache-dir -r requirements.txt

install-dev:
	pip install --no-cache-dir -r requirements-dev.txt

run:
	PYTHONPATH=$(PYTHONPATH) uvicorn app.main:app --host 0.0.0.0 --port $(PORT) --reload

test:
	PYTHONPATH=$(PYTHONPATH) pytest tests/ -v

lint:
	PYTHONPATH=$(PYTHONPATH) ruff check src/ tests/

build:
	podman build -f Containerfile -t $(FULL_IMAGE) .

push:
	podman push $(FULL_IMAGE)

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache  -exec rm -rf {} + 2>/dev/null || true
