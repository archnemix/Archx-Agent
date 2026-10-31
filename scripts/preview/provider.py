"""Ephemeral runner test provider: real Ollama/Whisper/eSpeak/OCR; labelled image fixture.
Not a production inference server. Binds loopback; the app alone is tunnelled.
"""
import base64
import io
import json
import os
import subprocess
import tempfile
import threading
import requests
from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse, Response
from PIL import Image, ImageDraw

app = FastAPI()
MODELS = ['smollm2-135m-q6', 'qwen3:0.6b', 'tts-espeak', 'whisper-tiny', 'ocr-tesseract', 'image-fixture-not-generation']
whisper_lock = threading.Lock()
whisper_model = None

@app.get('/v1/models')
def models():
    return {'data': [{'id': m, 'owned_by': 'temporary GitHub runner'} for m in MODELS]}

@app.post('/v1/chat/completions')
async def chat(request: Request):
    body = await request.json()
    model = body.get('model')
    if model not in MODELS[:2] + ['ocr-tesseract']:
        raise HTTPException(400, 'Select a supported chat or OCR model.')
    if model == 'ocr-tesseract':
        images = [p['image_url']['url'] for m in body['messages'] if isinstance(m.get('content'), list) for p in m['content'] if p.get('type') == 'image_url']
        if not images or not images[0].startswith('data:image/'):
            raise HTTPException(400, 'Upload an image containing text; this is OCR, not general vision.')
        raw = base64.b64decode(images[0].split(',', 1)[1], validate=True)
        image = Image.open(io.BytesIO(raw))
        if image.width * image.height > 16000000:
            raise HTTPException(400, 'Image is too large.')
        with tempfile.TemporaryDirectory() as temp:
            file = os.path.join(temp, 'input.png')
            image.save(file)
            text = subprocess.check_output(['tesseract', file, 'stdout'], timeout=45).decode()
        return {'choices': [{'message': {'content': text or '(No readable text found)'}, 'finish_reason': 'stop'}]}
    payload = {'model': model, 'messages': body['messages'], 'stream': bool(body.get('stream')), 'options': {'num_predict': min(int(body.get('max_tokens') or 768), 1536), 'num_ctx': 4096, 'temperature': body.get('temperature', 0.7)}}
    if model.startswith('qwen3'):
        payload['think'] = True
    if not payload['stream']:
        result = requests.post('http://127.0.0.1:11434/api/chat', json=payload, timeout=180)
        result.raise_for_status()
        message = result.json()['message']
        return {'choices': [{'message': {'role': 'assistant', 'content': message.get('content', ''), 'reasoning_content': message.get('thinking', '')}, 'finish_reason': 'stop'}]}
    def stream():
        with requests.post('http://127.0.0.1:11434/api/chat', json=payload, stream=True, timeout=180) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                event = json.loads(line)
                if event.get('error'):
                    yield 'data: ' + json.dumps({'error': {'message': event['error']}}) + '\n\n'
                    return
                message = event.get('message', {})
                delta = {'content': message.get('content', '')}
                if message.get('thinking'):
                    delta['reasoning_content'] = message['thinking']
                yield 'data: ' + json.dumps({'model': model, 'choices': [{'delta': delta}]}) + '\n\n'
                if event.get('done'):
                    yield 'data: [DONE]\n\n'
    return StreamingResponse(stream(), media_type='text/event-stream')

@app.post('/v1/audio/speech')
async def speech(request: Request):
    body = await request.json()
    text = str(body.get('input', ''))[:4000]
    if not text.strip():
        raise HTTPException(400, 'Enter text to speak.')
    # Pass via stdin, never interpolate user text into a command.
    result = subprocess.run(['espeak-ng', '--stdout', '--stdin'], input=text.encode(), capture_output=True, timeout=45, check=True)
    return Response(result.stdout, media_type='audio/wav')

@app.post('/v1/audio/transcriptions')
def transcribe(file: UploadFile = File(...), model: str = Form(...)):
    global whisper_model
    raw = file.file.read(20 * 1024 * 1024 + 1)
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(413, 'Audio must be under 20 MB.')
    with whisper_lock:
        if whisper_model is None:
            from faster_whisper import WhisperModel
            whisper_model = WhisperModel('tiny', device='cpu', compute_type='int8', cpu_threads=2)
        segments, _ = whisper_model.transcribe(io.BytesIO(raw), beam_size=1)
        return {'text': ' '.join(segment.text for segment in segments).strip()}

@app.post('/v1/images/generations')
def image_fixture():
    image = Image.new('RGB', (640, 400), '#ece9e2')
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 40, 600, 360), outline='#55524b', width=2)
    draw.text((70, 165), 'ARCHX STUDIO - FIXED TEST IMAGE', fill='#25241f', font_size=24)
    draw.text((70, 210), 'Delivery test only. Not AI image generation.', fill='#55524b', font_size=18)
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return {'data': [{'b64_json': base64.b64encode(buffer.getvalue()).decode(), 'revised_prompt': 'Fixed test fixture; not generated from your prompt.'}]}
