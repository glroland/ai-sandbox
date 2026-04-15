IMAGE := registry.home.glroland.com/ai/docling-process-func:1a

PIP := $(if $(shell command -v uv 2>/dev/null),uv pip,pip)

install:
	$(PIP) install --upgrade -r requirements.txt

build:
	podman build --platform linux/amd64 -f Containerfile -t $(IMAGE) .

push:
	podman push $(IMAGE)

deploy:
	helm upgrade --install docling-eventing deploy/helm

undeploy:
	helm uninstall docling-eventing

test:
	pytest tests/ -v

.PHONY: install build push deploy undeploy test
