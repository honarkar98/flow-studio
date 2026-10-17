"""Pure variable interpolation and response mapping."""

from copy import deepcopy
import json
import re

VARIABLE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
EXACT_VARIABLE = re.compile(r"^\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}$")
NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def valid_name(name):
    return isinstance(name, str) and NAME.fullmatch(name) is not None


def validate_capture_rules(rules):
    if rules is None:
        return
    if not isinstance(rules, list):
        raise ValueError("قواعد ذخیرهٔ پاسخ باید آرایه باشند.")
    for rule in rules:
        if not isinstance(rule, dict) or not valid_name(rule.get("name")):
            raise ValueError("نام متغیر خروجی معتبر نیست.")
        if not isinstance(rule.get("path", "$"), str):
            raise ValueError("مسیر فیلد پاسخ معتبر نیست.")


def _value(name, variables):
    if name not in variables:
        raise ValueError(f"متغیر {name} مقدار ندارد.")
    return variables[name]


def render(value, variables):
    if isinstance(value, dict):
        return {key: render(item, variables) for key, item in value.items()}
    if isinstance(value, list):
        return [render(item, variables) for item in value]
    if not isinstance(value, str):
        return value
    exact = EXACT_VARIABLE.fullmatch(value)
    if exact:
        return deepcopy(_value(exact.group(1), variables))

    def replace(match):
        item = _value(match.group(1), variables)
        return item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)

    return VARIABLE.sub(replace, value)


def extract(document, path):
    """Read a dotted/array path such as $.results[0].id; $ means the root."""
    if not isinstance(path, str):
        raise ValueError("مسیر پاسخ معتبر نیست.")
    remaining = path.strip()
    if remaining == "$":
        return deepcopy(document)
    if remaining.startswith("$"):
        remaining = remaining[1:]
    if remaining.startswith("."):
        remaining = remaining[1:]
    if not remaining:
        raise ValueError("مسیر پاسخ معتبر نیست.")
    current = document
    while remaining:
        if remaining.startswith("["):
            end = remaining.find("]")
            if end < 0 or not remaining[1:end].isdigit():
                raise ValueError(f"اندیس مسیر پاسخ معتبر نیست: {path}")
            index = int(remaining[1:end])
            if not isinstance(current, list) or index >= len(current):
                raise ValueError(f"فیلد پاسخ یافت نشد: {path}")
            current = current[index]
            remaining = remaining[end + 1:]
        else:
            split = re.search(r"[.\[]", remaining)
            end = split.start() if split else len(remaining)
            key = remaining[:end]
            if not key or not isinstance(current, dict) or key not in current:
                raise ValueError(f"فیلد پاسخ یافت نشد: {path}")
            current = current[key]
            remaining = remaining[end:]
        if remaining.startswith("."):
            remaining = remaining[1:]
            if not remaining:
                raise ValueError(f"مسیر پاسخ معتبر نیست: {path}")
    return deepcopy(current)


def capture(response_json, rules, variables):
    validate_capture_rules(rules)
    updated = dict(variables)
    for rule in rules or []:
        name = rule.get("name")
        updated[name] = extract(response_json, rule.get("path", "$"))
    return updated


def assert_response(response_json, rules):
    for rule in rules or []:
        actual = extract(response_json, rule["path"])
        if actual != rule.get("equals"):
            raise ValueError(f"شرط پاسخ برقرار نیست: {rule['path']}")
