"""Actual local Transformers inference; no fallback embeddings or remote code."""
import time
import numpy as np
from utils.c4_rag.retrievers import _embedding_text

def serialise_v0(chunk):
    # Frozen historical MPNet serialization; repeated fields are not repaired in V0.
    return _embedding_text(chunk)

class LocalNeural:
    def __init__(self, root, kind, *, dtype='float32', attention=None):
        import torch
        from transformers import AutoTokenizer, AutoModel, AutoModelForSequenceClassification
        self.torch, self.kind = torch, kind
        self.cap = 384 if kind == 'mpnet' else 512
        torch.set_num_threads(1)
        torch.use_deterministic_algorithms(True)
        self.tokenizer = AutoTokenizer.from_pretrained(str(root), local_files_only=True, trust_remote_code=False)
        model_class = AutoModel if kind == 'mpnet' else AutoModelForSequenceClassification
        options = {'torch_dtype': getattr(torch, dtype)}
        if attention is not None:
            options['attn_implementation'] = attention
        self.model = model_class.from_pretrained(str(root), local_files_only=True,
                         trust_remote_code=False, use_safetensors=True, **options).cpu().eval()
        self.audit = []

    def lengths(self, text, query=None):
        tok = self.tokenizer
        full = tok(text if query is None else query, text_pair=None if query is None else text,
                   add_special_tokens=True, truncation=False)['input_ids']
        qlen = len(tok(query, add_special_tokens=False)['input_ids']) if query is not None else 0
        if query is not None and qlen > 64:
            raise ValueError('QUERY_OVER_64_TOKENS_REQUIRES_SEPARATE_FACTOR')
        return {'untruncated_tokens': len(full), 'model_tokens': min(len(full), self.cap),
                'query_tokens': qlen, 'truncated_tokens': max(0, len(full)-self.cap)}

    def encode(self, texts, ids):
        if self.kind != 'mpnet':
            raise ValueError('Cross encoder is not an embedding model')
        rows = []
        for start in range(0, len(texts), 4):
            batch = texts[start:start+4]
            self.audit.extend({'id': ident, **self.lengths(t)} for ident, t in zip(ids[start:start+4], batch))
            data = self.tokenizer(batch, padding=True, truncation=True, max_length=self.cap, return_tensors='pt')
            with self.torch.inference_mode():
                hidden = self.model(**data).last_hidden_state
                mask = data['attention_mask'].unsqueeze(-1).float()
                pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
                pooled = self.torch.nn.functional.normalize(pooled, p=2, dim=1)
            rows.append(pooled.cpu().numpy().astype('float32'))
        return np.concatenate(rows) if rows else np.zeros((0, 768), dtype='float32')

    def score_pairs(self, query, passages, ids):
        if self.kind != 'cross_encoder':
            raise ValueError('MPNet is not a pair reranker')
        scores = []
        for start in range(0, len(passages), 4):
            batch = passages[start:start+4]
            self.audit.extend({'id': ident, **self.lengths(t, query)} for ident, t in zip(ids[start:start+4], batch))
            data = self.tokenizer([query]*len(batch), batch, padding=True, truncation='only_second',
                                  max_length=self.cap, return_tensors='pt')
            with self.torch.inference_mode():
                scores.extend(self.model(**data).logits.reshape(-1).tolist())
        return dict(zip(ids, scores))
