import requests
import json
import time
from pydantic import BaseModel

# Constant for the number of iterations
NUM_ITERATIONS = 10

class ConfigBase(BaseModel):
    MODEL_NAME : str = None
    API_URL : str = None
    API_KEY : str = "token"

class VllmConfig(ConfigBase):
    MODEL_NAME : str = "gpt-oss-20b"
    API_URL : str = "https://gpt-oss-20b-sandbox.apps.ocp.home.glroland.com/v1"

class LlamaStackConfig(ConfigBase):
    MODEL_NAME : str = "vllm-inference/gpt-oss-20b"
    API_URL : str = "https://openai-responses-api-secure-sandbox.apps.ocp.home.glroland.com/v1"

class MyLlamaStackConfig(ConfigBase):
    MODEL_NAME : str = "vllm-inference/vllm-inference/gpt-oss-20b"
    API_URL : str = "https://my-llama-stack-my-llama-stack.apps.ocp.home.glroland.com/v1"

# Setup Config
#CONFIG = VllmConfig()
CONFIG = LlamaStackConfig()
#CONFIG = MyLlamaStackConfig()

# Remote MCP Server configuration via URL
# Note: MCP servers are typically integrated into the tools/functions definition 
# depending on the specific provider's implementation of the responses API.
REMOTE_MCP_NAME = "Baseball-Chatbot-Utilities"
REMOTE_MCP_URL = "https://baseball-chatbot-agent-utilities-baseball-chatbot.apps.ocp.home.glroland.com/mcp"

# Prompt to use for testing
PROMPT_STATIC = "What is the capital of Japan?"
PROMPT_CURRENT_TEMP = f"Using {REMOTE_MCP_NAME}, what is the current temperature in Atlanta?"
PROMPT_SLEEP = f"Using {REMOTE_MCP_NAME}, call the go-to-sleep tool with an input value of 3.  Tell me the result it passes back."
PROMPT = PROMPT_SLEEP

def main():
    headers = {
        "Authorization": f"Bearer {CONFIG.API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": CONFIG.MODEL_NAME,
        "input": PROMPT,
        "tools": [
            {
                "type": "mcp",
                "server_label": REMOTE_MCP_NAME,
                "server_url": REMOTE_MCP_URL,
                "require_approval": "never"
            }
        ]
    }

    print(f"Starting loop for {NUM_ITERATIONS} iterations...")

    for i in range(1, NUM_ITERATIONS + 1):
        start_time = time.time()
        response = requests.post(f"{CONFIG.API_URL}/responses", headers=headers, data=json.dumps(payload))
        end_time = time.time()
        duration = int((end_time - start_time))

        data = response.json()
        last_output = len(data['output'])
        #print (json.dumps(data, indent=4))
        llm_response = data['output'][last_output-1]['content'][0]['text']
        llm_response_length = 0
        if llm_response is not None:
            llm_response_length = len(llm_response)

        # Check for successful response
        if response.status_code != 200:
            raise Exception(
                f"Iteration {i} failed with status code {response.status_code}: {response.text}"
            )

        print(f"Iteration {i}: Success in {duration} seconds.  {llm_response_length} bytes received.  ({llm_response})")

    print("All iterations completed successfully.")

if __name__ == "__main__":
    main()
