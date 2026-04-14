PIPELINE_NAME := "Docling Ingestion Pipeline"
TOKEN := $(shell oc whoami -t)
KFP := kfp --endpoint https://ds-pipeline-dspa-sandbox.apps.ocp.home.glroland.com --existing-token $(TOKEN)
TIMESTAMP := $(shell date +"%F %T")
AZURE_STORAGE_KEY := ${AZURE_STORAGE_KEY}

install:
	pip install -r requirements.txt

compile:
	cd src/components && $(KFP) dsl compile --py delete_blob.py --output delete_blob.yaml
	cd src/components && $(KFP) dsl compile --py download_blob.py --output download_blob.yaml
	cd src/components && $(KFP) dsl compile --py download_input_file.py --output download_input_file.yaml
	cd src/components && $(KFP) dsl compile --py list_blobs.py --output list_blobs.yaml
	cd src/components && $(KFP) dsl compile --py run_docling_gpu.py --output run_docling_gpu.yaml
	cd src/components && $(KFP) dsl compile --py upload_blob.py --output upload_blob.yaml
	cd src/components && $(KFP) dsl compile --py upload_directory.py --output upload_directory.yaml
	cd src && $(KFP) dsl compile --py basic-pipeline.py --output basic-pipeline.yaml
	cd src && $(KFP) dsl compile --py azure-pipeline.py --output azure-pipeline.yaml

run-basic:
	cd src && $(KFP) run create --package-file basic-pipeline.yaml --experiment-name Default --run-name "$(TIMESTAMP)" "source_document_url=https://raw.githubusercontent.com/glroland/mechanic/cf1cd0395b867edacd3f69ac32737763617d1dbd/chatbot/src/assets/c3_repair.pdf"

run-azure:
	cd src && $(KFP) run create --package-file azure-pipeline.yaml --experiment-name Default --run-name "$(TIMESTAMP)" input_container="input" output_container="output" docling_batch_size=10 storage_account="docling" "storage_key=$(AZURE_STORAGE_KEY)"
