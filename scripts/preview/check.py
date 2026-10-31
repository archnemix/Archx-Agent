"""A short real-inference gate, not a fixture substitute for model capability."""
import base64
import io
import json
import os
from pathlib import Path
import time
import requests
from PIL import Image, ImageDraw
base = 'http://127.0.0.1:8090/v1'
for _ in range(90):
    try:
        if requests.get(base + '/models', timeout=2).ok:
            break
    except requests.RequestException:
        pass
    time.sleep(1)
else:
    raise SystemExit('Provider failed to start')
details = requests.post('http://127.0.0.1:11434/api/show', json={'model': 'smollm2-135m-q4'}, timeout=30)
details.raise_for_status()
metadata = details.json()['details']
assert metadata['quantization_level'] == 'Q4_K_M', metadata
output = Path(os.environ.get('RUNNER_TEMP', '/tmp')) / 'real-model-evidence'
output.mkdir(exist_ok=True)
(output / 'quantization.json').write_text(json.dumps(metadata, indent=2))
print('Verified actual loaded model metadata:', metadata, flush=True)
for model in ['smollm2-135m-q4', 'qwen3:0.6b']:
    response = requests.post(base + '/chat/completions', json={'model': model, 'messages': [{'role': 'user', 'content': 'What is 2 + 3? Answer briefly.'}], 'stream': False, 'max_tokens': 1024}, timeout=240)
    response.raise_for_status()
    message = response.json()['choices'][0]['message']
    assert message['content'].strip(), model + ' returned no answer'
    if model.startswith('qwen3'):
        assert message.get('reasoning_content', '').strip(), 'Qwen did not return actual thinking'
    print(model, 'actual inference passed', flush=True)
audio = requests.post(base + '/audio/speech', json={'model': 'tts-espeak', 'input': 'Hello. This is a real speech test.'}, timeout=45)
audio.raise_for_status()
assert audio.content.startswith(b'RIFF')
stt = requests.post(base + '/audio/transcriptions', data={'model': 'whisper-tiny'}, files={'file': ('speech.wav', audio.content, 'audio/wav')}, timeout=120)
stt.raise_for_status()
assert stt.json()['text'].strip()
image = Image.new('RGB', (640, 160), 'white')
ImageDraw.Draw(image).text((20, 50), 'ARCHX MEMORY TEST', fill='black', font_size=40)
buffer = io.BytesIO(); image.save(buffer, 'PNG')
ocr = requests.post(base + '/chat/completions', json={'model': 'ocr-tesseract', 'messages': [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()}}]}]}, timeout=60)
ocr.raise_for_status()
assert 'MEMORY' in ocr.json()['choices'][0]['message']['content']
fixture = requests.post(base + '/images/generations', json={'model': 'image-fixture-not-generation', 'prompt': 'test'}, timeout=20)
fixture.raise_for_status()
assert fixture.json()['data'][0]['b64_json']
print('Real speech synthesis, transcription and OCR passed; labelled fixed-image delivery passed.', flush=True)
