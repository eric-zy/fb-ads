"""金额单位工具（设计文档 §9）

约定：
    **数据库一律以 BIGINT 存储最小货币单位（分）**，禁止 FLOAT 存金额。

    $10.50  →  1050
    ¥10.50  →  1050
    $0.01   →  1

理由：
    FLOAT 存金额会在累加（sum）、比较（>）时产生精度误差，
    Meta 侧返回的金额本身就是最小单位的整数，转换过程中用 FLOAT 会平白引入误差。

使用：
    - 写入前：to_minor(10.5)          → 1050
    - 读出后：to_major(1050)          → 10.5
    - 展示：  format_money(1050, 'USD') → "10.50"

例外（不参与本约定）：
    ctr / cpc / cpm / roas / conversion_rate / risk_score 等比率与评分
    是**派生指标**而非金额，保持浮点；但计算它们时必须先转成主单位（元）再算。
"""
from typing import Optional

# 常见货币的小数位（用于最小单位换算）。未列出的货币默认 2 位。
_CURRENCY_EXPONENT = {
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
    "CNY": 2,
    "HKD": 2,
    "TWD": 2,
    "JPY": 0,   # 日元无小数位
    "KRW": 0,
    "VND": 0,
}

_CURRENCY_SYMBOL = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "CNY": "¥",
    "JPY": "¥",
}


def exponent_for(currency: Optional[str]) -> int:
    """取货币的小数位数；未知货币按 2 位处理"""
    if not currency:
        return 2
    return _CURRENCY_EXPONENT.get(str(currency).upper(), 2)


def to_minor(amount: Optional[float], currency: Optional[str] = None) -> int:
    """主单位（元）→ 最小单位（分）"""
    if amount is None:
        return 0
    return int(round(float(amount) * (10 ** exponent_for(currency))))


def to_major(amount_minor: Optional[int], currency: Optional[str] = None) -> float:
    """最小单位（分）→ 主单位（元）"""
    if amount_minor is None:
        return 0.0
    return float(amount_minor) / (10 ** exponent_for(currency))


def format_money(amount_minor: Optional[int], currency: Optional[str] = None) -> str:
    """格式化展示，如 1050 + USD → "$10.50" """
    exp = exponent_for(currency)
    symbol = _CURRENCY_SYMBOL.get(str(currency).upper() if currency else "", "")
    value = to_major(amount_minor, currency)
    return f"{symbol}{value:.{exp}f}"
