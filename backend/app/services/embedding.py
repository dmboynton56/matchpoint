from openai import OpenAI
from dotenv import load_dotenv
import os

load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise RuntimeError("OPENAI_API_KEY is not set")

client = OpenAI(
    api_key=api_key, 
    timeout=30, 
    max_retries=3
)

EMBEDDING_MODEL = "text-embedding-3-small"

def generateEmbedding(text: str):
    text = text.strip()
    if not text:
        raise ValueError("Input text for embedding cannot be empty")
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text
    )
    if not response.data:
        raise RuntimeError("OpenAI embedding response returned no data")
    
    return response.data[0].embedding

# Generates embeddings in batches which is cheaper than running them individually
# Achieves the same result as the original above
def generate_embeddings_batch(texts: list[str]) -> list[list[float]]:
    texts = [t.strip() for t in texts]
    if not all(texts):
        raise ValueError("One or more texts for batch embedding are empty")

    response = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)

    if not response.data:
        raise RuntimeError("OpenAI batch embedding response returned no data")

    return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]
