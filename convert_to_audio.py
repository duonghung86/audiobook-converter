import asyncio
import re
import time
from pathlib import Path
from typing import List, Tuple

import edge_tts


# Common male names for voice detection (expandable list)
MALE_NAMES = {
    'adam', 'alex', 'andrew', 'anthony', 'ben', 'benjamin', 'bobby', 'brandon',
    'brian', 'charles', 'chris', 'christopher', 'daniel', 'david', 'dennis',
    'edward', 'eric', 'frank', 'gary', 'george', 'greg', 'henry', 'jack',
    'james', 'jason', 'jeff', 'jeffrey', 'jeremy', 'jim', 'joe', 'john',
    'jonathan', 'josh', 'joshua', 'justin', 'kevin', 'larry', 'mark', 'matt',
    'matthew', 'michael', 'mike', 'nick', 'patrick', 'paul', 'peter', 'phil',
    'philip', 'ray', 'richard', 'rick', 'robert', 'ron', 'ryan', 'sam',
    'scott', 'sean', 'steve', 'steven', 'ted', 'tim', 'timothy', 'tom',
    'travis', 'wayne', 'will', 'william'
}

# TTS voice configurations
FEMALE_VOICE = "en-US-AriaNeural"  # Natural female voice
MALE_VOICE = "en-US-ZiraNeural"     # Natural male voice


def detect_voice_for_text(text: str) -> str:
    """
    Basic voice detection based on male names in dialogue.
    Returns FEMALE_VOICE by default, MALE_VOICE if male character detected.
    """
    # Look for dialogue patterns with male names
    # Pattern: "Name said," or "Name:" or similar
    lines = text.split('\n')

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Check for dialogue with male names
        for name in MALE_NAMES:
            # Patterns like: "John said,", "John:", ""John,"", etc.
            patterns = [
                rf'\b{name}\b.*?(said|asked|replied|whispered|shouted|yelled|cried)',
                rf'"{name},',
                rf'"{name}:',
                rf'^\s*{name}\s*:',
                rf'^\s*"{name}',
            ]

            for pattern in patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    return MALE_VOICE

    return FEMALE_VOICE


def split_text_by_voice(text: str) -> List[Tuple[str, str]]:
    """
    Split text into segments with appropriate voices.
    Returns list of (text_segment, voice) tuples.
    """
    segments = []
    current_voice = FEMALE_VOICE
    current_segment = []

    lines = text.split('\n')

    for line in lines:
        line_voice = detect_voice_for_text(line)

        if line_voice != current_voice and current_segment:
            # Voice change - save current segment
            segments.append((' '.join(current_segment), current_voice))
            current_segment = [line]
            current_voice = line_voice
        else:
            current_segment.append(line)

    # Add remaining segment
    if current_segment:
        segments.append((' '.join(current_segment), current_voice))

    return segments


async def text_to_speech(text: str, output_file: Path, voice: str = FEMALE_VOICE) -> None:
    """
    Convert text to speech using Edge TTS.
    """
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(output_file))


async def convert_chunk_to_audio(chunk_file: Path, audio_folder: Path, delay: float = 2.0) -> None:
    """
    Convert a single chunk file to audio with appropriate voice detection.
    """
    print(f"Processing: {chunk_file.name}")

    # Read the chunk text
    text = chunk_file.read_text(encoding='utf-8')

    # Split by voice segments
    voice_segments = split_text_by_voice(text)

    # Create audio filename
    chunk_num = chunk_file.stem.split('_')[0]  # e.g., "001" from "001_chunk.txt"
    audio_file = audio_folder / f"{chunk_num}_audio.mp3"

    # If only one segment, use simple conversion
    if len(voice_segments) == 1:
        segment_text, voice = voice_segments[0]
        await text_to_speech(segment_text, audio_file, voice)
    else:
        # Multiple voice segments - combine into single audio file
        # For simplicity, use the predominant voice for the whole chunk
        # (Advanced: could concatenate multiple audio segments)
        male_segments = sum(1 for _, v in voice_segments if v == MALE_VOICE)
        female_segments = len(voice_segments) - male_segments

        predominant_voice = MALE_VOICE if male_segments > female_segments else FEMALE_VOICE

        # Combine all text
        combined_text = ' '.join(text for text, _ in voice_segments)
        await text_to_speech(combined_text, audio_file, predominant_voice)

    print(f"Created: {audio_file}")

    # Delay to avoid rate limiting
    if delay > 0:
        print(f"Waiting {delay} seconds...")
        await asyncio.sleep(delay)


async def process_book_audio(content_folder: Path, delay: float = 3.0) -> dict:
    """
    Process all chunk files in a content folder and convert to audio.
    """
    if not content_folder.exists():
        raise FileNotFoundError(f"Content folder not found: {content_folder}")

    # Extract book title from folder name
    folder_name = content_folder.name
    if folder_name.endswith('_content'):
        book_title = folder_name[:-8]  # Remove '_content'
    else:
        book_title = folder_name

    # Create audio folder
    audio_folder_name = sanitize_filename(book_title + "_audio")
    audio_folder = content_folder.parent / audio_folder_name
    audio_folder.mkdir(parents=True, exist_ok=True)

    # Find all chunk files
    chunk_files = sorted(content_folder.glob("*_chunk.txt"))

    if not chunk_files:
        raise FileNotFoundError(f"No chunk files found in {content_folder}")

    print(f"Found {len(chunk_files)} chunk files")
    print(f"Audio will be saved to: {audio_folder}")

    # Process each chunk
    audio_files = []
    for chunk_file in chunk_files:
        await convert_chunk_to_audio(chunk_file, audio_folder, delay)
        audio_files.append(audio_folder / f"{chunk_file.stem.split('_')[0]}_audio.mp3")

    return {
        "book_title": book_title,
        "audio_folder": str(audio_folder.resolve()),
        "audio_files": [str(f.resolve()) for f in audio_files],
        "total_chunks": len(chunk_files)
    }


def sanitize_filename(value: str, max_length: int = 250) -> str:
    """Sanitize filename for filesystem compatibility."""
    value = re.sub(r"[<>:\\\"/\\|?*]", "_", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:max_length]


async def main_async(content_folder: str, delay: float = 3.0) -> None:
    """
    Main async function for command-line usage.
    """
    content_path = Path(content_folder)

    try:
        result = await process_book_audio(content_path, delay)
        print("\nAudio conversion completed successfully!")
        print(f"Book: {result['book_title']}")
        print(f"Audio folder: {result['audio_folder']}")
        print(f"Audio files created: {result['total_chunks']}")
        print("\nAudio files:")
        for audio_file in result['audio_files']:
            print(f" - {audio_file}")
    except Exception as exc:
        print(f"Error: {exc}", file=__import__('sys').stderr)
        return 1

    return 0


def main():
    """
    Command-line interface.
    """
    import argparse

    parser = argparse.ArgumentParser(description="Convert book chunks to audio using Edge TTS.")
    parser.add_argument("content_folder", help="Path to the folder containing chunk files (e.g., 'Book Title_content')")
    parser.add_argument("--delay", type=float, default=3.0, help="Delay in seconds between audio conversions (default: 3.0)")

    args = parser.parse_args()

    # Run the async main function
    asyncio.run(main_async(args.content_folder, args.delay))


if __name__ == "__main__":
    main()