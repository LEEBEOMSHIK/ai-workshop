def split_sentences(text: str) -> tuple[str, ...]:
    """Split prose on terminal punctuation without treating clause numbers as sentences."""

    sentences: list[str] = []
    start = 0
    for index, character in enumerate(text):
        if character not in ".!?。！？" or _is_numbered_clause_dot(text, index):
            continue
        if index + 1 < len(text) and not text[index + 1].isspace():
            continue
        sentence = text[start : index + 1].strip()
        if sentence:
            sentences.append(sentence)
        start = index + 1
    tail = text[start:].strip()
    if tail:
        sentences.append(tail)
    return tuple(sentences)


def _is_numbered_clause_dot(text: str, index: int) -> bool:
    if text[index] != ".":
        return False
    marker_start = index
    while marker_start > 0 and not text[marker_start - 1].isspace():
        marker_start -= 1
    return text[marker_start:index].isdigit()
