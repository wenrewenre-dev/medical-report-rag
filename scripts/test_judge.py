# scripts/test_judge.py —— LLM 裁判的离线单测（不花钱、不联网）
# 跑法：python scripts/test_judge.py
# 验的是裁判最容易静默出错的地方：JSON 解析、字段兜底、机器复核是否对得上
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import judge

SRC = [{"id": 1, "name": "血红蛋白", "text": "参考区间 130-175 g/L"},
       {"id": 12, "name": "平均血红蛋白量", "text": "27-34 pg"}]

ok = True


def check(name, cond, detail=""):
    global ok
    print(("  ✅ " if cond else "  ❌ ") + name + (f"  {detail}" if detail else ""))
    ok = ok and cond


class _Msg:
    def __init__(self, t):
        self.content = t


class _Choice:
    def __init__(self, t):
        self.message = _Msg(t)
        self.finish_reason = "stop"


class _Resp:
    def __init__(self, t):
        self.choices = [_Choice(t)]


class _Completions:
    text = ""

    @classmethod
    def create(cls, **kwargs):
        return _Resp(cls.text)


class _Chat:
    completions = _Completions


class FakeClient:
    """最小的 OpenAI 客户端替身：只返回预置文本"""
    chat = _Chat

    def __init__(self, text):
        _Completions.text = text


print("\n[1] 引用提取")
check("单个引用", judge.citations("见图[资料1]") == ["1"])
check("多个去重保序", judge.citations("[资料12] 和 [资料1] 还有 [资料12]") == ["12", "1"])
check("没有引用", judge.citations("没有任何引用") == [])

print("\n[2] JSON 解析容错")
check("纯 JSON", judge._parse_json('{"pass": true}') == {"pass": True})
check("代码块包裹", judge._parse_json('```json\n{"pass": false}\n```') == {"pass": False})
check("前后夹解释", judge._parse_json('结论如下：{"pass": true} 以上') == {"pass": True})
check("残缺字段兜底", judge._parse_fields('pass: true, citation_valid: false')
      == {"pass": True, "citation_valid": False})
check("非 JSON 返回 None", judge._parse_json("我不是 JSON") is None)

GOOD = ('{"citation_valid": true, "bad_citations": [], "supported": "yes", '
        '"unsupported_claims": [], "fabricated_numbers": [], "pass": true, "reason": "有据可查"}')
BAD_CITE = ('{"citation_valid": false, "bad_citations": ["资料99"], "supported": "yes", '
            '"unsupported_claims": [], "fabricated_numbers": [], "pass": false, "reason": "引用了不存在的资料"}')

print("\n[3] 正常裁决")
v = judge.judge_answer("HGB 偏低怎么办", "血红蛋白 112 g/L 偏低[资料1]。", SRC, FakeClient(GOOD))
check("pass 取到", v["pass"] is True and v["supported"] == "yes")
check("引用与机器复核一致", v["citation_agree"] is True)

v = judge.judge_answer("q", "结论[资料99]", SRC, FakeClient(BAD_CITE))
check("假引用被抓", v["pass"] is False and v["bad_citations"] == ["资料99"])
check("机器侧同样判越界", v["bad_citations_rule"] == ["99"] and v["citation_agree"] is True)

print("\n[4] 裁判漏看要被标记出来")
blind = ('{"citation_valid": true, "bad_citations": [], "supported": "yes", '
         '"unsupported_claims": [], "fabricated_numbers": [], "pass": true, "reason": "看起来没问题"}')
v = judge.judge_answer("q", "结论[资料42]", SRC, FakeClient(blind))
check("citation_agree=False", v["citation_agree"] is False, str(v["bad_citations_rule"]))

print("\n[5] 坏输出兜底")
v = judge.judge_answer("q", "a", SRC, FakeClient("抱歉我无法判断"))
check("不抛异常，返回 error", v["pass"] is None and "error" in v)
check("仍给出机器复核", v["bad_citations_rule"] == [])
partial = '我把结论写在下面\n"pass": false\n"supported": "partial"'
v = judge.judge_answer("q", "a[资料1]", SRC, FakeClient(partial))
check("字段兜底可用并标记 degraded", v["pass"] is False and v["degraded"] is True)

print("\n" + ("全部通过 ✅" if ok else "有失败项 ❌"))
sys.exit(0 if ok else 1)
