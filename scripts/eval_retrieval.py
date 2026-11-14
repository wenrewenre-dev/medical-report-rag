# scripts/eval_retrieval.py —— 检索回归测试集
# 铁律：kb.json每新增一个项目，这里同步加一条测试（数据与测试成对维护）
#
# 用法：
#   python scripts/eval_retrieval.py                      # 三路检索基线（vector/bm25/hybrid）
#   python scripts/eval_retrieval.py --limit 5            # 只跑前5条，快速冒烟
#   python scripts/eval_retrieval.py --strategies off,rewrite,hyde,both
#                                                         # 查询改写/HyDE 对比（每题多花1-2次LLM调用）
import argparse

import query_rewrite
from kb import KB

# (查询, 期望Top1的id, 考察点)
CASES = [
    ("血糖偏高说明什么", 6, "口语化提问"),
    ("空腹血糖6.8严重吗", 6, "带数值提问"),
    ("ALT升高常见于哪些疾病", 7, "英文缩写"),
    ("最近总觉得没力气，是不是贫血", 1, "纯症状→语义理解"),
    ("HGB 90g/L要紧吗", 1, "缩写+数值"),
    ("甘油三酯高怎么办", 10, "项目全名"),
    ("三酰甘油结果异常", 10, "别名匹配"),
    ("血钾低会有什么症状", 4, "口语化"),
    ("白细胞低是不是免疫力很差", 2, "诱导性问法"),
    ("转氨酶高是肝炎吗", 7, "俗称匹配"),
    ("总胆固醇高怎么降下来", 9, "口语化·消歧后"),
    ("低密度脂蛋白胆固醇偏高要紧吗", 26, "LDL消歧"),
    ("肌酐高代表肾不好吗", 8, "机制类提问"),
    ("血小板减少会不会出血", 3, "机制类提问"),
    ("尿酸高是怎么回事", 16, "尿酸·扩库"),
    ("平均血红蛋白量偏低什么意思", 12, "MCH·扩库"),
    ("平均血红蛋白浓度偏低什么意思", 13, "MCHC·扩库"),
    ("血钠高说明什么", 5, "标准问法"),
]
# 扩库后为每个新项目追加（id以你实际编排为准），例如：
# ("尿酸高是怎么回事", 11, "扩库新增"),
# ("平均血红蛋白浓度偏低什么意思", 13, "扩库新增·解析修复配套"),
# ("糖化血红蛋白8.5%严重吗", 26, "扩库新增"),

KS = (1, 3, 5, 10)


def evaluate(kb, mode="hybrid", queries_fn=None, limit=0):
    """返回 (各@k命中数, MRR, Top1未命中的用例)。
    queries_fn: 问题 → 查询列表（改写策略）；None 表示只用原问题。"""
    cases = CASES[:limit] if limit else CASES
    hits = {k: 0 for k in KS}
    rr, fails = 0.0, []
    for q, expect, note in cases:
        queries = queries_fn(q) if queries_fn else [q]
        if len(queries) > 1:
            ranked = kb.search_many(queries, k=max(KS), mode=mode)
        else:
            ranked = kb.search(q, k=max(KS), mode=mode)
        ids = [r["id"] for r in ranked]
        for k in KS:
            if expect in ids[:k]:
                hits[k] += 1
        if expect in ids:
            rr += 1.0 / (ids.index(expect) + 1)
        if expect not in ids[:1]:
            fails.append((q, expect, ids[0] if ids else None,
                          ranked[0]["name"] if ranked else "", note))
    return hits, rr / len(cases), fails


def print_row(label, hits, mrr, n):
    cells = "  ".join(f"HIT@{k}={hits[k]:>2d}/{n}" for k in KS)
    print(f"{label:<18} {cells}   MRR={mrr:.3f}")


def main():
    ap = argparse.ArgumentParser(description="检索质量评测")
    ap.add_argument("--strategies", default="",
                    help="逗号分隔: off,rewrite,hyde,both（给了就做改写对比）")
    ap.add_argument("--mode", default="hybrid", choices=["vector", "bm25", "hybrid"],
                    help="对比改写时用哪条检索路径，默认 hybrid")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条，快速冒烟")
    args = ap.parse_args()

    kb = KB()
    n = args.limit or len(CASES)
    print(f"\n回归测试集：{len(CASES)} 条" + (f"（本次只跑前 {n} 条）" if args.limit else ""))
    print("=" * 86)

    if not args.strategies:
        for mode in ("vector", "bm25", "hybrid"):
            hits, mrr, fails = evaluate(kb, mode=mode, limit=args.limit)
            print_row(mode, hits, mrr, n)
            for q, expect, got, name, note in fails:
                print(f"    ✗ {q}（{note}）期望[资料{expect}]，实际Top1[资料{got}]{name}")
        print("\n加 --strategies off,rewrite,hyde,both 可对比查询改写/HyDE（每题会多花1-2次LLM调用）")
        return

    client = query_rewrite.make_client()
    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]
    print(f"检索路径: {args.mode}（每题用 LLM 生成改写，首次运行较慢）\n")
    for strategy in strategies:
        if strategy == "off":
            fn = None
        else:
            fn = lambda q, s=strategy: query_rewrite.build_queries(q, client, s)
        hits, mrr, fails = evaluate(kb, mode=args.mode, queries_fn=fn, limit=args.limit)
        print_row(f"{args.mode}+{strategy}", hits, mrr, n)
        for q, expect, got, name, note in fails:
            print(f"    ✗ {q}（{note}）期望[资料{expect}]，实际Top1[资料{got}]{name}")
        print()


if __name__ == "__main__":
    main()
