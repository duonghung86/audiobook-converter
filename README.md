# Audiobook Converter

A complete workflow to convert EPUB books to organized text chunks and then to audio files using Edge TTS.

## Features

- **EPUB Processing**: Extract title, cover image, and content from EPUB files
- **Smart Text Chunking**: Split content into chunks under 3000 characters without breaking paragraphs
- **Text-to-Speech**: Convert text chunks to high-quality audio using Edge TTS
- **Voice Detection**: Automatically uses female voice by default, male voice for male characters
- **Rate Limiting**: Built-in delays to avoid abusing TTS services
- **Organized Output**: Creates structured folders for content and audio files

## Installation

```bash
pip install -r requirements.txt
```

## Usage

### Step 1: Process EPUB to Text Chunks

```bash
# Process a single EPUB file
python scrape_book.py --epub "path/to/book.epub"

# Or process from book_links.txt
python scrape_book.py
```

This creates a folder like `Book Title_content/` containing:
- `cover.jpg` (if available)
- `001_chunk.txt`, `002_chunk.txt`, etc. (text chunks)

### Step 2: Convert Text Chunks to Audio

```bash
# Convert chunks to audio with default 3-second delay
python convert_to_audio.py "Book Title_content"

# Use custom delay (recommended to avoid rate limiting)
python convert_to_audio.py "Book Title_content" --delay 5.0
```

This creates a folder like `Book Title_audio/` containing:
- `001_audio.mp3`, `002_audio.mp3`, etc. (audio files)

## Voice Selection

- **Female Voice**: Used by default (en-US-AriaNeural)
- **Male Voice**: Automatically detected when male characters speak (en-US-ZiraNeural)
- Detection is based on common male names in dialogue patterns

## File Organization

```
audiobook_converter/
├── book_links.txt          # URLs for web scraping
├── scrape_book.py          # Main scraper and EPUB processor
├── convert_to_audio.py     # TTS conversion script
├── requirements.txt        # Python dependencies
├── epubs/                  # EPUB files
└── Book Title_content/     # Generated content folder
    ├── cover.jpg
    ├── 001_chunk.txt
    └── ...
└── Book Title_audio/       # Generated audio folder
    ├── 001_audio.mp3
    └── ...
```

## Command Line Options

### scrape_book.py

```bash
# Web scraping options
python scrape_book.py --url "https://example.com/book"
python scrape_book.py --links-file book_links.txt --skip-scanned
python scrape_book.py --links-file book_links.txt --force --max-pages 10

# EPUB processing
python scrape_book.py --epub "book.epub"
```

### convert_to_audio.py

```bash
python convert_to_audio.py "content_folder" --delay 3.0
```

## Tips

- Use longer delays (3-5 seconds) between audio conversions to avoid rate limiting
- Process EPUBs directly for better formatting preservation
- The voice detection is basic - it works for obvious male/female character dialogue
- Audio files are saved as MP3 format compatible with most players

## Dependencies

- `beautifulsoup4`: HTML parsing
- `requests`: HTTP requests for web scraping
- `ebooklib`: EPUB file processing
- `edge-tts`: Microsoft Edge Text-to-Speech service