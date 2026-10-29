"""单据号生成：前缀 + 年月日时分秒 + 随机尾数，保证可读且唯一。"""
import random
from datetime import datetime


def gen_no(prefix: str) -> str:
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"{prefix}{ts}{random.randint(10, 99)}"
