import json
import os
from datetime import datetime

import httpx
import uvicorn
from cloudevents.conversion import to_structured
from cloudevents.http import CloudEvent, from_http
from fastapi import FastAPI, Request, Response

# Output channel URL — update this to match your cluster/namespace
OUTPUT_CHANNEL_URL = "http://hello-world-output.sandbox.svc.cluster.local"

app = FastAPI()


@app.post("/")
async def handle_event(request: Request) -> Response:
    # Parse CloudEvent from the incoming HTTP request
    body = await request.body()
    event = from_http(request.headers, body)

    # 1. Print message contents
    data = event.data
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            pass
    print(f"[CloudEvent received] id={event['id']} type={event['type']} source={event['source']}")
    print(f"[Message contents] {data}")

    # 2. Build hello world statement
    current_time = datetime.now().isoformat()
    hello_world = f"Hello World! Time: {current_time} | Message: {data}"
    print(f"[Hello World] {hello_world}")

    # 3. Publish hello world statement to output channel
    output_event = CloudEvent(
        {
            "type": "com.docling.helloworld",
            "source": "hello-world-function",
        },
        hello_world,
    )
    headers, body = to_structured(output_event)
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(OUTPUT_CHANNEL_URL, headers=headers, content=body, timeout=10)
        print(f"[Published] status={resp.status_code} channel={OUTPUT_CHANNEL_URL}")
    except httpx.RequestError as exc:
        print(f"[Publish failed] {exc}")

    return Response(status_code=200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
