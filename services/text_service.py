import json
import re

def to_sentence_case(text: str) -> str:
    """Capitalize the first letter of each sentence and lowercase the rest."""
    if not text:
        return ""
    # Split on punctuation followed by spaces
    sentences = re.split(r'([.!?]\s+)', text)
    result = []
    for i, part in enumerate(sentences):
        if i % 2 == 0:
            # Sentence content
            if part:
                # Capitalize first letter, lowercase the rest
                result.append(part[0].upper() + part[1:].lower())
            else:
                result.append(part)
        else:
            # Punctuation/spacing
            result.append(part)
    # Join and capitalize the very first character if needed
    joined = "".join(result)
    if joined:
        return joined[0].upper() + joined[1:]
    return joined

def remove_duplicate_lines(text: str) -> str:
    seen = set()
    result = []
    for line in text.splitlines():
        if line not in seen:
            seen.add(line)
            result.append(line)
    return "\n".join(result)

def clean_text(text: str) -> str:
    # Strip HTML
    cleaned = re.sub(r'<[^>]*>', '', text)
    # Condense white spaces
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return cleaned.strip()

def pretty_print_json(text: str) -> str:
    try:
        parsed = json.loads(text)
        return json.dumps(parsed, indent=4, ensure_ascii=False)
    except Exception as e:
        raise ValueError("Invalid JSON string.")

def get_text_stats(text: str) -> dict:
    return {
        "chars": len(text),
        "words": len(text.split()),
        "lines": len(text.splitlines())
    }
