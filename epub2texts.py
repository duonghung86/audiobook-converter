import re
from ebooklib import epub
from PIL import Image
import io
import os
import ebooklib
from bs4 import BeautifulSoup
import requests
import json
import os


def get_trimmed_title(title, max_length=5):
    # Remove special characters from base_title
    title = re.sub(r'[^a-zA-Z0-9\s]', '', title)
    parts = re.split(r'[:\-]', title)
    base_title = parts[0].strip()
    words = base_title.split()
    return " ".join(words[:max_length]) if len(words) > max_length else base_title

def select_epub_file():
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()  # Hide the root window
    file_path = filedialog.askopenfilename(title="Select an EPUB file", filetypes=[("EPUB files", "*.epub")])    
    return file_path

def search_book_manual(query):
    # We add 'intitle:' to tell Google to look specifically in the title
    url = f"https://www.googleapis.com/books/v1/volumes?q=intitle:{query}"

    response = requests.get(url)
    data = response.json()

    if "items" in data:
        # Get the first result
        volume_info = data["items"][0]["volumeInfo"]

        metadata = {
            "title": volume_info.get("title"),
            "authors": volume_info.get("authors", []),
            "publisher": volume_info.get("publisher"),
            "publishedDate": volume_info.get("publishedDate"),
            "isbn_13": next((identifier["identifier"] for identifier in volume_info.get("industryIdentifiers", [])
                            if identifier["type"] == "ISBN_13"), None)
        }
        return metadata

    return None

def create_directory(book_path,safe_title=None): 
    book = epub.read_epub(book_path)
    full_title = book.get_metadata('DC', 'title')[0][0]
    author = book.get_metadata('DC', 'creator')[0][0]
    print(full_title, author)
    if safe_title is None:
        safe_title = get_trimmed_title(full_title)
    print(safe_title)
    text_path = f"texts/{safe_title}"
    print(text_path)
    audiobook_path = f"audios/{safe_title}"
    print(audiobook_path)
    os.makedirs(text_path, exist_ok=True)
    os.makedirs(audiobook_path, exist_ok=True)
    # Get the book metadata
    book_metadata = search_book_manual(full_title)

    if book_metadata is None:
        book_metadata = {
            "title": full_title,
            "authors": author
            }
    # Define the path for the JSON file
    metadata_filepath = os.path.join(text_path, "metadata.json")

    # Save the metadata to a JSON file
    with open(metadata_filepath, 'w', encoding='utf-8') as f:
        json.dump(book_metadata, f, ensure_ascii=False, indent=4)
    print(f"Book metadata saved to: {metadata_filepath}")
    
    return book, text_path, audiobook_path

def get_book_cover_image(book, text_path, field_name='cover'):
    items = {item.get_id(): item for item in book.get_items()}
    if field_name not in items:
        print(f"No {field_name} key found in the EPUB file.")
        print("Available items:", items.keys())
        return None
    cover = items['cover']
    image_data = cover.get_content()
    try:
        image = Image.open(io.BytesIO(image_data))
        cover_filename = os.path.join(text_path, "cover.jpg")
        image.save(cover_filename)
        print(f"Cover image saved to: {cover_filename}")
    except Exception as e:
        print(f"Could not save cover image: {e}")

def extract_chapters(book, text_path):
    items = {item.get_id(): item for item in book.get_items()}
    non_chapter_keywords = tuple(['the author gratefully acknowledges','contents','about the author',
                              "copyright",'dear reader', 'revision history','table of contents',
                              'books by the same author','book'])
    # Remove existing .txt files in text_path
    for f in os.listdir(text_path):
        if f.lower().endswith('.txt'):
            os.remove(os.path.join(text_path, f))
            print(f"Removed existing text file: {f}")

    chapter_id = 1
    for spine_item in book.spine:
        item_id = spine_item[0]  # (id, type)
        print(f"Item ID: {item_id}, Type: {items[item_id].get_type()}")
        if item_id in items:
            item = items[item_id]
            if (item.get_type() == ebooklib.ITEM_DOCUMENT)&(not item_id.startswith("ded")):
                soup = BeautifulSoup(item.get_content(), "html.parser")
                text = soup.get_text().strip()
                if len(text)==0:
                    print(f"The content in {item_id} is empty")
                    continue
                if text[:50].lower().startswith(non_chapter_keywords):
                    print(f"The content in {item_id} is not a chapter")
                    continue
                print(f"=== Chapter {chapter_id} ===")
                if not text[:20].lower().startswith('chapter'):
                    text = f"Chapter {chapter_id} \n\n" + text.strip()
                print(text[:50])
                full_text_path = os.path.join(text_path, f"ch{chapter_id:03d}.txt")
                with open(full_text_path, 'w') as f:
                    f.write(text)
                print(f"Full text saved to: {full_text_path}")
                chapter_id += 1
                if chapter_id == 82:
                    break


if __name__ == "__main__":
    epub_file_path = select_epub_file()
    if epub_file_path:
        book, text_path, audiobook_path = create_directory(epub_file_path)
        get_book_cover_image(book, text_path)
        extract_chapters(book, text_path)
    else:
        print("No EPUB file selected.")