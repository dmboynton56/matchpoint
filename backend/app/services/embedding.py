from openai import OpenAI
from dotenv import load_dotenv
import os

load_dotenv()


api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise RuntimeError("OPENAI_API_KEY is not set")

client = OpenAI(
    api_key = api_key,
    timeout = 30,
    max_retries = 3
)
def generateEmbedding(text: str):
    text = text.strip()
    if not text:
        raise ValueError("Input text for embedding cannot be empty")
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    if not response.data:
        raise RuntimeError("OpenAI embedding response returned no data")
    
    return response.data[0].embedding