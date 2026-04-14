from kfp import compiler, dsl

from components import download_input_file_step, run_docling_step_with_gpu

PIPELINE_NAME = "Docling Ingestion Pipeline"


@dsl.pipeline(name=PIPELINE_NAME)
def simple_dsl_pipeline(source_document_url: str,
                        docling_batch_size: str = "10"):
    # Step 1: Download the source document from URL
    download_task = download_input_file_step(source_document_url=source_document_url)

    # Step 2: Run Docling with GPU acceleration
    run_docling_w_gpu_task = run_docling_step_with_gpu(
        source_document_path=download_task.output,
        docling_batch_size=docling_batch_size,
    )
    run_docling_w_gpu_task.set_cpu_limit('10')
    run_docling_w_gpu_task.add_node_selector_constraint('nvidia.com/gpu')
    run_docling_w_gpu_task.set_accelerator_type('nvidia.com/gpu')
    run_docling_w_gpu_task.set_accelerator_limit(1)
