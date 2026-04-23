import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

print("HF token loaded:", bool(os.getenv("HF_TOKEN")))
print("HF token prefix:", (os.getenv("HF_TOKEN") or "")[:5])

client = OpenAI(
    base_url="https://router.huggingface.co/v1",
    api_key=os.getenv("HF_TOKEN"),
)

resp = client.chat.completions.create(
    model="deepseek-ai/DeepSeek-R1:fastest",
    messages=[{"role": "user", "content": "Say hello in one short sentence."}],
)

print(resp.choices[0].message.content)