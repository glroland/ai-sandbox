from kfp import compiler, dsl, components

PIPELINE_NAME = "Azure Docling Ingestion Pipeline"

list_blobs_op = components.load_component_from_file('components/list_blobs.yaml')
download_blob_op = components.load_component_from_file('components/download_blob.yaml')
run_docling_step_with_gpu = components.load_component_from_file('components/run_docling_gpu.yaml')
run_docling_step_with_cpu = components.load_component_from_file('components/run_docling_cpu.yaml')
upload_blob_op = components.load_component_from_file('components/upload_blob.yaml')
upload_directory_op = components.load_component_from_file('components/upload_directory.yaml')
delete_blob_op = components.load_component_from_file('components/delete_blob.yaml')
download_input_file_step = components.load_component_from_file('components/download_input_file.yaml')
detect_scanned_pdf_op = components.load_component_from_file('components/detect_scanned_pdf.yaml')

@dsl.pipeline(name=PIPELINE_NAME)
def azure_docling_pipeline(
    input_container: str,
    output_container: str,
    docling_batch_size: str = "10",
    storage_account: str = "",
    storage_key: str = "",
):
    """
    For each blob in *input_container*:
      1. Download the blob.
      2. Detect whether the PDF is a scanned document.
      3. Run Docling (GPU if scanned, CPU otherwise) to convert it.
      4. Upload the original file to *output_container*.
      5. Upload all Docling output files to *output_container* under the same prefix.
      6. Delete the original blob from *input_container*.
    """
    
    # List all blobs in the input container
    list_task = list_blobs_op(
        container_name=input_container,
        storage_account=storage_account,
        storage_key=storage_key,
    )
    list_task.set_caching_options(enable_caching=False)

    # Process each blob in parallel
    with dsl.ParallelFor(items=list_task.output, parallelism=1) as blob_name:

        # Step 1: Download blob from input container
        download_task = download_blob_op(
            container_name=input_container,
            blob_name=blob_name,
            storage_account=storage_account,
            storage_key=storage_key,
        )
        download_task.set_caching_options(enable_caching=True)

        # Step 2: Detect whether the PDF is a scanned document
        detect_task = detect_scanned_pdf_op(
            input_file=download_task.outputs["output_file"],
        )
        detect_task.set_caching_options(enable_caching=True)

        # Step 3: Run Docling — GPU if scanned, CPU otherwise
        with dsl.If(detect_task.output == True):
            gpu_task = run_docling_step_with_gpu(
                source_document_path=download_task.outputs["output_file"],
                docling_batch_size=docling_batch_size,
            )
            gpu_task.set_cpu_limit('10')
            gpu_task.add_node_selector_constraint('nvidia.com/gpu')
            gpu_task.set_accelerator_type('nvidia.com/gpu')
            gpu_task.set_accelerator_limit(1)
            gpu_task.set_caching_options(enable_caching=True)

        with dsl.Else():
            cpu_task = run_docling_step_with_cpu(
                source_document_path=download_task.outputs["output_file"],
                docling_batch_size=docling_batch_size,
            )
            cpu_task.set_cpu_limit('10')
            cpu_task.set_caching_options(enable_caching=True)

        docling_artifacts = dsl.OneOf(
            gpu_task.outputs["generated_artifacts_path"],
            cpu_task.outputs["generated_artifacts_path"],
        )

        # Step 4: Upload the original file to the output container
        upload_original_task = upload_blob_op(
            container_name=output_container,
            blob_name=blob_name,
            input_file=download_task.outputs["output_file"],
            storage_account=storage_account,
            storage_key=storage_key,
        )
        upload_original_task.set_caching_options(enable_caching=True)

        # Step 5: Upload all Docling output files to the output container
        upload_docling_task = upload_directory_op(
            container_name=output_container,
            blob_prefix=blob_name,
            input_dir=docling_artifacts,
            storage_account=storage_account,
            storage_key=storage_key,
        )
        upload_docling_task.set_caching_options(enable_caching=True)

        # Step 6: Delete the original blob from the input container (after both uploads)
        delete_task = delete_blob_op(
            container_name=input_container,
            blob_name=blob_name,
            storage_account=storage_account,
            storage_key=storage_key,
        )
        #delete_task.after(upload_original_task, upload_docling_task)
        delete_task.set_caching_options(enable_caching=True)
