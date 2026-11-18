"""互供比例的有理数解析与展示，全程不使用浮点。"""
from fractions import Fraction
from decimal import Decimal, InvalidOperation


def parse_rational(value, name='比例'):
    """把整数/有限小数/分数字符串解析为 Fraction。

    接受：int、Fraction、'3/7'、'0.125'、'1e-6' 等；拒绝负数、NaN、无穷与不可解析输入。
    """
    if isinstance(value, bool):
        raise ValueError(f'{name}不能为布尔值')
    if isinstance(value, Fraction):
        result = value
    elif isinstance(value, int):
        result = Fraction(value)
    elif isinstance(value, float):
        # 仅允许能被精确还原的有限二进制浮点；禁止 NaN/Inf
        if value != value or value in (float('inf'), float('-inf')):
            raise ValueError(f'{name}数值不合法')
        result = Fraction(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError(f'{name}不能为空')
        if '/' in text:
            parts = text.split('/')
            if len(parts) != 2:
                raise ValueError(f'{name}分数格式应为 分子/分母')
            numerator, denominator = parts
            try:
                result = Fraction(int(numerator), int(denominator))
            except (ValueError, ZeroDivisionError):
                raise ValueError(f'{name}分数的分子分母必须为整数且分母非零')
        else:
            try:
                result = Fraction(Decimal(text))
            except (InvalidOperation, ValueError):
                raise ValueError(f'{name}不是合法有理数')
    else:
        raise ValueError(f'{name}类型不合法')
    if result < 0:
        raise ValueError(f'{name}不能为负数')
    return result


def fraction_str(value):
    """规范分数串，整数分母省略。"""
    if not isinstance(value, Fraction):
        value = Fraction(value)
    return str(value.numerator) if value.denominator == 1 else f'{value.numerator}/{value.denominator}'


def decimal_str(value, places=12):
    """有限/截断小数展示，仅用于页面预览，计算仍以分数为准。"""
    if not isinstance(value, Fraction):
        value = Fraction(value)
    sign = '-' if value < 0 else ''
    value = abs(value)
    scale = 10 ** places
    whole, remainder = divmod(value.numerator * scale, value.denominator)
    text = str(whole).zfill(places + 1)
    head, tail = text[:-places], text[-places:]
    tail = tail.rstrip('0')
    return sign + (head if not tail else f'{head}.{tail}')
