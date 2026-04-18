import argparse
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from utils import (
    deduplicate_text,
    ensure_book_texts_folder,
    extract_text_with_formatting,
    sanitize_filename,
    should_skip_section,
)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"


def download_cover_image(image_url: str, folder: Path) -> Path | None:
    """Download and save cover image from URL."""
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
    """Extract book title from HTML."""
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
    """Find cover image URL in HTML."""
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


def find_main_content(soup: BeautifulSoup) -> BeautifulSoup:
    """Find the main content area of the page."""
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
    """Find the URL for the next page."""
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
    """Extract chapters from HTML container."""
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
                content_text = (
                    extract_text_with_formatting(content_nodes[0].parent)
                    if hasattr(content_nodes[0], "parent")
                    else extract_text_with_formatting(content_nodes[0])
                )
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


def scrape_book_text(url: str, delay_seconds: float = 2.0, max_pages: int = 0) -> tuple[str, str]:
    """
    Scrape book content from URL and return (title, full_text).
    """
    all_text_parts = []
    current_url = url
    page_count = 0
    visited_urls = set()
    title = "book"

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
            cover_url = find_cover_url(soup, current_url)
            if cover_url:
                print(f"Found cover image: {cover_url}")

        # Combine chapter texts
        for chapter_title, chapter_text in page_chapters:
            if page_count > 1:
                all_text_parts.append(f"\n\n--- Page {page_count} ---\n{chapter_title}\n\n{chapter_text}")
            else:
                all_text_parts.append(chapter_text)

        next_url = find_next_page_url(soup, current_url)
        current_url = next_url

        if current_url:
            print(f"Waiting {delay_seconds} seconds before next request...")
            time.sleep(delay_seconds)

    full_text = "\n\n".join(all_text_parts)
    return title, full_text


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch book content from URL and save as text file.")
    parser.add_argument("url", help="Book page URL to scrape")
    parser.add_argument("--delay", type=float, default=2.0, help="Delay in seconds between page requests (default: 2.0)")
    parser.add_argument("--max-pages", type=int, default=0, help="Maximum pages to scrape (0 = unlimited, default: 0)")
    args = parser.parse_args()

    try:
        title, full_text = scrape_book_text(args.url, delay_seconds=args.delay, max_pages=args.max_pages)
    except Exception as exc:
        print(f"Error scraping URL: {exc}", file=sys.stderr)
        return 1

    # Save to book_texts folder
    book_texts_folder = ensure_book_texts_folder()
    filename = sanitize_filename(title + "_text") + ".txt"
    file_path = book_texts_folder / filename

    try:
        file_path.write_text(full_text, encoding="utf-8")
        print(f"Book text saved successfully:")
        print(f"Title: {title}")
        print(f"File: {file_path.resolve()}")
        print(f"Size: {len(full_text)} characters")
        return 0
    except Exception as exc:
        print(f"Error saving file: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
