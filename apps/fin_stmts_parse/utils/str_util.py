import re
import json
import unicodedata


_EXCEL_ESCAPED_CHAR_RE = re.compile(r"_x([0-9A-Fa-f]{4})_")


def replace_excel_escaped_control_chars(text):
    """Replace Excel XML escaped control/whitespace chars, such as _x000D_, with spaces."""
    value = str(text)

    def replace_match(match):
        codepoint = int(match.group(1), 16)
        char = chr(codepoint)
        category = unicodedata.category(char)
        if char.isspace() or category in {"Cc", "Cf"}:
            return " "
        return match.group(0)

    return _EXCEL_ESCAPED_CHAR_RE.sub(replace_match, value)


def is_match(reg, text):
    if re.search(rf"{reg}", text):
        return True
    else:
        return False

def extract_data(reg, text):
    match = re.search(rf"{reg}", text)
    if match:
        return match.group(0)
    else:
        return None

def extract_llm_json(text):
    # 1. 提取 Markdown 中的 JSON
    match = re.search(r"```json(.*?)(?=```)", text, re.DOTALL)
    if match:
        content = re.sub(r"//.*?\n", "\n", match.group(1))
        try:
            return json.loads(content.strip())
        except:
            return {}

    # 2. 提取文本中的原始 JSON 对象
    if re.search(r"{.*?}", text, re.DOTALL):
        decoder = json.JSONDecoder()
        try:
            start_index = text.find('{')
            obj, index = decoder.raw_decode(text[start_index:])
            return obj
        except (json.JSONDecodeError, ValueError):
            return {}
    else:
        return {}
