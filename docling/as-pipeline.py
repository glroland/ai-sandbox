import subprocess
import kfp
import kfp.client
from kfp.dsl import Input, Output, Artifact, Dataset
from kfp import compiler, dsl

PIPELINE_NAME = "Docling Ingestion Pipeline"

@dsl.component
def download_input_file_step(source_document_url: str, source_document_path: Output[Artifact]):
    print ("Downloading Input File...")
    print ("URL: " + str(source_document_url))
    print ("To: " + str(source_document_path.path))

    # download file
    import urllib.request
    urllib.request.urlretrieve(source_document_url, source_document_path.path)

    print ("Source Document Downloaded!")


@dsl.container_component
def run_docling_step_with_gpu(source_document_path: Input[Artifact],
                              generated_artifacts_path: Output[Dataset],
                              docling_batch_size: int = 4):
    return dsl.ContainerSpec(
        image='quay.io/bball/docling-rapidocr-pipeline:1.0',
        command=['docling'],
        args=[
            '-v',
            '--device', 'cuda',  #'cuda', 'cpu'
            '--from', 'pdf',
            '--to', 'md',
            '--image-export-mode', 'referenced',
            '--ocr',
            '--ocr-engine', 'rapidocr', 
            '--page-batch-size', str(docling_batch_size),
            '--output', generated_artifacts_path.path,
            source_document_path.path
        ]
    )


@dsl.pipeline(name=PIPELINE_NAME)
def simple_dsl_pipeline(source_document_url: str,
                        docling_batch_size: int = 10):
    # Step 1
    download_task = download_input_file_step(source_document_url = source_document_url)

    # Step 2
    run_docling_w_gpu_task = run_docling_step_with_gpu(source_document_path = download_task.output)
    run_docling_w_gpu_task.set_cpu_limit('10')   # 20
    run_docling_w_gpu_task.add_node_selector_constraint('nvidia.com/gpu')
    run_docling_w_gpu_task.set_accelerator_type('nvidia.com/gpu')
    run_docling_w_gpu_task.set_accelerator_limit(1)
    
    #feature.node.kubernetes.io/cpu-cpuid.AVX2: 'true'
