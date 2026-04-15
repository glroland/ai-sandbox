IMAGE := registry.home.glroland.com/ai/docling-process-func:1a

install:
	pip install -r requirements.txt

build:
	podman build --platform linux/amd64 -f Containerfile -t $(IMAGE) .

push:
	podman push $(IMAGE)

deploy:
	helm upgrade --install docling-eventing deploy/helm

undeploy:
	helm uninstall docling-eventing --ignore-not-found

.PHONY: install build push deploy undeploy
