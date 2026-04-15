"""
Integration test: send a CloudEvent to the deployed docling-process Knative service.

Configuration via environment variables:
  CLUSTER_URL        Full service URL (e.g. https://docling-process-sandbox.apps.mycluster.example.com)
                     If set, OPENSHIFT_CLUSTER is ignored.
  OPENSHIFT_CLUSTER  Base apps domain (e.g. apps.mycluster.example.com). The service URL is
                     constructed as https://<kservice-name>-<namespace>.<OPENSHIFT_CLUSTER>.
  KSERVICE_NAME      Knative service name (default: docling-process)
  NAMESPACE          OpenShift namespace (default: sandbox)

Event payload schema:
  {
    "input":  { "container": "<azure-container>", "path": "<blob-path-to-file>" },
    "output": { "container": "<azure-container>", "path": "<blob-prefix-for-output>" }
  }
"""

import os
import uuid

import httpx
import pytest
from cloudevents.v1.conversion import to_structured
from cloudevents.v1.http import CloudEvent

KSERVICE_NAME = os.environ.get("KSERVICE_NAME", "docling-process")
NAMESPACE = os.environ.get("NAMESPACE", "sandbox")


def get_service_url() -> str:
    """Resolve the service URL from environment variables."""
    cluster_url = os.environ.get("CLUSTER_URL")
    if cluster_url:
        return cluster_url.rstrip("/")

    openshift_cluster = os.environ.get("OPENSHIFT_CLUSTER")
    if openshift_cluster:
        return f"https://{KSERVICE_NAME}-{NAMESPACE}.{openshift_cluster.lstrip('.')}"

    pytest.skip(
        "No cluster address provided. Set CLUSTER_URL or OPENSHIFT_CLUSTER env var."
    )


@pytest.fixture(scope="session")
def service_url() -> str:
    return get_service_url()


def build_cloud_event(
    input_container: str = "docling-input",
    input_path: str = "documents/sample.pdf",
    output_container: str = "docling-output",
    output_path: str = "processed/sample/",
) -> tuple[dict, bytes]:
    """Build a structured CloudEvent with an Azure Blob Storage input/output payload."""
    data = {
        "input": {
            "container": input_container,
            "path": input_path,
        },
        "output": {
            "container": output_container,
            "path": output_path,
        },
    }
    event = CloudEvent(
        {
            "type": "com.docling.document.ingest",
            "source": "integration-test",
            "id": str(uuid.uuid4()),
        },
        data,
    )
    return to_structured(event)


class TestSendCloudEvent:
    def test_send_document_ingest_event(self, service_url: str):
        """Send a document ingest CloudEvent with blob references and assert HTTP 200."""
        headers, body = build_cloud_event()

        with httpx.Client(verify=False, timeout=30) as client:
            response = client.post(service_url, headers=headers, content=body)

        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}. Body: {response.text}"
        )

    def test_send_event_with_custom_paths(self, service_url: str):
        """Send a CloudEvent with custom container and path values."""
        headers, body = build_cloud_event(
            input_container="raw-docs",
            input_path=f"uploads/{uuid.uuid4()}/report.pdf",
            output_container="processed-docs",
            output_path=f"results/{uuid.uuid4()}/",
        )

        with httpx.Client(verify=False, timeout=30) as client:
            response = client.post(service_url, headers=headers, content=body)

        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}. Body: {response.text}"
        )

    def test_send_multiple_events(self, service_url: str):
        """Send several events in sequence and assert each returns 200."""
        for i in range(3):
            doc_id = str(uuid.uuid4())
            headers, body = build_cloud_event(
                input_path=f"documents/batch/{doc_id}.pdf",
                output_path=f"processed/batch/{doc_id}/",
            )
            with httpx.Client(verify=False, timeout=30) as client:
                response = client.post(service_url, headers=headers, content=body)
            assert response.status_code == 200, (
                f"Event {i} failed with status {response.status_code}. Body: {response.text}"
            )

    def test_send_invalid_payload_returns_400(self, service_url: str):
        """Send a CloudEvent with a missing 'output' field and assert HTTP 400."""
        event = CloudEvent(
            {
                "type": "com.docling.document.ingest",
                "source": "integration-test",
                "id": str(uuid.uuid4()),
            },
            {"input": {"container": "my-container", "path": "docs/file.pdf"}},
        )
        headers, body = to_structured(event)

        with httpx.Client(verify=False, timeout=30) as client:
            response = client.post(service_url, headers=headers, content=body)

        assert response.status_code == 400, (
            f"Expected 400, got {response.status_code}. Body: {response.text}"
        )
