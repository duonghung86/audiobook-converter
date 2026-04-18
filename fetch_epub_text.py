import argparse
import sys
from pathlib import Path

from bs4 import BeautifulSoup
from ebooklib import epub

from utils import (
    deduplicate_text,
    ensure_book_texts_folder,
    sanitize_filename,
    should_skip_section,
)


def process_epub_to_text(epub_path: str) -> tuple[str, str]:
    """
    Process an EPUB file and extract all text content.
    Returns (title, full_text).
    """
    epub_path = Path(epub_path)
    if not epub_path.exists():
        raise FileNotFoundError(f"EPUB file not found: {epub_path}")

    # Read the EPUB file
    book = epub.read_epub(str(epub_path))

    # Extract title
    title = book.get_metadata("DC", "title")
    if title:
        title = title[0][0]
    else:
        title = epub_path.stem  # Use filename if no title

    # Extract cover image info
    cover_found = False
    for item in book.get_items():
        if item.get_type() == 1 and "cover" in item.get_name().lower():  # 1 = IMAGE
            cover_found = True
            print(f"Found cover image: {item.get_name()}")
            break

    if not cover_found:
        print("No cover image found in EPUB.")

    # Extract content from all documents, skipping unwanted sections
    content_parts = []
    for item in book.get_items():
        if item.get_type() == 9:  # 9 = HTML document
            soup = BeautifulSoup(item.get_content(), "html.parser")
            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.extract()
            text = soup.get_text(separator="\n", strip=True)
            if text.strip() and not should_skip_section(text):
                content_parts.append(text)

    full_text = "\n\n".join(content_parts)
    return title, full_text


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract text content from EPUB file and save as text file.")
    parser.add_argument("epub", help="Path to EPUB file to process")
    args = parser.parse_args()

    try:
        title, full_text = process_epub_to_text(args.epub)
    except Exception as exc:
        print(f"Error processing EPUB: {exc}", file=sys.stderr)
        return 1

    # Save to book_texts folder
    book_texts_folder = ensure_book_texts_folder()
    filename = sanitize_filename(title + "_text") + ".txt"
    file_path = book_texts_folder / filename

    try:
        file_path.write_text(full_text, encoding="utf-8")
        print(f"EPUB text extracted successfully:")
        print(f"Title: {title}")
        print(f"File: {file_path.resolve()}")
        print(f"Size: {len(full_text)} characters")
        return 0
    except Exception as exc:
        print(f"Error saving file: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
