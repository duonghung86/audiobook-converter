import re
from pathlib import Path


def sanitize_filename(value: str, max_length: int = 250) -> str:
    """Sanitize filenames by removing invalid characters."""
    value = re.sub(r"[<>:\\\"/\\|?*]", "_", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:max_length]


def extract_text_with_formatting(element) -> str:
    """
    Extract text from HTML element while preserving paragraph and line break structure.
    Each <p>, <div>, <br> tag creates a new line.
    """
    lines = []
    for child in element.descendants:
        if isinstance(child, str):
            text = child.strip()
            if text:
                lines.append(text)
        elif child.name in {"p", "div", "li", "dd", "dt"}:
            pass  # Handled by checking for block elements
        elif child.name == "br":
            if lines and lines[-1] != "":
                lines.append("")

    return "\n\n".join(lines)


def deduplicate_text(text: str) -> str:
    """
    Remove consecutive duplicate lines and clean up excessive whitespace.
    """
    lines = text.split("\n")
    deduplicated = []
    prev_line = None

    for line in lines:
        line = line.strip()
        if line and line != prev_line:
            deduplicated.append(line)
            prev_line = line
        elif not line and (not deduplicated or deduplicated[-1] != ""):
            deduplicated.append(line)

    result = "\n".join(deduplicated)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def fix_broken_words(text: str) -> str:
    """
    Fix words that are broken across lines or have spaces between letters.
    This removes spaces between single consonant letters (excluding I) and following lowercase words,
    and between single letters in general.
    """
    # First, fix single consonant letter (excluding I) followed by space and lowercase word
    text = re.sub(r'(\b[B-HJ-Z]\b)\s+(\b[a-z]\w*\b)', r'\1\2', text)
    # Then, fix remaining single letters separated by space
    text = re.sub(r'(\b\w\b)\s+(\b\w\b)', r'\1\2', text)
    return text


def should_skip_section(text: str) -> bool:
    """
    Check if a section should be skipped based on content keywords.
    """
    text_lower = text.lower()
    
    # Skip patterns for sections to exclude
    skip_patterns = [
        # Table of contents
        r'\b(contents|table of contents|toc)\b',
        
        # Acknowledgments/Acknowledgements (including "acknowledges")
        r'\b(acknowledgement|acknowledgements|acknowledgment|acknowledgments|acknowledges)\b',
        
        # Author biography/About the author
        r'\b(about the author|author biography|biography)\b',
        
        # Copyright and legal
        r'\bcopyright\b.*\d{4}',
        
        # Also available/Other books
        r'\b(also available|other books|more books)\b',
        
        # Title page
        r'\btitle page\b',
        
        # Dedication
        r'\bdedication\b',
    ]
    
    for pattern in skip_patterns:
        if re.search(pattern, text_lower):
            return True
    
    return False


def split_into_chunks(text: str, max_chars: int = 3000) -> list[str]:
    """
    Split text into chunks where each chunk has less than max_chars characters
    and does not split paragraphs.
    """
    # First, fix broken words
    text = fix_broken_words(text)
    
    # Split into paragraphs (assuming double newlines separate paragraphs)
    paragraphs = re.split(r'\n\s*\n+', text.strip())

    chunks = []
    current_chunk = ""
    current_length = 0

    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        # Add double newline at end to separate paragraphs
        paragraph_with_break = paragraph + '\n\n'
        paragraph_length = len(paragraph_with_break)

        # If adding this paragraph would exceed the limit and we already have content
        if current_length + paragraph_length > max_chars and current_chunk:
            chunks.append(current_chunk.rstrip())
            current_chunk = paragraph_with_break
            current_length = paragraph_length
        else:
            current_chunk += paragraph_with_break
            current_length += paragraph_length

    # Add the last chunk if it has content
    if current_chunk.strip():
        chunks.append(current_chunk.rstrip())

    return chunks


def ensure_book_texts_folder() -> Path:
    """Ensure that the book_texts folder exists."""
    folder = Path("book_texts")
    folder.mkdir(parents=True, exist_ok=True)
    return folder
