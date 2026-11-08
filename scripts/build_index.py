# scripts/build_index.py —— 第3步：把知识库向量化并存入FAISS
# 为什么先设镜像：BGE模型要从HuggingFace下载，国内直连常超时，用国内镜像站代替
import os
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

import json
import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

KB_PATH = "data/kb.json"          # 你的知识库
INDEX_PATH = "data/faiss.index"   # 向量索引文件
META_PATH = "data/meta.json"      # 检索结果 → 原始数据的映射表
MODEL_NAME = "BAAI/bge-small-zh-v1.5"

def item_to_text(item: dict) -> str:
    """
    把一条JSON数据拼装成一段自然语言文本。
    为什么不直接把JSON字符串丢进去编码？
    因为用户查询是自然语言（如"血糖高怎么办"），
    把字段织成流畅的中文句子，与查询的语言风格更匹配，检索命中率更高。
    """
    ranges = "；".join(
        f"{r['population']} {r['low']}-{r['high']}"
        for r in item["reference_ranges"]
    )
    parts = [
        f"【{item['name']}】",
        f"英文缩写：{'、'.join(item['abbr'])}。",
    ]
    if item.get("aliases"):
        parts.append(f"又称：{'、'.join(item['aliases'])}。")
    parts += [
        f"归类：{item['category']}。单位：{item['unit']}。",
        f"参考区间：{ranges}。",
        f"升高的临床意义：{item['elevated_meaning']}",
        f"降低的临床意义：{item['decreased_meaning']}",
        f"相关疾病：{'、'.join(item['related_diseases'])}。",
        f"复检建议：{item['recheck_advice']}",
    ]
    if item.get("notes"):
        parts.append(f"注意事项：{item['notes']}")
    return "".join(parts)

def main():
    # 1. 读知识库
    with open(KB_PATH, "r", encoding="utf-8") as f:
        items = json.load(f)
    print(f"读取知识库：{len(items)} 个项目")

    # 2. 每条数据拼装成检索文本
    texts = [item_to_text(it) for it in items]
    print("示例文本（第1条）：")
    print(texts[0][:150], "...\n")

    # 3. 加载BGE模型并编码
    #    选bge-small-zh-v1.5的理由：中文优化、仅约100MB、CPU可跑，
    #    对40-60条规模的知识库检索效果足够好
    print(f"加载模型 {MODEL_NAME}（首次运行会自动下载，请耐心等待）...")
    model = SentenceTransformer(MODEL_NAME)
    embeddings = model.encode(
        texts,
        normalize_embeddings=True,  # 归一化：之后用内积检索等价于余弦相似度，是BGE官方推荐用法
        show_progress_bar=True,
    )
    print(f"编码完成，每个项目变成 {embeddings.shape[1]} 维向量")

    # 4. 存入FAISS（内积索引）
    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(np.array(embeddings, dtype="float32"))
    faiss.write_index(index, INDEX_PATH)
    print(f"向量索引已保存到 {INDEX_PATH}")

    # 5. 保存映射表：FAISS返回的是位置编号，要知道位置i对应哪个检验项目
    meta = [{"id": it["id"], "name": it["name"], "source": it.get("source", ""), "text": texts[i]}
            for i, it in enumerate(items)]
    with open(META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"映射表已保存到 {META_PATH}")
    print("✅ 索引构建完成！")

if __name__ == "__main__":
    main()
