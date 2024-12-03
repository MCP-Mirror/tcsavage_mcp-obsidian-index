from collections.abc import Sequence

import numpy as np
import torch
from sentence_transformers import SentenceTransformer


class Encoder:
    model_minilm_l6_v2: SentenceTransformer

    def __init__(self):
        self.model_minilm_l6_v2 = SentenceTransformer(
            "sentence-transformers/paraphrase-MiniLM-L6-v2",
            device="mps",
        )

    def encode_query(self, query: str) -> torch.Tensor | np.ndarray:
        """
        Encode a query into a vector.
        """
        return self.model_minilm_l6_v2.encode(
            query,
            show_progress_bar=False,
        )

    def encode_documents(
        self, documents: Sequence[str], batch_size: int = 16
    ) -> torch.Tensor | np.ndarray:
        """
        Encode a sequence of documents into a matrix.
        """
        return self.model_minilm_l6_v2.encode(
            list(documents), show_progress_bar=False, batch_size=batch_size
        )
