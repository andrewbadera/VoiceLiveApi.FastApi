# Quick Start Guide

## 🚀 Getting Started in 3 Steps

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment
Copy the example environment file and edit with your Azure credentials:
```bash
cp .env.example .env
```

Edit `.env` and add your Azure credentials:
```env
AZURE_VOICELIVE_ENDPOINT=your-resource.cognitiveservices.azure.com/voice-live/realtime
AZURE_VOICELIVE_API_KEY=your-api-key-here
```

### 3. Run the Server
```bash
python main.py
```

Or using the startup script:
```bash
python start.py
```

Or using uvicorn directly:
```bash
uvicorn main:app --reload
```

## 🌐 Access the Application

Once the server is running:

- **Test Interface**: http://localhost:8080
- **WebSocket Endpoint**: ws://localhost:8080/ws
- **Health Check**: http://localhost:8080/health

## 🎤 Using the Test Interface

1. Open http://localhost:8080 in your browser
2. Click **"Start Conversation"**
3. Allow microphone access when prompted
4. Start speaking naturally
5. The AI assistant will respond in real-time
6. Click **"Stop Conversation"** when done

## 📋 What Changed from Original main.py

### Before (Desktop Application)
- ❌ Required PyAudio for local audio capture/playback
- ❌ Desktop-only (couldn't be accessed from browser)
- ❌ Required command-line arguments
- ❌ Single-user only

### After (FastAPI Web Service)
- ✅ No PyAudio needed (audio handled by browser)
- ✅ Web-accessible from any device with a browser
- ✅ Environment variable configuration
- ✅ Multi-user capable (each WebSocket is a separate session)
- ✅ Built-in test client web interface
- ✅ RESTful health check endpoint
- ✅ CORS enabled for cross-origin requests

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Browser Client                          │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  - Microphone Capture (Web Audio API)                │   │
│  │  - Audio Format Conversion (Float32 → PCM16)         │   │
│  │  - WebSocket Communication                           │   │
│  │  - Audio Playback (Web Audio API)                    │   │
│  └──────────────────────────────────────────────────────┘   │
└───────────────────────┬─────────────────────────────────────┘
                        │ WebSocket (JSON + Base64 Audio)
                        │
┌───────────────────────▼─────────────────────────────────────┐
│                   FastAPI Server (main.py)                   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  WebSocketVoiceSession Class                         │   │
│  │  - Accepts browser WebSocket connections             │   │
│  │  - Manages bidirectional audio streaming             │   │
│  │  - Forwards audio to Azure Voice Live API            │   │
│  │  - Streams responses back to browser                 │   │
│  └──────────────────────────────────────────────────────┘   │
└───────────────────────┬─────────────────────────────────────┘
                        │ Azure SDK (WebSocket)
                        │
┌───────────────────────▼─────────────────────────────────────┐
│                Azure Voice Live API                          │
│  - Speech-to-Text                                            │
│  - GPT-4 Realtime Processing                                 │
│  - Text-to-Speech                                            │
└──────────────────────────────────────────────────────────────┘
```

## 🔧 Key Classes and Functions

### `WebSocketVoiceSession`
Main class that manages a voice conversation session between browser and Azure.

**Key Methods:**
- `start()` - Initializes the session and starts bidirectional communication
- `_setup_session()` - Configures Azure Voice Live session
- `_receive_from_browser()` - Receives audio from browser WebSocket
- `_process_azure_events()` - Processes events from Azure Voice Live API
- `_handle_azure_event()` - Handles specific event types and forwards to browser

### FastAPI Endpoints

#### `GET /`
Serves the built-in HTML/JavaScript test client

#### `WS /ws`
WebSocket endpoint for real-time audio streaming

#### `GET /health`
Simple health check endpoint

## 🎵 Audio Pipeline

### Browser → Server → Azure
1. Browser captures microphone (Float32, 24kHz, mono)
2. JavaScript converts Float32 → PCM16
3. JavaScript encodes PCM16 → Base64
4. WebSocket sends JSON: `{"type": "audio", "audio": "base64..."}`
5. Server receives and decodes
6. Server forwards to Azure Voice Live API

### Azure → Server → Browser
1. Azure sends PCM16 audio chunks
2. Server encodes to Base64
3. Server sends JSON: `{"type": "audio", "audio": "base64..."}`
4. Browser decodes Base64 → PCM16
5. Browser converts PCM16 → Float32
6. Browser plays audio using Web Audio API

## 🔐 Security Considerations

### For Production:
1. **HTTPS/WSS**: Use SSL/TLS certificates
2. **CORS**: Restrict `allow_origins` to your domain
3. **Authentication**: Add user authentication
4. **Rate Limiting**: Prevent abuse
5. **Environment Variables**: Never commit `.env` files
6. **API Keys**: Rotate regularly

## 🐛 Troubleshooting

### Server won't start
- Check that all dependencies are installed: `pip list`
- Verify `.env` file exists and has correct values
- Check port 8080 is not already in use

### Browser can't connect
- Verify server is running
- Check browser console for errors
- Try different browser
- Check firewall settings

### No audio in browser
- Check microphone permissions
- Verify sample rate is 24kHz
- Check browser console for errors
- Try headphones to avoid echo

### Azure connection errors
- Verify `AZURE_VOICELIVE_ENDPOINT` is correct
- Check `AZURE_VOICELIVE_API_KEY` is valid
- Ensure model name is correct
- Check Azure service status

## 📚 Additional Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Azure Voice Live API Documentation](https://learn.microsoft.com/azure/cognitive-services/)
- [WebSocket Protocol](https://developer.mozilla.org/en-US/docs/Web/API/WebSocket)
- [Web Audio API](https://developer.mozilla.org/en-US/docs/Web/API/Web_Audio_API)

## 💡 Next Steps

### Enhancements you could add:
1. **User Authentication** - Add login system
2. **Session Management** - Save conversation history
3. **Multiple Models** - Let users choose different AI models
4. **Voice Selection UI** - Dropdown to select voices
5. **Transcription Display** - Show text of conversation
6. **Recording** - Save conversations
7. **Custom Instructions** - Let users customize AI behavior
8. **Mobile App** - React Native or Flutter client
9. **Load Balancing** - Scale to multiple servers
10. **Monitoring** - Add telemetry and logging
