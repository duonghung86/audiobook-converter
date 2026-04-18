import argparse
import sys
from pathlib import Path

from utils import (
    ensure_book_texts_folder,
    sanitize_filename,
    should_skip_section,
    split_into_chunks,
)


def select_text_file() -> Path | None:
    """
    List all text files in book_texts folder and let user select one.
    Returns the path to selected file or None if cancelled.
    """
    book_texts_folder = ensure_book_texts_folder()
    text_files = sorted(book_texts_folder.glob("*_text.txt"))

    if not text_files:
        print("No text files found in 'book_texts' folder.")
        return None

    print("Available text files:")
    for idx, file_path in enumerate(text_files, 1):
        file_size = file_path.stat().st_size / 1024  # Size in KB
        print(f"{idx}. {file_path.name} ({file_size:.1f} KB)")

    try:
        choice = input("\nSelect file number (or press Enter to cancel): ").strip()
        if not choice:
            return None
        choice_idx = int(choice) - 1
        if 0 <= choice_idx < len(text_files):
            return text_files[choice_idx]
        else:
            print("Invalid selection.")
            return None
    except ValueError:
        print("Invalid input.")
        return None


def chunk_text_file(text_file_path: Path, max_chars: int = 3000) -> dict:
    """
    Read a text file, filter out unwanted sections, split into chunks, and save.
    Returns dict with title, folder, chunk_files, and total_chunks.
    """
    # Extract title from filename (remove "_text.txt" suffix)
    filename = text_file_path.stem
    if filename.endswith("_text"):
        title = filename[:-5]  # Remove "_text"
    else:
        title = filename

    # Read the text file
    try:
        full_text = text_file_path.read_text(encoding="utf-8")
    except Exception as exc:
        raise IOError(f"Error reading text file: {exc}")

    # Filter out unwanted sections
    print("Filtering out unwanted sections (TOC, acknowledgements, etc.)...")
    filtered_parts = []
    paragraphs = full_text.split("\n\n")

    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if paragraph and not should_skip_section(paragraph):
            filtered_parts.append(paragraph)

    filtered_text = "\n\n".join(filtered_parts)
    print(f"  Original size: {len(full_text)} characters")
    print(f"  Filtered size: {len(filtered_text)} characters")

    # Split into chunks
    print(f"Splitting text into chunks (max {max_chars} characters per chunk)...")
    chunks = split_into_chunks(filtered_text, max_chars=max_chars)
    print(f"  Created {len(chunks)} chunks")

    # Create folder for chunks
    folder_name = sanitize_filename(title)
    folder_path = Path(folder_name)
    folder_path.mkdir(parents=True, exist_ok=True)

    # Save chunks to files
    chunk_files = []
    for i, chunk in enumerate(chunks, 1):
        filename = f"{i:03d}_chunk.txt"
        file_path = folder_path / filename
        file_path.write_text(chunk, encoding="utf-8")
        chunk_files.append(str(file_path.resolve()))

    return {
        "title": title,
        "folder": str(folder_path.resolve()),
        "chunk_files": chunk_files,
        "total_chunks": len(chunks),
        "source_text_file": str(text_file_path.resolve()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert text file into chunks with filtering.")
    parser.add_argument(
        "text_file",
        nargs="?",
        help="Path to text file in book_texts folder (if not provided, will prompt to select)",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=3000,
        help="Maximum characters per chunk (default: 3000)",
    )
    args = parser.parse_args()

    # Select or validate text file
    if args.text_file:
        text_file_path = Path(args.text_file)
        if not text_file_path.exists():
            print(f"Error: File not found: {text_file_path}", file=sys.stderr)
            return 1
    else:
        text_file_path = select_text_file()
        if not text_file_path:
            print("No file selected.")
            return 0

    try:
        result = chunk_text_file(text_file_path, max_chars=args.max_chars)
    except Exception as exc:
        print(f"Error processing text file: {exc}", file=sys.stderr)
        return 1

    print("\nText file chunked successfully:")
    print(f"Title: {result['title']}")
    print(f"Folder: {result['folder']}")
    print(f"Total chunks: {result['total_chunks']}")
    print("Chunk files:")
    for path in result["chunk_files"]:
        file_size = Path(path).stat().st_size
        print(f"  - {Path(path).name} ({file_size} bytes)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
