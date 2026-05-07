import os
import re
import torch
import soundfile as sf
from pydub import AudioSegment
from time import sleep
from kokoro import KPipeline

# def get_gpu_free_bytes(device_index=0):
#     """Return free bytes on GPU (best-effort)."""
#     if torch.cuda.is_available():
#         try:
#             # PyTorch built-in (accurate for allocator view)
#             free, total = torch.cuda.mem_get_info(device_index)
#             return int(free)
#         except Exception:
#             pass
#     if _USE_PYNVML:
#         h = nvmlDeviceGetHandleByIndex(device_index)
#         info = nvmlDeviceGetMemoryInfo(h)
#         return int(info.free)
#     # fallback: no GPU
#     return 0

def shorttext2audio(pipe, text, voice="af_bella", speed=0.8, lang="en-us"):
    chunks = list(pipe(text, voice=voice, speed=speed))
    # Concatenate all audio tensors
    audio_tensor = torch.cat([c.audio.cpu() for c in chunks], dim=0)
    # Convert to numpy float32
    audio_np = audio_tensor.numpy().astype("float32")
    # Kokoro uses 24 kHz sample rate
    sf.write("temp.wav", audio_np, 24000)
    p_audio = AudioSegment.from_wav("temp.wav")
    os.remove("temp.wav")
    return p_audio

def longtext2audio(pipe, text, voice="af_bella", speed=0.8, lang="en-us",
                    max_chars=200):
    """
    Split long text into chunks sized to current GPU free memory.
    bytes_per_char: conservative estimate (UTF-8 worst-case or tokenizer average).
    safety_factor: fraction of free memory to consider usable.
    """
    if len(text) < max_chars:
        short_audio = shorttext2audio(pipe, text, voice=voice, speed=speed, lang=lang)
        sleep(1)
        return short_audio
    sentences = re.split(r'(?<=[.!?])["”’]?\s*(?=[A-Z"“‘]|$)', text)
    # Filter out empty strings that might result from splits (e.g., at the end of the text)
    sentences = [s.strip() for s in sentences if s.strip()]

    current_chunk = []
    long_audio = AudioSegment.empty()
    for isentence, sentence in enumerate(sentences):
        chunk_text = ". ".join(current_chunk)
        if (len(chunk_text) < max_chars) and (isentence < len(sentences) - 1):
            current_chunk.append(sentence)
        else:
            print(f"Chunk of {len(chunk_text)} chars ready for audio generation.")
            short_audio = shorttext2audio(pipe,chunk_text, voice=voice, speed=speed, lang=lang)
            long_audio += short_audio
            current_chunk = [sentence]
            sleep(1)
    return long_audio

def chapter2audio(chapter_file):
    pipe = KPipeline(lang_code="a", device="cuda",repo_id='hexgrad/Kokoro-82M')
    with open(chapter_file, 'r', encoding='utf-8') as f:
        chapter_text = f.read()
    # Split into logical paragraphs.
    raw_paragraphs = re.split(r'\n', chapter_text)
    paragraphs = [p.strip() for p in raw_paragraphs if p.strip()]
    print(f"Chapter has {len(paragraphs)} paragraphs")
    combined_audio = AudioSegment.empty()
    for j,p in enumerate(paragraphs):
        # print(len(p.split()),len(p))
        try:
            p_audio = longtext2audio(pipe,p)
            combined_audio += p_audio
        except Exception as e:
            print(f"Error occurred while processing paragraph {j}: {e}")
            return


    base_name = os.path.splitext(os.path.basename(chapter_file))[0]
    output_dir = os.path.dirname(chapter_file).replace('texts', 'audios')
    output_mp3_path = os.path.join(output_dir, f"{base_name}.mp3")

    # Export the merged audio with high quality VBR mp3
    print(f"Saving merged audio to: {output_mp3_path}")
    combined_audio.export(output_mp3_path, format="mp3", parameters=["-q:a", "0"])

def book2audio(folder_path,start_chapter=70):
    txt_files = []
    if os.path.isdir(folder_path):
        for f in os.listdir(folder_path):
            if f.lower().endswith('.txt'):
                txt_files.append(os.path.join(folder_path, f))
        txt_files.sort()
        print("Sorted list of txt files:")
        for i, txt_file in enumerate(txt_files):
            if i <= start_chapter:
                continue
            print(txt_file.split('/')[-1],end=', ')
            chapter2audio(txt_file)

def select_book_folder():
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()  # Hide the root window
    directory_path = filedialog.askdirectory(title="Select a book folder", initialdir="texts")
    return directory_path

if __name__ == "__main__":
    book_folder = select_book_folder()
    book2audio(book_folder)
