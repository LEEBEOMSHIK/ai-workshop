def split_sentences(text: str) -> tuple[str, ...]:
    """Split prose on terminal punctuation without treating clause numbers as sentences."""

    sentences: list[str] = []
    start = 0
    active_clause_number: int | None = None
    marker_dot_indexes: set[int] = set()
    for index, character in enumerate(text):
        marker = _numbered_marker_at(text, index)
        if marker is not None and _is_valid_clause_marker(
            text, index, marker[0], active_clause_number
        ):
            if sentence := text[start:index].strip():
                sentences.append(sentence)
            start = index
            active_clause_number = marker[0]
            marker_dot_indexes.add(marker[1])
        if character not in ".!?。！？" or index in marker_dot_indexes:
            continue
        if index + 1 < len(text) and not text[index + 1].isspace():
            continue
        sentence = text[start : index + 1].strip()
        if sentence:
            sentences.append(sentence)
        start = index + 1
        active_clause_number = None
    tail = text[start:].strip()
    if tail:
        sentences.append(tail)
    return tuple(sentences)


def _numbered_marker_at(text: str, index: int) -> tuple[int, int] | None:
    if not text[index].isdigit() or (index > 0 and not text[index - 1].isspace()):
        return None
    marker_end = index
    while marker_end < len(text) and text[marker_end].isdigit():
        marker_end += 1
    if (
        marker_end == len(text)
        or text[marker_end] != "."
        or (marker_end + 1 < len(text) and not text[marker_end + 1].isspace())
    ):
        return None
    return int(text[index:marker_end]), marker_end


def _is_valid_clause_marker(
    text: str, index: int, number: int, active_clause_number: int | None
) -> bool:
    previous = index - 1
    while previous >= 0 and text[previous].isspace():
        previous -= 1
    if previous < 0 or text[previous] in ".!?。！？":
        return True
    if "\n" in text[previous + 1 : index]:
        return True
    return active_clause_number is not None and number == active_clause_number + 1
