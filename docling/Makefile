PIPELINE_NAME := "Docling Ingestion Pipeline"
TOKEN := $(shell oc whoami -t)
KFP := kfp --endpoint https://ds-pipeline-dspa-pipelines.apps.ocp.home.glroland.com --existing-token $(TOKEN)
TIMESTAMP := $(shell date +"%F %T")

compile:
	$(KFP) dsl compile --py as-pipeline.py --output pipeline.yaml

run:
	$(KFP) run create --package-file pipeline.yaml --experiment-name Default --run-name "$(TIMESTAMP)" "source_document_url=https://raw.githubusercontent.com/glroland/mechanic/cf1cd0395b867edacd3f69ac32737763617d1dbd/chatbot/src/assets/c3_repair.pdf"
