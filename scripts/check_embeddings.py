"""List models available to this API key; probe the configured dimension."""

import os

from dotenv import load_dotenv
from google import genai
from google.genai import types


def main():
    load_dotenv()
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    available = []
    for model in client.models.list():
        if "embedContent" in (model.supported_actions or []):
            available.append(model.name)
            print(model.name)
    model = os.getenv("EMBEDDING_MODEL")
    if model:
        if model not in available and "models/" + model not in available:
            raise SystemExit(
                "Configured EMBEDDING_MODEL is not available to this API key"
            )
        dim = int(os.getenv("EMBEDDING_DIM", "768"))
        result = client.models.embed_content(
            model=model,
            contents="robotics",
            config=types.EmbedContentConfig(output_dimensionality=dim),
        )
        actual = len(result.embeddings[0].values)
        print(f"Configured dimension: {dim}; returned dimension: {actual}")
        if actual != dim:
            raise SystemExit(
                "Embedding dimension mismatch; do not create the vector index"
            )


if __name__ == "__main__":
    main()
