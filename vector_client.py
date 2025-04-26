import os
from pinecone import Pinecone, ServerlessSpec
from openai import OpenAI

# Load API keys
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Initialize Pinecone
pc = Pinecone(api_key=PINECONE_API_KEY)
INDEX_NAME = "mano-pitches"
index = pc.Index(INDEX_NAME, region="us-east-1")

# Initialize OpenAI
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# --- Embedding helper ---
def get_embedding(text: str) -> list:
    """Generate embedding for a text string"""
    try:
        response = openai_client.embeddings.create(
            model="text-embedding-ada-002",
            input=text
        )
        return response.data[0].embedding
    except Exception as e:
        print(f"❌ Error generating embedding: {e}")
        return None

import uuid

def store_vector(vector_data: dict):
    try:
        text = vector_data["text"]
        metadata = vector_data.get("metadata", {})
        vector_id = vector_data.get("id", str(uuid.uuid4()))  # ✅ if no id, generate one
        
        embedding = get_embedding(text)
        if embedding is None:
            raise ValueError("Embedding generation failed.")
        
        index.upsert([(vector_id, embedding, metadata)])
        print(f"✅ Stored vector {vector_id}")
    except Exception as e:
        print(f"❌ Error storing vector: {e}")


# --- Search vectors ---
def search_vectors(query_text: str, filter_criteria=None, limit=5):
    try:
        embedding = get_embedding(query_text)
        if embedding is None:
            raise ValueError("Embedding generation failed for search.")

        result = index.query(
            vector=embedding,
            top_k=limit,
            include_metadata=True,
            filter=filter_criteria or {}
        )
        return result.matches
    except Exception as e:
        print(f"❌ Error searching vectors: {e}")
        return []
