# scripts/search_test.py —— 用几个真实问法测试检索是否命中
import os
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["HF_HUB_OFFLINE"] = "1"        # 模型已缓存，强制离线，跳过联网校验
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import json
import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

MODEL_NAME = "BAAI/bge-small-zh-v1.5"

def load():
    index = faiss.read_index("data/faiss.index")
    with open("data/meta.json", "r", encoding="utf-8") as f:
        meta = json.load(f)
    model = SentenceTransformer(MODEL_NAME)
    return index, meta, model

def search(query: str, index, meta, model, k=3):
    # BGE官方技巧：查询前加这个前缀，检索精度更高（ passage 侧不需要加）
    q = "为这个句子生成表示以用于检索相关文章：" + query
    vec = model.encode([q], normalize_embeddings=True)
    scores, positions = index.search(np.array(vec, dtype="float32"), k)
    print(f"\n🔍 查询：{query}")
    for rank, (pos, score) in enumerate(zip(positions[0], scores[0]), 1):
        m = meta[pos]
        print(f"  Top{rank} [资料{m['id']}] {m['name']}  (相似度 {score:.3f})")

if __name__ == "__main__":
    index, meta, model = load()
       # 测试query：覆盖"口语化问法"、"缩写"、"症状描述"三种典型场景 + 新批次的对抗性验证
    for q in [
        "血糖偏高说明什么",
        "ALT升高常见于哪些疾病",
        "最近总觉得没力气，是不是贫血",
        "AST 谷草转氨酶升高是什么原因",
        "转氨酶偏高需要复查什么",
        "D-二聚体阳性是不是血栓",
        "APTT 延长但 PT 正常",
        "吃达格列净尿糖4+正常吗",
        "体检说贫血是缺铁吗",
    ]:
        search(q, index, meta, model)
