from kfp import dsl
from kfp.dsl import Input, Output, Artifact, Dataset


@dsl.container_component
def run_docling_step_with_gpu(source_document_path: Input[Artifact],
                              generated_artifacts_path: Output[Dataset],
                              docling_batch_size: int = 4):
    return dsl.ContainerSpec(
        image='quay.io/bball/docling-rapidocr-pipeline:1.0',
        command=['docling'],
        args=[
            '-v',
            '--device', 'cuda',
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
