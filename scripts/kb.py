# scripts/kb.py —— 共享检索模块（第6步升级：向量 + BM25 + RRF混合检索）
import os
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

import json
import faiss
import jieba
import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

MODEL_NAME = "BAAI/bge-small-zh-v1.5"
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："
RRF_K = 60  # RRF平滑常数，业界标准值
W_VECTOR = 1.0 # 语义路权重：数据变强后，语义检索是主力
W_BM25 = 0.5   # 关键词路权重：降权保留其救场能力（缩写查询），抑制其短文档噪声

jieba.setLogLevel(60)  # 静音jieba首次运行时"Building prefix dict"日志


class KB:
    """检索三件套：FAISS向量索引 + BM25关键词索引 + 元数据"""

    def __init__(self, index_path="data/faiss.index", meta_path="data/meta.json"):
        self.index = faiss.read_index(index_path)
        with open(meta_path, "r", encoding="utf-8") as f:
            self.meta = json.load(f)
        print("加载BGE模型...")
        self.model = SentenceTransformer(MODEL_NAME)
        # BM25语料 = 每条知识的检索文本；统一小写，保证"HGB"和查询"hgb"能对上
        print("构建BM25关键词索引...")
        tokenized = [list(jieba.cut(m["text"].lower())) for m in self.meta]
        self.bm25 = BM25Okapi(tokenized)

    def _make(self, pos, score):
        m = self.meta[pos]
        return {"id": m["id"], "name": m["name"], "source": m.get("source", ""),
                "text": m["text"], "score": float(score)}

    def _vector(self, query, k):
        vec = self.model.encode([QUERY_PREFIX + query], normalize_embeddings=True)
        scores, pos = self.index.search(np.array(vec, dtype="float32"), k)
        return [(int(p), float(s)) for p, s in zip(pos[0], scores[0])]

    def _bm25(self, query, k):
        tokens = [t for t in jieba.cut(query.lower()) if t.strip()]
        scores = self.bm25.get_scores(tokens)
        order = np.argsort(scores)[::-1]
        return [(int(i), float(scores[i])) for i in order[:k] if scores[i] > 0]

    def search(self, query: str, k: int = 3, mode: str = "hybrid"):
        """
        mode: "vector" 纯语义 | "bm25" 纯关键词 | "hybrid" 双路召回+RRF融合（默认）
        """
        if mode == "vector":
            return [self._make(p, s) for p, s in self._vector(query, k)]
        if mode == "bm25":
            return [self._make(p, s) for p, s in self._bm25(query, k)]
        # hybrid：两路各取较多候选，按"排名倒数求和"融合
        n = max(k * 3, 10)
        rrf = {}
        for rank, (p, _) in enumerate(self._vector(query, n)):
            rrf[p] = rrf.get(p, 0.0) + W_VECTOR * 1.0 / (RRF_K + rank + 1)
        for rank, (p, _) in enumerate(self._bm25(query, n)):
            rrf[p] = rrf.get(p, 0.0) + W_BM25 * 1.0 / (RRF_K + rank + 1)
        ranked = sorted(rrf.items(), key=lambda x: -x[1])[:k]
        return [self._make(p, s) for p, s in ranked]
