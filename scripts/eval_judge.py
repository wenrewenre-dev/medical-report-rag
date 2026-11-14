# scripts/eval_judge.py —— 用 LLM 裁判自动评测回答质量
#
# 两种跑法：
#   python scripts/eval_judge.py --limit 5        # 快速冒烟
#   python scripts/eval_judge.py                  # 18 条回归集全跑（每条 1 次回答 + 1 次裁判）
#   python scripts/eval_judge.py --calibrate      # 追加标定：把好答案改坏，看裁判抓不抓得住
#
# 评测走的是真实链路：直接驱动 app.qa_fn，和界面上点"提问"得到的是同一条管线。
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import judge
from eval_retrieval import CASES


def run_answer(app_mod, question: str) -> str:
    """驱动真实问答管线，取最终回答"""
    frames = list(app_mod.qa_fn(question, [], False))
    return frames[-1][1][-1]["content"]


def mutate(answer: str, kind: str) -> str:
    """把一份合格回答改坏，模拟三种典型缺陷"""
    if kind == "fake_citation":
        return judge.CITATION_RE.sub("[资料99]", answer, count=1) if "[资料" in answer \
            else answer + "\n\n[资料99] 也支持上述判断。"
    if kind == "unsupported":
        return answer + "\n\n另外建议每天大剂量服用维生素C 1000mg 来改善贫血。"
    if kind == "fabricated_number":
        return answer + "\n\n成年男性血红蛋白参考范围是 100-110 g/L。"
    raise ValueError(kind)


def main():
    ap = argparse.ArgumentParser(description="LLM-as-a-Judge 回答评测")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条")
    ap.add_argument("--calibrate", action="store_true", help="追加注入缺陷的标定")
    ap.add_argument("--cal-limit", type=int, default=6, help="标定使用前 N 条")
    args = ap.parse_args()

    import app  # 重：加载检索模块 + 构建界面（评测走真实管线）

    kb, client = app.kb, app.client
    cases = CASES[:args.limit] if args.limit else CASES

    print(f"\n【参考回答】{len(cases)} 条（真实管线 → 裁判）")
    print("=" * 78)
    passed, agree, errors, results = 0, 0, 0, []
    for i, (q, expect, note) in enumerate(cases, 1):
        answer = run_answer(app, q)
        sources = kb.search(q, k=3)
        v = judge.judge_answer(q, answer, sources, client)
        if v.get("error"):
            errors += 1
            print(f"{i:>2}. ✗ 裁判解析失败：{v['error']} | 原始输出: {v.get('raw', '')[:80]}")
            continue
        passed += v["pass"]
        agree += v["citation_agree"]
        results.append((q, answer, sources, v))
        mark = "✅" if v["pass"] else "❌"
        extra = f"引用{v['cited']} 支持度={v['supported']}"
        if v["bad_citations_rule"]:
            extra += f" 越界引用{v['bad_citations_rule']}"
        print(f"{i:>2}. {mark} {q[:22]:<24} {extra}")
        if not v["pass"]:
            print(f"     判词: {v['reason']} | 无依据: {v['unsupported_claims'][:2]} "
                  f"| 编造数字: {v['fabricated_numbers'][:2]}")

    n = len(results)
    print("-" * 78)
    print(f"通过 {passed}/{n}" + (f"（裁判解析失败 {errors} 条）" if errors else ""))
    print(f"引用项与机器复核一致 {agree}/{n}")

    if not args.calibrate:
        print("\n加 --calibrate 可做标定：把合格回答改坏，验证裁判抓不抓得住")
        return

    print(f"\n【注入缺陷标定】取前 {args.cal_limit} 条合格回答，各改坏 3 种")
    print("=" * 78)
    kinds = [("fake_citation", "假引用"), ("unsupported", "无依据结论"), ("fabricated_number", "编造数字")]
    tally = {k: [0, 0] for k, _ in kinds}   # [抓住, 总数]
    for q, answer, sources, v in results[:args.cal_limit]:
        for kind, label in kinds:
            bad = mutate(answer, kind)
            bv = judge.judge_answer(q, bad, sources, client)
            caught = bv.get("pass") is False
            tally[kind][0] += 1 if caught else 0
            tally[kind][1] += 1
            if not caught:
                print(f"  ⚠️ 漏判 {label}：{q[:20]} | 裁判理由: {bv.get('reason')}")

    for kind, label in kinds:
        caught, total = tally[kind]
        print(f"  {label:<8} 判不合格 {caught}/{total}")

    total_caught = sum(v[0] for v in tally.values())
    total_all = sum(v[1] for v in tally.values())
    print(f"\n合计：{total_caught}/{total_all} 注入缺陷被判不合格"
          f"（与人工标注的一致率 {total_caught / total_all:.0%}）" if total_all else "")


if __name__ == "__main__":
    main()
