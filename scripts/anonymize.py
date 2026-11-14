# scripts/anonymize.py —— 报告数据脱敏：解析之前先把 PHI 抹掉
#
# 定位：本地部署是"数据不出机器"的被动防御，脱敏是"就算发出去也不含身份信息"的主动防御，
#       两层都做，报告里那串姓名/身份证/病历号才不会随请求进入 LLM 供应商的日志。
#
# 做法：只抹值、保留标签（"病历号：[已脱敏]"），行结构不变，
#       下游 parse_line 照常逐行解析，judge 需要的"性别：男/女"也不受影响。
# 不抹：性别、年龄——前者决定用哪套参考区间（功能必需），后者不参与判定但对解读有用，
#       且都不属于直接标识符。
import re

MASK = "[已脱敏]"

# 标签字段：(类别, 标签正则, 值正则)。先按标签抹，能保留"这是什么字段"的语义
LABELED = [
    ("姓名", r"(?:患者|病人|受检者)?姓名",
     r"[\u4e00-\u9fa5·]{2,6}(?=\s|性别|年龄|标本|科室|床号|住院|门诊|$)"),
    ("身份证号", r"(?:身份)?证件?(?:号码|号)",
     r"[0-9Xx]{15,18}"),
    ("电话", r"(?:手机号码|手机号|手机|联系电话|电话号码|电话|联系方式)",
     r"[\d\-+]{7,20}"),
    ("病历号", r"(?:病历|病案)(?:号码|编号|号)",
     r"[A-Za-z0-9\-]{2,24}"),
    ("就诊号", r"(?:门诊|住院|急诊|就诊)(?:号码|编号|号)",
     r"[A-Za-z0-9\-]{2,24}"),
    ("样本号", r"(?:样本|标本|条码|检验|申请单|流水)(?:号码|编号|号)",
     r"[A-Za-z0-9\-]{2,24}"),
    ("卡号", r"(?:医保卡|社保卡|就诊卡)(?:号码|编号|号)?",
     r"[A-Za-z0-9\-]{2,24}"),
    ("地址", r"(?:家庭住址|联系地址|住址|地址)",
     r"[^\n]{2,50}"),
    ("出生日期", r"出生(?:日期|年月)",
     r"[\d\-/年月日]{4,20}"),
]

# 没有标签、直接出现在文本里的：按形态抹
BARE = [
    ("身份证号", r"(?<!\d)\d{17}[\dXx](?!\d)"),
    ("手机号", r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    ("座机号", r"(?<!\d)0\d{2,3}[-\s]?\d{7,8}(?!\d)"),
    ("邮箱", r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    ("日期", r"(?<!\d)(?:19|20)\d{2}[-/年]\d{1,2}[-/月]\d{1,2}日?(?!\d)"),
]


def anonymize_with_report(text: str):
    """返回（脱敏后的文本, {类别: 次数}）——次数给界面展示"抹了几处"。"""
    if not text:
        return text, {}

    counts = {}
    out = text
    for category, label, value in LABELED:
        out, n = re.subn(rf"({label})\s*[:：]?\s*({value})", rf"\1：{MASK}", out)
        if n:
            counts[category] = counts.get(category, 0) + n
    for category, pattern in BARE:
        out, n = re.subn(pattern, MASK, out)
        if n:
            counts[category] = counts.get(category, 0) + n
    return out, counts


def anonymize(text: str) -> str:
    """只要脱敏结果（parse_line 之前调它）"""
    return anonymize_with_report(text)[0]


def summary(counts: dict) -> str:
    """{"姓名": 1, "病历号": 1} → "姓名×1、病历号×1" """
    return "、".join(f"{k}×{v}" if v > 1 else k for k, v in counts.items())
