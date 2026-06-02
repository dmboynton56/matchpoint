from openai import OpenAI
from dotenv import load_dotenv
import os

load_dotenv()


api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise RuntimeError("OPENAI_API_KEY is not set")

OPENAI_TIMEOUT_SECONDS = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30"))
OPENAI_MAX_RETRIES = int(os.getenv("OPENAI_MAX_RETRIES", "1"))

client = OpenAI(
    api_key=api_key,
    timeout=OPENAI_TIMEOUT_SECONDS,
    max_retries=OPENAI_MAX_RETRIES,
)


def generateEmbedding(text: str):
    text = text.strip()
    if not text:
        raise ValueError("Input text for embedding cannot be empty")
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=text,
    )
    response_data = getattr(response, "data", None)
    if not response_data:
        raise RuntimeError("OpenAI embedding response returned no data")

    return response_data[0].embedding
