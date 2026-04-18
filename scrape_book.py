import argparse
import os
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from ebooklib import epub


USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"


def sanitize_filename(value: str, max_length: int = 250) -> str:
    value = re.sub(r"[<>:\\\"/\\|?*]", "_", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:max_length]


def download_cover_image(image_url: str, folder: Path) -> Path | None:
    try:
        response = requests.get(image_url, headers={"User-Agent": USER_AGENT}, timeout=20)
        response.raise_for_status()
    except Exception:
        return None

    extension = Path(image_url).suffix.split("?")[0] or ".jpg"
    if extension.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        extension = ".jpg"

    file_path = folder / ("cover" + extension)
    with file_path.open("wb") as f:
        f.write(response.content)
    return file_path


def find_title(soup: BeautifulSoup) -> str:
    og_title = soup.select_one("meta[property='og:title'], meta[name='og:title']")
    if og_title and og_title.get("content"):
        return og_title["content"].strip()

    if soup.title and soup.title.string:
        title = soup.title.string.strip()
        if title:
            return title

    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(strip=True)

    h2 = soup.find("h2")
    if h2 and h2.get_text(strip=True):
        return h2.get_text(strip=True)

    return "book"


def find_cover_url(soup: BeautifulSoup, base_url: str) -> str | None:
    og_image = soup.select_one("meta[property='og:image'], meta[name='og:image']")
    if og_image and og_image.get("content"):
        return requests.compat.urljoin(base_url, og_image["content"].strip())

    cover_image = soup.find("img", alt=re.compile(r"cover", re.I))
    if cover_image and cover_image.get("src"):
        return requests.compat.urljoin(base_url, cover_image["src"].strip())

    cover_image = soup.find("img", src=re.compile(r"cover", re.I))
    if cover_image and cover_image.get("src"):
        return requests.compat.urljoin(base_url, cover_image["src"].strip())

    return None


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


def find_main_content(soup: BeautifulSoup) -> BeautifulSoup:
    selectors = [
        "article",
        "main",
        "div[id*='content']",
        "div[class*='content']",
        "div[class*='book']",
        "section[id*='content']",
    ]
    for selector in selectors:
        element = soup.select_one(selector)
        if element and element.get_text(strip=True):
            return element
    return soup.body or soup


def find_next_page_url(soup: BeautifulSoup, base_url: str) -> str | None:
    # Common patterns for next page links
    next_patterns = [
        ("a[rel='next']", "href"),
        ("a.next", "href"),
        ("a[aria-label*='next']", "href"),
        ("a[aria-label*='Next']", "href"),
        ("a.pagination-next", "href"),
        ("a[class*='next']", "href"),
        ("li.next a", "href"),
    ]

    for selector, attr in next_patterns:
        try:
            element = soup.select_one(selector)
            if element and element.get(attr):
                return requests.compat.urljoin(base_url, element.get(attr).strip())
        except Exception:
            pass

    # Search for links with "next" in text
    for link in soup.find_all("a"):
        text = link.get_text(strip=True).lower()
        href = link.get("href", "").strip()
        if not href:
            continue
        if any(pattern in text for pattern in ["next", "»", "→", "continue →", "next page"]):
            return requests.compat.urljoin(base_url, href)

    # Try to detect pagination from link hrefs (numbered pages)
    all_links = soup.find_all("a")
    for link in all_links:
        href = link.get("href", "").strip()
        # Look for common pagination patterns like p,2, or page=2 or /page/2
        if re.search(r"[?&]page[=_](\d+)", href, re.I) or re.search(r"/page[s]?/(\d+)", href, re.I):
            match = re.search(r"(?:[?&]page[=_]|/page[s]?/)(\d+)", href, re.I)
            if match:
                page_num = int(match.group(1))
                next_page = page_num + 1
                next_url = re.sub(
                    r"(?<=[?&]page[=_]|/page[s]?/)(\d+)",
                    str(next_page),
                    href,
                    flags=re.I,
                )
                return requests.compat.urljoin(base_url, next_url)

    # Try to detect the p,N, pattern in URL and generate next URL
    match = re.search(r"p,(\d+),", base_url)
    if match:
        current_page = int(match.group(1))
        next_page = current_page + 1
        next_url = base_url.replace(f"p,{current_page},", f"p,{next_page},")
        print(f"Found next page via p,N, pattern: {next_url}")
        return next_url
    
    # If URL doesn't have p,N, pattern, assume it's page 1 and generate page 2
    if not re.search(r"p,\d+,", base_url):
        # Pattern: /path/NNNNNN-name_read.html -> /path/p,2,NNNNNN-name_read.html
        next_url = re.sub(r"/(\d+)-", r"/p,2,\1-", base_url)
        if next_url != base_url:
            print(f"Generated next page URL (page 2): {next_url}")
            return next_url

    return None


def extract_chapters(container: BeautifulSoup) -> list[tuple[str, str]]:
    headings = []
    for level in ["h1", "h2", "h3", "h4"]:
        for tag in container.find_all(level):
            text = tag.get_text(strip=True)
            if re.search(r"chapter|part|book|section", text, re.I):
                headings.append(tag)

    if headings:
        chapters = []
        for idx, heading in enumerate(headings):
            content_nodes = []
            sibling = heading.next_sibling
            while sibling:
                if getattr(sibling, "name", None) in {"h1", "h2", "h3", "h4"} and sibling in headings:
                    break
                if isinstance(sibling, str):
                    sibling = sibling.next_sibling
                    continue
                if sibling.get_text(strip=True):
                    content_nodes.append(sibling)
                sibling = sibling.next_sibling

            chapter_title = heading.get_text(strip=True)
            chapter_text = chapter_title + "\n\n"
            if content_nodes:
                # Extract text directly without converting to string first
                content_text = extract_text_with_formatting(content_nodes[0].parent) if hasattr(content_nodes[0], "parent") else extract_text_with_formatting(content_nodes[0])
                chapter_text += content_text
            chapter_text = deduplicate_text(chapter_text)
            
            # Skip unwanted sections
            if not should_skip_section(chapter_text):
                chapters.append((chapter_title, chapter_text.strip()))

        return chapters

    # Fallback: split by paragraphs if no explicit chapter headings
    full_text = extract_text_with_formatting(container)
    full_text = deduplicate_text(full_text)
    if not full_text:
        return [("content", container.get_text(separator="\n", strip=True))]

    # For fallback content, check if it should be skipped
    if should_skip_section(full_text):
        return []

    return [("content", full_text)]


def create_book_folder(book_title: str) -> Path:
    folder_name = sanitize_filename(book_title + "_content")
    folder_path = Path(folder_name)
    folder_path.mkdir(parents=True, exist_ok=True)
    return folder_path


def save_chapters(folder: Path, chapters: list[tuple[str, str]]):
    if len(chapters) == 1 and chapters[0][0].lower() == "content":
        file_path = folder / "book.txt"
        deduplicated_text = deduplicate_text(chapters[0][1])
        file_path.write_text(deduplicated_text, encoding="utf-8")
        return [file_path]

    saved_paths = []
    for idx, (title, text) in enumerate(chapters, start=1):
        deduplicated_text = deduplicate_text(text)
        title_clean = sanitize_filename(title)
        if not title_clean:
            title_clean = f"chapter-{idx}"
        file_name = f"{idx:03d}_{title_clean}.txt"
        file_path = folder / file_name
        file_path.write_text(deduplicated_text, encoding="utf-8")
        saved_paths.append(file_path)
    return saved_paths


def normalize_url(url: str) -> str:
    return url.strip()


def read_links_file(file_path: Path) -> list[str]:
    if not file_path.exists():
        return []
    lines = file_path.read_text(encoding="utf-8").splitlines()
    return [normalize_url(line) for line in lines if normalize_url(line) and not normalize_url(line).startswith("#")]


def load_history(file_path: Path) -> set[str]:
    if not file_path.exists():
        return set()
    lines = file_path.read_text(encoding="utf-8").splitlines()
    return {normalize_url(line) for line in lines if normalize_url(line) and not normalize_url(line).startswith("#")}


def mark_link_scanned(url: str, file_path: Path) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("a", encoding="utf-8") as f:
        f.write(normalize_url(url) + "\n")


def prompt_skip(url: str) -> bool:
    if not sys.stdin.isatty():
        return True
    answer = input(f"Link already scanned: {url}\nSkip this link? [Y/n]: ").strip().lower()
    return answer in ("", "y", "yes")


def scrape_book(url: str, delay_seconds: float = 2.0, max_pages: int = 0) -> dict:
    chapters = []
    current_url = url
    page_count = 0
    visited_urls = set()

    while current_url and (max_pages == 0 or page_count < max_pages):
        if current_url in visited_urls:
            break
        visited_urls.add(current_url)
        page_count += 1

        print(f"Fetching page {page_count}: {current_url}")
        try:
            response = requests.get(current_url, headers={"User-Agent": USER_AGENT}, timeout=25)
            response.raise_for_status()
        except Exception as exc:
            print(f"Error fetching page {page_count}: {exc}", file=sys.stderr)
            break

        soup = BeautifulSoup(response.text, "html.parser")
        main_content = find_main_content(soup)
        page_chapters = extract_chapters(main_content)

        if page_count == 1:
            title = find_title(soup)
            folder = create_book_folder(title)
            cover_url = find_cover_url(soup, current_url)
            cover_path = None
            if cover_url:
                cover_path = download_cover_image(cover_url, folder)
        else:
            page_chapters = [(f"Page {page_count} - {ch_title}", deduplicate_text(ch_text)) for ch_title, ch_text in page_chapters]

        chapters.extend(page_chapters)

        next_url = find_next_page_url(soup, current_url)
        current_url = next_url

        if current_url:
            print(f"Waiting {delay_seconds} seconds before next request...")
            time.sleep(delay_seconds)

    if not chapters:
        return {"title": "book", "folder": "", "chapter_files": [], "cover_path": None, "source_url": url}

    chapter_files = save_chapters(folder, chapters)

    return {
        "title": title,
        "folder": str(folder.resolve()),
        "chapter_files": [str(path.resolve()) for path in chapter_files],
        "cover_path": str(cover_path.resolve()) if cover_path else None,
        "source_url": url,
        "pages_fetched": page_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape a book from a URL or a file of URLs and save chapters into folders, or process an EPUB file.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--url", help="Single book page URL to scrape")
    group.add_argument("--links-file", help="Text file with one book URL per line")
    group.add_argument("--epub", help="EPUB file to process")
    parser.add_argument("--skip-scanned", action="store_true", help="Automatically skip links already scanned without prompting")
    parser.add_argument("--force", action="store_true", help="Re-scan links even if already scanned")
    parser.add_argument("--history-file", default=".scraped_links.txt", help="File to store scanned URLs")
    parser.add_argument("--delay", type=float, default=2.0, help="Delay in seconds between page requests (default: 2.0)")
    parser.add_argument("--max-pages", type=int, default=0, help="Maximum pages to scrape per book (0 = unlimited, default: 0)")
    args = parser.parse_args()

    if not args.url and not args.links_file:
        default_links = Path("book_links.txt")
        if default_links.exists():
            args.links_file = str(default_links)
        else:
            parser.error("Provide --url, --links-file, --epub, or create book_links.txt in the current directory.")

    history_path = Path(args.history_file)
    scanned_history = load_history(history_path)

    if args.epub:
        try:
            result = process_epub(args.epub)
        except Exception as exc:
            print(f"Error processing EPUB: {exc}", file=sys.stderr)
            return 1

        print("EPUB processed successfully:")
        print(f"Title: {result['title']}")
        print(f"Folder: {result['folder']}")
        if result["cover_path"]:
            print(f"Cover saved: {result['cover_path']}")
        else:
            print("Cover image not found.")
        print(f"Total chunks: {result['total_chunks']}")
        print("Chunk files:")
        for path in result["chunk_files"]:
            print(f" - {path}")
        return 0

    if args.links_file:
        links_file_path = Path(args.links_file)
        links = read_links_file(links_file_path)
        if not links:
            print(f"No URLs found in {links_file_path}")
            return 0

        for url in links:
            if not url:
                continue
            if url in scanned_history and not args.force:
                if args.skip_scanned or prompt_skip(url):
                    print(f"Skipping already scanned link: {url}")
                    continue

            print(f"Processing: {url}")
            try:
                result = scrape_book(url, delay_seconds=args.delay, max_pages=args.max_pages)
            except Exception as exc:
                print(f"Error scraping {url}: {exc}", file=sys.stderr)
                continue

            mark_link_scanned(url, history_path)
            scanned_history.add(url)
            print("Book scraped successfully:")
            print(f"Title: {result['title']}")
            print(f"Folder: {result['folder']}")
            if result.get("pages_fetched"):
                print(f"Pages fetched: {result['pages_fetched']}")
            if result["cover_path"]:
                print(f"Cover saved: {result['cover_path']}")
            else:
                print("Cover image not found or could not be downloaded.")
            print("Chapter files:")
            for path in result["chapter_files"]:
                print(f" - {path}")
            print()

        return 0

    try:
        if args.url in scanned_history and not args.force:
            if args.skip_scanned or prompt_skip(args.url):
                print(f"Skipping already scanned link: {args.url}")
                return 0

        result = scrape_book(args.url, delay_seconds=args.delay, max_pages=args.max_pages)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    mark_link_scanned(args.url, history_path)
    print("Book scraped successfully:")
    print(f"Title: {result['title']}")
    print(f"Folder: {result['folder']}")
    if result.get("pages_fetched"):
        print(f"Pages fetched: {result['pages_fetched']}")
    if result["cover_path"]:
        print(f"Cover saved: {result['cover_path']}")
    else:
        print("Cover image not found or could not be downloaded.")
    print("Chapter files:")
    for path in result["chapter_files"]:
        print(f" - {path}")
    return 0


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


def process_epub(epub_path: str) -> dict:
    """
    Process an EPUB file: extract title, cover, content, split into chunks, and save to files.
    """
    epub_path = Path(epub_path)
    if not epub_path.exists():
        raise FileNotFoundError(f"EPUB file not found: {epub_path}")

    # Read the EPUB file
    book = epub.read_epub(str(epub_path))

    # Extract title
    title = book.get_metadata('DC', 'title')
    if title:
        title = title[0][0]
    else:
        title = epub_path.stem  # Use filename if no title

    # Create folder
    folder_name = sanitize_filename(title + "_content")
    folder_path = Path(folder_name)
    folder_path.mkdir(parents=True, exist_ok=True)

    # Extract cover image
    cover_path = None
    for item in book.get_items():
        if item.get_type() == 1 and 'cover' in item.get_name().lower():  # 1 = IMAGE
            cover_filename = f"cover{Path(item.get_name()).suffix}"
            cover_file_path = folder_path / cover_filename
            with cover_file_path.open('wb') as f:
                f.write(item.get_content())
            cover_path = str(cover_file_path.resolve())
            break

    # Extract content from all documents, skipping unwanted sections
    content_parts = []
    for item in book.get_items():
        if item.get_type() == 9:  # 9 = HTML document
            soup = BeautifulSoup(item.get_content(), 'html.parser')
            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.extract()
            text = soup.get_text(separator='\n', strip=True)
            if text.strip() and not should_skip_section(text):
                content_parts.append(text)

    full_content = '\n\n'.join(content_parts)

    # Split content into chunks without breaking paragraphs
    chunks = split_into_chunks(full_content, max_chars=3000)

    # Save chunks to files
    chunk_files = []
    for i, chunk in enumerate(chunks, 1):
        filename = f"{i:03d}_chunk.txt"
        file_path = folder_path / filename
        file_path.write_text(chunk, encoding='utf-8')
        chunk_files.append(str(file_path.resolve()))

    return {
        "title": title,
        "folder": str(folder_path.resolve()),
        "cover_path": cover_path,
        "chunk_files": chunk_files,
        "total_chunks": len(chunks),
        "source_file": str(epub_path.resolve())
    }


def split_into_chunks(text: str, max_chars: int = 3000) -> list[str]:
    """
    Split text into chunks where each chunk has less than max_chars characters
    and does not split paragraphs.
    """
    # Split into paragraphs (assuming double newlines separate paragraphs)
    paragraphs = re.split(r'\n\s*\n', text.strip())

    chunks = []
    current_chunk = ""
    current_length = 0

    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        # Add newline at end of paragraph if not present
        if not paragraph.endswith('\n'):
            paragraph += '\n\n'

        paragraph_length = len(paragraph)

        # If adding this paragraph would exceed the limit and we already have content
        if current_length + paragraph_length > max_chars and current_chunk:
            chunks.append(current_chunk.rstrip())
            current_chunk = paragraph
            current_length = paragraph_length
        else:
            current_chunk += paragraph
            current_length += paragraph_length

    # Add the last chunk if it has content
    if current_chunk.strip():
        chunks.append(current_chunk.rstrip())

    return chunks


if __name__ == "__main__":
    raise SystemExit(main())
