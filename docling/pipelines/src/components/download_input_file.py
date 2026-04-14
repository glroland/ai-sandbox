from kfp import dsl
from kfp.dsl import Output, Artifact


@dsl.component
def download_input_file_step(source_document_url: str, source_document_path: Output[Artifact]):
    print("Downloading Input File...")
    print("URL: " + str(source_document_url))
    print("To: " + str(source_document_path.path))

    import urllib.request
    urllib.request.urlretrieve(source_document_url, source_document_path.path)

    print("Source Document Downloaded!")
