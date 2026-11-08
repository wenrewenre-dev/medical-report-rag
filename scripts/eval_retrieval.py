# scripts/eval_retrieval.py —— 检索回归测试集
# 铁律：kb.json每新增一个项目，这里同步加一条测试（数据与测试成对维护）
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

def evaluate(kb, mode):
    ok, fails = 0, []
    for q, expect, note in CASES:
        top = kb.search(q, k=1, mode=mode)[0]
        if top["id"] == expect:
            ok += 1
        else:
            fails.append((q, expect, top["id"], top["name"], note))
    return ok, fails

if __name__ == "__main__":
    kb = KB()
    print(f"\n回归测试集：{len(CASES)} 条\n" + "=" * 55)
    for mode in ["vector", "bm25", "hybrid"]:
        ok, fails = evaluate(kb, mode)
        print(f"\n【{mode}】正确率 {ok}/{len(CASES)}")
        for q, expect, got, name, note in fails:
            print(f"  ✗ {q}（{note}）期望[资料{expect}]，实际命中[资料{got}]{name}")
