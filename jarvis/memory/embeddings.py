"""Optional Gemini embeddings. Empty model disables outbound embedding requests."""

import math
from typing import Protocol


class Embedder(Protocol):
    def embed(
        self, text: str, query: bool = False, timeout: float = 3.0
    ) -> list[float]: ...


class GeminiEmbedder:
    def __init__(self, config, api_key):
        from google import genai

        self.client = genai.Client(api_key=api_key)
        self.model = config.embedding_model
        self.dim = config.embedding_dim

    def embed(self, text, query=False, timeout=3.0):
        from google.genai import types

        response = self.client.models.embed_content(
            model=self.model,
            contents=text,
            config=types.EmbedContentConfig(
                output_dimensionality=self.dim,
                task_type="RETRIEVAL_QUERY" if query else "RETRIEVAL_DOCUMENT",
                http_options=types.HttpOptions(
                    timeout=max(1, int(timeout * 1000)),
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            ),
        )
        vector = response.embeddings[0].values
        if len(vector) != self.dim or not all(math.isfinite(x) for x in vector):
            raise ValueError(
                "Embedding dimension or values do not match configured index"
            )
        norm = math.sqrt(sum(x * x for x in vector))
        if not norm:
            raise ValueError("Zero embedding")
        return [x / norm for x in vector]
