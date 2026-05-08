import onnxruntime as rt
from kokoro_onnx import Kokoro
from time import time

print(rt.get_available_providers())
import soundfile as sf
def get_kokoro_gpu():
    providers = [
        ('CUDAExecutionProvider', {
            'device_id': 0,
            'arena_extend_strategy': 'kNextPowerOfTwo',
            # 'gpu_mem_limit':  3 * 1024 * 1024 * 1024,
            'cudnn_conv_algo_search': 'DEFAULT',
            'do_copy_in_default_stream': True,
        }),
        # 'CPUExecutionProvider',
    ]
    kokoro_onnx_path = "kokoro_models/kokoro-v0_19.onnx"
    voice_json_path = "kokoro_models/voices.json"
    model = Kokoro(kokoro_onnx_path, voice_json_path)
    model.sess = rt.InferenceSession(kokoro_onnx_path, providers=providers)
    print(f"Kokoro initialized with providers: {model.sess.get_providers()}")
    return model

kokoro_model = get_kokoro_gpu()
start_time = time()
para = "“That is not yet possible, Sariputta. A finished set of precepts cannot be created in one day or by one person. In the first years of the sangha, we didn’t have any precepts."
para = " Gradually, because of shortcomings and errors committed by brothers, we have created precepts. Now we have one hundred twenty precepts. That number will increase over time. The precepts are not yet complete, Sariputta. I believe the number may rise to two hundred or more"
print(f"Input text length: {len(para)} characters")
# samples, sample_rate = kokoro_model.create(para, voice="af_bella", speed=0.8, lang="en-us")
# temp_wav_path = "temp_chunk.wav"
# sf.write(temp_wav_path, samples, sample_rate)
# end_time = time()
# print(f"Time taken for inference: {end_time - start_time:.2f} seconds")

# CPU 20.24s - 28s