import os
import re
from tracemalloc import start
# import torch
import soundfile as sf
from pydub import AudioSegment
from time import sleep, time
# from kokoro import KPipeline
import onnxruntime as rt
from kokoro_onnx import Kokoro
import json
import eyed3

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

def get_kokoro_model():
    providers = [
        ('CUDAExecutionProvider', {
            'device_id': 0,
            'arena_extend_strategy': 'kNextPowerOfTwo',
            'gpu_mem_limit':  int(3.5 * 1024 * 1024 * 1024) ,
            'cudnn_conv_algo_search': 'DEFAULT',
            'do_copy_in_default_stream': True,
        }),
    ]
    kokoro_onnx_path = "kokoro_models/kokoro-v0_19.onnx"
    voice_json_path = "kokoro_models/voices.json"
    model = Kokoro(kokoro_onnx_path, voice_json_path)

    try:
        model.sess = rt.InferenceSession(kokoro_onnx_path, providers=providers)
        print(f"Kokoro initialized with providers: {model.sess.get_providers()}")
    except Exception as e:
        print(f"CUDA session failed: {e}")
        print("Falling back to CPUExecutionProvider.")
        model.sess = rt.InferenceSession(kokoro_onnx_path, providers=["CPUExecutionProvider"])
        print(f"Kokoro initialized with providers: {model.sess.get_providers()}")

    return model


def shorttext2audio(kmodel, text, voice="af_bella", speed=0.8, lang="en-us"):
    samples, sample_rate = kmodel.create(text, voice=voice, speed=speed, lang=lang)
    temp_wav_path = "temp.wav"
    sf.write(temp_wav_path, samples, sample_rate)
    p_audio = AudioSegment.from_wav("temp.wav")
    os.remove("temp.wav")
    return p_audio

def read_text_file(chapter_file):
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            with open(chapter_file, 'r', encoding=encoding) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    with open(chapter_file, 'r', encoding='utf-8', errors='replace') as f:
        return f.read()

def longtext2audio(kmodel, text, voice="af_bella", speed=0.8, lang="en-us",
                    max_chars=4000):
    """
    Split long text into chunks sized to current GPU free memory.
    bytes_per_char: conservative estimate (UTF-8 worst-case or tokenizer average).
    safety_factor: fraction of free memory to consider usable.
    """
    if len(text) < max_chars:
        print(f"Generating the chunk 1 ({len(text)} characters) 100% ...")
        short_audio = shorttext2audio(kmodel, text, voice=voice, speed=speed, lang=lang)
        sleep(1)
        return short_audio
    sentences = re.split(r'(?<=[.!?])["”’]?\s*(?=[A-Z"“‘]|$)', text)
    sentences = [s.strip() for s in sentences if s.strip()]

    current_chunk = []
    long_audio = AudioSegment.empty()
    chunk_id = 1
    processed_char = 0
    for isentence, sentence in enumerate(sentences):
        if not current_chunk:
            current_chunk.append(sentence)
            continue

        joined = ". ".join(current_chunk + [sentence])
        if len(joined) <= max_chars:
            current_chunk.append(sentence)
            continue

        chunk_text = ". ".join(current_chunk)
        processed_char += len(chunk_text)
        processed_percent = round(processed_char*100/len(text),2)
        print(f"Generating the chunk {chunk_id} ({len(chunk_text)} characters) {processed_percent}% ...")
        short_audio = shorttext2audio(kmodel, chunk_text, voice=voice, speed=speed, lang=lang)
        long_audio += short_audio
        current_chunk = [sentence]
        sleep(0.5)
        chunk_id += 1

    if current_chunk:
        chunk_text = ". ".join(current_chunk)
        print(f"Generating the chunk {chunk_id} ({len(chunk_text)} characters) ...")
        short_audio = shorttext2audio(kmodel, chunk_text, voice=voice, speed=speed, lang=lang)
        long_audio += short_audio

    return long_audio

def chapter2audio(kokoro_model, chapter_file, skip_if_exists=True):
    base_name = os.path.splitext(os.path.basename(chapter_file))[0]
    output_dir = os.path.dirname(chapter_file).replace('texts', 'audios')
    output_mp3_path = os.path.join(output_dir, f"{base_name}.mp3")
    if skip_if_exists and os.path.exists(output_mp3_path):
        print(f"Skipping {chapter_file} as {output_mp3_path} already exists.")
    else:
        chapter_text = read_text_file(chapter_file)
        # Split into logical paragraphs.
        raw_paragraphs = re.split(r'\n\n', chapter_text)
        paragraphs = [p.strip() for p in raw_paragraphs if p.strip()]
        print(f"Chapter has {len(paragraphs)} paragraphs")
        combined_audio = AudioSegment.empty()
        start=time()
        for j,p in enumerate(paragraphs):
            print(j,len(p.split()),len(p))
            try:
                p_audio = longtext2audio(kokoro_model,p)
                combined_audio += p_audio
            except Exception as e:
                print(f"Error occurred while processing paragraph {j}: {e}")
                print(p)
                return

        end=time()
        print(f"Time taken to process chapter: {end - start:.2f} seconds")
        print("Converting rate: {:.2f} characters/second".format(len(chapter_text) / (end - start)))

            # Export the merged audio with high quality VBR mp3
        print(f"Saving merged audio to: {output_mp3_path}")
        combined_audio.export(output_mp3_path, format="mp3", parameters=["-q:a", "0"])

    # Load metadata and cover path
    book_folder = os.path.dirname(chapter_file)
    metadata_path = os.path.join(book_folder, 'metadata.json')
    cover_path = os.path.join(book_folder, 'cover.jpg')
    with open(metadata_path, 'r', encoding='utf-8') as f:
        metadata = json.load(f)
    
    # Embed metadata and cover art
    audiofile = eyed3.load(output_mp3_path)
    if audiofile.tag is None:
        audiofile.initTag()
    chapter_num = int(base_name[2:])  # e.g., ch001 -> 1
    audiofile.tag.title = f"Chapter {chapter_num}"
    audiofile.tag.artist = ', '.join(metadata.get('authors', []))
    audiofile.tag.album = metadata.get('title', '')
    audiofile.tag.publisher = metadata.get('publisher', '')
    if 'publishedDate' in metadata and metadata['publishedDate']:
        audiofile.tag.recording_date = metadata['publishedDate']
    audiofile.tag.track_num = chapter_num
    if os.path.exists(cover_path):
        with open(cover_path, 'rb') as img_file:
            audiofile.tag.images.set(3, img_file.read(), 'image/jpeg')
    audiofile.tag.save()


def book2audio(folder_path,start_chapter=0, skip_if_exists=False):
    txt_files = []
    if os.path.isdir(folder_path):
        for f in os.listdir(folder_path):
            if f.lower().endswith('.txt'):
                txt_files.append(os.path.join(folder_path, f))
        txt_files.sort()
        print("Sorted list of txt files:")
        kokoro_model = get_kokoro_model()
    for i, txt_file in enumerate(txt_files):
            if i < start_chapter:
                continue
            print(txt_file.split('/')[-1],end=', ')
            chapter2audio(kokoro_model, txt_file, skip_if_exists=skip_if_exists)

def select_book_folder():
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()  # Hide the root window
    directory_path = filedialog.askdirectory(title="Select a book folder", initialdir="texts")
    return directory_path

if __name__ == "__main__":
    book_folder = select_book_folder()
    book2audio(book_folder,skip_if_exists=True)
