# Voice Live API - FastAPI WebSocket Bridge

A FastAPI application that enables browser-based real-time audio conversations with Azure Voice Live API.

## Features

- 🎤 **Real-time audio streaming** from browser to Azure Voice Live API
- 🔊 **Bi-directional audio** - speak and hear responses in real-time
- 🌐 **Browser-native** - no plugins required, uses WebSocket and Web Audio API
- 🚀 **FastAPI backend** - high-performance async Python server
- 🎨 **Built-in test client** - simple web interface included

## Architecture

```
Browser Client (JavaScript)
    ↓ WebSocket (audio as base64 PCM16)
FastAPI Server (Python)
    ↓ Azure SDK
Azure Voice Live API
```

## Prerequisites

- Python 3.8+
- Azure Cognitive Services account with Voice Live API access
- Modern web browser (Chrome, Edge, Firefox, Safari)

## Installation

1. **Clone or navigate to the project directory**

2. **Install dependencies:**

```bash
pip install -r requirements.txt
```

3. **Configure environment variables:**

Copy `.env.example` to `.env` and fill in your Azure credentials:

```bash
cp .env.example .env
```

Edit `.env`:
```env
AZURE_VOICELIVE_ENDPOINT=your-resource-name.cognitiveservices.azure.com/voice-live/realtime
VOICELIVE_MODEL=gpt-4o-realtime-preview
VOICELIVE_VOICE=alloy
```

## Usage

### Start the server:

```bash
python main.py
```

Or using uvicorn directly:

```bash
uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

### Access the test client:

Open your browser to: **http://localhost:8080**

You'll see a simple test interface where you can:
1. Click "Start Conversation" to begin
2. Allow microphone access when prompted
3. Start speaking naturally
4. Hear the AI assistant's responses in real-time
5. Click "Stop Conversation" when done

## API Endpoints

### `GET /`
Serves the built-in HTML test client interface.

### `WS /ws`
WebSocket endpoint for real-time audio streaming.

**Client → Server Messages:**
```json
{
  "type": "audio",
  "audio": "base64_encoded_pcm16_audio"
}
```

```json
{
  "type": "interrupt"
}
```

```json
{
  "type": "stop"
}
```

**Server → Client Messages:**
```json
{
  "type": "session_ready",
  "session_id": "session_id_here"
}
```

```json
{
  "type": "audio",
  "audio": "base64_encoded_pcm16_audio"
}
```

```json
{
  "type": "speech_started"
}
```

```json
{
  "type": "speech_stopped"
}
```

```json
{
  "type": "response_started"
}
```

```json
{
  "type": "response_audio_done"
}
```

```json
{
  "type": "response_done"
}
```

```json
{
  "type": "error",
  "message": "error_message"
}
```

### `GET /health`
Health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "service": "voice-live-api-bridge"
}
```

## Audio Format

- **Sample Rate:** 24kHz
- **Format:** PCM16 (16-bit linear PCM)
- **Channels:** Mono (1 channel)
- **Encoding:** Base64 (for WebSocket transmission)

## Browser Client Implementation

To integrate this API into your own web application:

1. **Connect to WebSocket:**
```javascript
const ws = new WebSocket('ws://localhost:8080/ws');
```

2. **Capture audio from microphone:**
```javascript
const stream = await navigator.mediaDevices.getUserMedia({
  audio: {
    sampleRate: 24000,
    channelCount: 1,
    echoCancellation: true,
    noiseSuppression: true
  }
});
```

3. **Convert and send audio:**
```javascript
// Convert Float32 to PCM16
function convertFloat32ToPCM16(float32Array) {
  const pcm16 = new Int16Array(float32Array.length);
  for (let i = 0; i < float32Array.length; i++) {
    const s = Math.max(-1, Math.min(1, float32Array[i]));
    pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
  }
  return pcm16.buffer;
}

// Send to server
ws.send(JSON.stringify({
  type: 'audio',
  audio: btoa(String.fromCharCode(...new Uint8Array(pcm16Buffer)))
}));
```

4. **Receive and play audio:**
```javascript
ws.onmessage = async (event) => {
  const data = JSON.parse(event.data);
  if (data.type === 'audio') {
    // Decode base64 to PCM16
    const audioData = atob(data.audio);
    const pcm16 = new Int16Array(audioData.length);
    for (let i = 0; i < audioData.length; i++) {
      pcm16[i] = audioData.charCodeAt(i);
    }
    
    // Convert to Float32 and play
    const float32 = new Float32Array(pcm16.length);
    for (let i = 0; i < pcm16.length; i++) {
      float32[i] = pcm16[i] / (pcm16[i] < 0 ? 0x8000 : 0x7FFF);
    }
    
    // Create and play audio buffer
    const audioBuffer = audioContext.createBuffer(1, float32.length, 24000);
    audioBuffer.getChannelData(0).set(float32);
    const source = audioContext.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(audioContext.destination);
    source.start(0);
  }
};
```

## Configuration Options

### Voice Options

**OpenAI Voices:**
- `alloy` - Neutral, balanced
- `echo` - Male, clear
- `fable` - British accent
- `onyx` - Deep, authoritative
- `nova` - Energetic
- `shimmer` - Warm, friendly

**Azure Neural Voices:**
- `en-US-AvaNeural`
- `en-US-JennyNeural`
- `en-US-GuyNeural`
- Many more available (see Azure documentation)

### Model Options

- `gpt-4o-realtime-preview` (default)
- Check Azure documentation for other available models

## Troubleshooting

### "Server not configured" error
Make sure your `.env` file has valid `AZURE_VOICELIVE_ENDPOINT` and `AZURE_VOICELIVE_API_KEY` values.

### Microphone not working
- Check browser permissions
- Make sure you're using HTTPS (or localhost)
- Try a different browser

### Audio quality issues
- Check your internet connection
- Ensure sample rate is 24kHz
- Verify audio format is PCM16

### CORS errors
If accessing from a different origin, update the CORS configuration in `main.py`:
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://yourdomain.com"],  # Specify your domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## Development

### Running with hot reload:
```bash
uvicorn main:app --reload
```

### Enabling debug logging:
Set environment variable:
```bash
export LOGLEVEL=DEBUG
```

Or modify in code:
```python
logging.basicConfig(level=logging.DEBUG)
```

## Production Deployment

For production deployment:

1. **Use environment variables** instead of .env file
2. **Set specific CORS origins** (not "*")
3. **Use HTTPS** for WebSocket connections (wss://)
4. **Add authentication** if needed
5. **Consider rate limiting** and connection limits
6. **Use a production ASGI server** (uvicorn with workers, or hypercorn)

Example production startup:
```bash
uvicorn main:app --host 0.0.0.0 --port 8080 --workers 4 --ssl-keyfile=/path/to/key.pem --ssl-certfile=/path/to/cert.pem
```

## License

This project is provided as-is for demonstration purposes.

## Support

For Azure Voice Live API issues, refer to the official Azure documentation:
- https://learn.microsoft.com/azure/cognitive-services/

For FastAPI issues:
- https://fastapi.tiangolo.com/
