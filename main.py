import os
import sys
import asyncio
import base64
import json
from typing import Union, Optional, TYPE_CHECKING
import logging

# FastAPI imports
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

# Environment variable loading
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("Note: python-dotenv not installed. Using existing environment variables.")

# Azure VoiceLive SDK imports
from azure.core.credentials import AzureKeyCredential, TokenCredential
from azure.ai.voicelive.aio import connect
from azure.ai.voicelive.models import ServerEventType

if TYPE_CHECKING:
    from azure.ai.voicelive.aio import VoiceLiveConnection

from azure.ai.voicelive.models import (
    RequestSession,
    ServerVad,
    AzureStandardVoice,
    Modality,
    InputAudioFormat,
    OutputAudioFormat
)

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(title="Voice Live API - WebSocket Bridge")

# Configure CORS for browser clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Configuration from environment
AZURE_VOICELIVE_ENDPOINT = os.environ.get("AZURE_VOICELIVE_ENDPOINT")
AZURE_VOICELIVE_API_KEY = os.environ.get("AZURE_VOICELIVE_API_KEY")
VOICELIVE_MODEL = os.environ.get("VOICELIVE_MODEL", "gpt-4o-realtime-preview")
VOICELIVE_VOICE = os.environ.get("VOICELIVE_VOICE", "alloy")
VOICELIVE_INSTRUCTIONS = os.environ.get(
    "VOICELIVE_INSTRUCTIONS",
    "You are a helpful AI assistant. Respond naturally and conversationally. Keep your responses concise but engaging."
)


class SessionConfig(BaseModel):
    """Configuration for a voice session."""
    voice: Optional[str] = VOICELIVE_VOICE
    instructions: Optional[str] = VOICELIVE_INSTRUCTIONS
    model: Optional[str] = VOICELIVE_MODEL


class WebSocketVoiceSession:
    """
    Manages a WebSocket session bridging browser client and Azure Voice Live API.
    
    Architecture:
    - Browser sends audio (base64 PCM16 24kHz) via WebSocket
    - Audio is forwarded to Azure Voice Live API
    - Azure responses are streamed back to browser
    """

    def __init__(
        self,
        websocket: WebSocket,
        endpoint: str,
        credential: Union[AzureKeyCredential, TokenCredential],
        model: str,
        voice: str,
        instructions: str,
    ):
        self.websocket = websocket
        self.endpoint = endpoint
        self.credential = credential
        self.model = model
        self.voice = voice
        self.instructions = instructions
        self.connection: Optional["VoiceLiveConnection"] = None
        self.session_ready = False
        self.active = True

    async def start(self):
        """Start the voice session and process events."""
        try:
            logger.info(f"Starting WebSocket voice session with model {self.model}")

            # Connect to Azure Voice Live API
            async with connect(
                endpoint=self.endpoint,
                credential=self.credential,
                model=self.model,
                connection_options={
                    "max_msg_size": 10 * 1024 * 1024,
                    "heartbeat": 20,
                    "timeout": 20,
                },
            ) as connection:
                self.connection = connection

                # Configure session
                await self._setup_session()

                # Create tasks for bidirectional communication
                receive_task = asyncio.create_task(self._receive_from_browser())
                process_task = asyncio.create_task(self._process_azure_events())

                # Wait for either task to complete (or fail)
                done, pending = await asyncio.wait(
                    [receive_task, process_task],
                    return_when=asyncio.FIRST_COMPLETED
                )

                # Cancel pending tasks
                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

                # Check for exceptions in completed tasks
                for task in done:
                    if task.exception():
                        raise task.exception()

        except WebSocketDisconnect:
            logger.info("Browser WebSocket disconnected")
        except Exception as e:
            logger.error(f"Session error: {e}")
            try:
                await self.websocket.send_json({
                    "type": "error",
                    "message": str(e)
                })
            except:
                pass
        finally:
            self.active = False
            logger.info("Voice session ended")

    async def _setup_session(self):
        """Configure the Azure Voice Live session."""
        logger.info("Setting up Azure Voice Live session...")

        # Create voice configuration
        voice_config: Union[AzureStandardVoice, str]
        if self.voice.startswith("en-") or "-" in self.voice:
            # Azure voice
            voice_config = AzureStandardVoice(name=self.voice, type="azure-standard")
        else:
            # OpenAI voice (alloy, echo, fable, onyx, nova, shimmer)
            voice_config = self.voice

        # Create turn detection configuration
        turn_detection_config = ServerVad(
            threshold=0.5,
            prefix_padding_ms=300,
            silence_duration_ms=500
        )

        # Create session configuration
        session_config = RequestSession(
            modalities=[Modality.TEXT, Modality.AUDIO],
            instructions=self.instructions,
            voice=voice_config,
            input_audio_format=InputAudioFormat.PCM16,
            output_audio_format=OutputAudioFormat.PCM16,
            turn_detection=turn_detection_config,
        )

        assert self.connection is not None
        await self.connection.session.update(session=session_config)
        logger.info("Azure session configured")

    async def _receive_from_browser(self):
        """Receive audio data from browser WebSocket."""
        try:
            while self.active:
                # Receive message from browser
                data = await self.websocket.receive_json()
                
                message_type = data.get("type")
                
                if message_type == "audio":
                    # Audio data from browser (base64 encoded PCM16)
                    audio_base64 = data.get("audio")
                    if audio_base64 and self.connection:
                        # Forward to Azure Voice Live
                        await self.connection.input_audio_buffer.append(audio=audio_base64)
                        
                elif message_type == "interrupt":
                    # User wants to interrupt the assistant
                    logger.info("Interrupt requested by browser")
                    if self.connection:
                        await self.connection.response.cancel()
                        
                elif message_type == "stop":
                    # Client wants to stop the session
                    logger.info("Stop requested by browser")
                    self.active = False
                    break
                    
        except WebSocketDisconnect:
            logger.info("Browser disconnected during receive")
            self.active = False
        except Exception as e:
            logger.error(f"Error receiving from browser: {e}")
            self.active = False

    async def _process_azure_events(self):
        """Process events from Azure Voice Live API."""
        try:
            assert self.connection is not None
            
            async for event in self.connection:
                if not self.active:
                    break
                    
                await self._handle_azure_event(event)
                
        except Exception as e:
            logger.error(f"Error processing Azure events: {e}")
            self.active = False

    async def _handle_azure_event(self, event):
        """Handle events from Azure Voice Live and forward to browser."""
        logger.debug(f"Azure event: {event.type}")

        try:
            if event.type == ServerEventType.SESSION_UPDATED:
                logger.info(f"Session ready: {event.session.id}")
                self.session_ready = True
                await self.websocket.send_json({
                    "type": "session_ready",
                    "session_id": event.session.id
                })

            elif event.type == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED:
                logger.info("User speech started")
                await self.websocket.send_json({
                    "type": "speech_started"
                })

            elif event.type == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STOPPED:
                logger.info("User speech stopped")
                await self.websocket.send_json({
                    "type": "speech_stopped"
                })

            elif event.type == ServerEventType.RESPONSE_CREATED:
                logger.info("Response created")
                await self.websocket.send_json({
                    "type": "response_started"
                })

            elif event.type == ServerEventType.RESPONSE_AUDIO_DELTA:
                # Stream audio response to browser
                logger.debug("Sending audio delta to browser")
                audio_base64 = base64.b64encode(event.delta).decode("utf-8")
                await self.websocket.send_json({
                    "type": "audio",
                    "audio": audio_base64
                })

            elif event.type == ServerEventType.RESPONSE_AUDIO_DONE:
                logger.info("Response audio done")
                await self.websocket.send_json({
                    "type": "response_audio_done"
                })

            elif event.type == ServerEventType.RESPONSE_DONE:
                logger.info("Response complete")
                await self.websocket.send_json({
                    "type": "response_done"
                })

            elif event.type == ServerEventType.ERROR:
                logger.error(f"Azure error: {event.error.message}")
                await self.websocket.send_json({
                    "type": "error",
                    "message": event.error.message
                })

        except Exception as e:
            logger.error(f"Error handling Azure event: {e}")


@app.get("/")
async def root():
    """Serve a simple test page."""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Voice Live API - Browser Client</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                max-width: 800px;
                margin: 50px auto;
                padding: 20px;
                background: #f5f5f5;
            }
            .container {
                background: white;
                padding: 30px;
                border-radius: 10px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }
            h1 {
                color: #333;
                text-align: center;
            }
            .controls {
                display: flex;
                justify-content: center;
                gap: 10px;
                margin: 20px 0;
            }
            button {
                padding: 15px 30px;
                font-size: 16px;
                border: none;
                border-radius: 5px;
                cursor: pointer;
                transition: background 0.3s;
            }
            #startBtn {
                background: #4CAF50;
                color: white;
            }
            #startBtn:hover {
                background: #45a049;
            }
            #startBtn:disabled {
                background: #ccc;
                cursor: not-allowed;
            }
            #stopBtn {
                background: #f44336;
                color: white;
            }
            #stopBtn:hover {
                background: #da190b;
            }
            #stopBtn:disabled {
                background: #ccc;
                cursor: not-allowed;
            }
            #status {
                padding: 15px;
                margin: 20px 0;
                border-radius: 5px;
                text-align: center;
                font-weight: bold;
            }
            .status-disconnected {
                background: #ffebee;
                color: #c62828;
            }
            .status-connecting {
                background: #fff3e0;
                color: #ef6c00;
            }
            .status-ready {
                background: #e8f5e9;
                color: #2e7d32;
            }
            .status-speaking {
                background: #e3f2fd;
                color: #1565c0;
            }
            #log {
                background: #f9f9f9;
                border: 1px solid #ddd;
                border-radius: 5px;
                padding: 15px;
                height: 300px;
                overflow-y: auto;
                font-family: 'Courier New', monospace;
                font-size: 12px;
            }
            .log-entry {
                margin: 5px 0;
                padding: 5px;
                border-left: 3px solid #ccc;
                padding-left: 10px;
            }
            .log-info {
                border-left-color: #2196F3;
            }
            .log-error {
                border-left-color: #f44336;
                color: #c62828;
            }
            .log-success {
                border-left-color: #4CAF50;
                color: #2e7d32;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🎤 Voice Live API Test Client</h1>
            
            <div id="status" class="status-disconnected">
                Disconnected
            </div>
            
            <div class="controls">
                <button id="startBtn">Start Conversation</button>
                <button id="stopBtn" disabled>Stop Conversation</button>
            </div>
            
            <h3>Activity Log:</h3>
            <div id="log"></div>
        </div>

        <script>
            let ws = null;
            let audioContext = null;
            let mediaStream = null;
            let audioWorkletNode = null;
            let isRecording = false;

            const startBtn = document.getElementById('startBtn');
            const stopBtn = document.getElementById('stopBtn');
            const statusDiv = document.getElementById('status');
            const logDiv = document.getElementById('log');

            function updateStatus(message, className) {
                statusDiv.textContent = message;
                statusDiv.className = className;
            }

            function addLog(message, type = 'info') {
                const entry = document.createElement('div');
                entry.className = `log-entry log-${type}`;
                entry.textContent = `${new Date().toLocaleTimeString()}: ${message}`;
                logDiv.appendChild(entry);
                logDiv.scrollTop = logDiv.scrollHeight;
            }

            async function startConversation() {
                try {
                    addLog('Requesting microphone access...', 'info');
                    
                    // Get microphone access (let browser use its native sample rate)
                    mediaStream = await navigator.mediaDevices.getUserMedia({
                        audio: {
                            channelCount: 1,
                            echoCancellation: true,
                            noiseSuppression: true,
                            autoGainControl: true
                        }
                    });
                    
                    addLog('Microphone access granted', 'success');
                    
                    // Create audio context with browser's default sample rate
                    audioContext = new AudioContext();
                    addLog(`Audio context sample rate: ${audioContext.sampleRate}Hz`, 'info');
                    
                    const source = audioContext.createMediaStreamSource(mediaStream);
                    
                    // Create processor for audio capture
                    const processor = audioContext.createScriptProcessor(4096, 1, 1);
                    source.connect(processor);
                    processor.connect(audioContext.destination);
                    
                    // Connect to WebSocket
                    updateStatus('Connecting...', 'status-connecting');
                    addLog('Connecting to server...', 'info');
                    
                    ws = new WebSocket(`ws://${window.location.host}/ws`);
                    
                    ws.onopen = () => {
                        addLog('WebSocket connected', 'success');
                        updateStatus('Connected - Waiting for session...', 'status-connecting');
                    };
                    
                    ws.onmessage = async (event) => {
                        const data = JSON.parse(event.data);
                        handleServerMessage(data);
                    };
                    
                    ws.onerror = (error) => {
                        addLog(`WebSocket error: ${error}`, 'error');
                    };
                    
                    ws.onclose = () => {
                        addLog('WebSocket disconnected', 'info');
                        stopConversation();
                    };
                    
                    // Process audio and send to server
                    processor.onaudioprocess = (e) => {
                        if (!isRecording || !ws || ws.readyState !== WebSocket.OPEN) return;
                        
                        const inputData = e.inputBuffer.getChannelData(0);
                        
                        // Resample to 24kHz if needed
                        const resampled = resampleAudio(inputData, audioContext.sampleRate, 24000);
                        
                        const pcm16 = convertFloat32ToPCM16(resampled);
                        const base64Audio = arrayBufferToBase64(pcm16);
                        
                        ws.send(JSON.stringify({
                            type: 'audio',
                            audio: base64Audio
                        }));
                    };
                    
                    isRecording = true;
                    startBtn.disabled = true;
                    stopBtn.disabled = false;
                    
                } catch (error) {
                    addLog(`Error starting conversation: ${error.message}`, 'error');
                    updateStatus('Error - See log', 'status-disconnected');
                    stopConversation();
                }
            }

            function stopConversation() {
                isRecording = false;
                
                if (ws) {
                    ws.send(JSON.stringify({ type: 'stop' }));
                    ws.close();
                    ws = null;
                }
                
                if (mediaStream) {
                    mediaStream.getTracks().forEach(track => track.stop());
                    mediaStream = null;
                }
                
                if (audioContext) {
                    audioContext.close();
                    audioContext = null;
                }
                
                startBtn.disabled = false;
                stopBtn.disabled = true;
                updateStatus('Disconnected', 'status-disconnected');
                addLog('Conversation stopped', 'info');
            }

            async function handleServerMessage(data) {
                switch(data.type) {
                    case 'session_ready':
                        addLog(`Session ready: ${data.session_id}`, 'success');
                        updateStatus('Ready - Start speaking!', 'status-ready');
                        break;
                        
                    case 'speech_started':
                        addLog('Listening...', 'info');
                        updateStatus('Listening...', 'status-speaking');
                        break;
                        
                    case 'speech_stopped':
                        addLog('Processing your speech...', 'info');
                        updateStatus('Processing...', 'status-connecting');
                        break;
                        
                    case 'response_started':
                        addLog('Assistant responding...', 'info');
                        updateStatus('Assistant speaking...', 'status-speaking');
                        break;
                        
                    case 'audio':
                        // Play audio response
                        await playAudioChunk(data.audio);
                        break;
                        
                    case 'response_audio_done':
                        addLog('Assistant finished speaking', 'success');
                        updateStatus('Ready - Start speaking!', 'status-ready');
                        break;
                        
                    case 'response_done':
                        addLog('Response complete', 'success');
                        break;
                        
                    case 'error':
                        addLog(`Error: ${data.message}`, 'error');
                        updateStatus('Error - See log', 'status-disconnected');
                        break;
                }
            }

            // Audio format conversion and resampling
            function resampleAudio(audioData, sourceSampleRate, targetSampleRate) {
                if (sourceSampleRate === targetSampleRate) {
                    return audioData;
                }
                
                const ratio = sourceSampleRate / targetSampleRate;
                const newLength = Math.round(audioData.length / ratio);
                const result = new Float32Array(newLength);
                
                for (let i = 0; i < newLength; i++) {
                    const srcIndex = i * ratio;
                    const srcIndexInt = Math.floor(srcIndex);
                    const srcIndexFrac = srcIndex - srcIndexInt;
                    
                    // Linear interpolation
                    if (srcIndexInt + 1 < audioData.length) {
                        result[i] = audioData[srcIndexInt] * (1 - srcIndexFrac) + 
                                   audioData[srcIndexInt + 1] * srcIndexFrac;
                    } else {
                        result[i] = audioData[srcIndexInt];
                    }
                }
                
                return result;
            }
            
            function convertFloat32ToPCM16(float32Array) {
                const pcm16 = new Int16Array(float32Array.length);
                for (let i = 0; i < float32Array.length; i++) {
                    const s = Math.max(-1, Math.min(1, float32Array[i]));
                    pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
                }
                return pcm16.buffer;
            }

            function arrayBufferToBase64(buffer) {
                const bytes = new Uint8Array(buffer);
                let binary = '';
                for (let i = 0; i < bytes.byteLength; i++) {
                    binary += String.fromCharCode(bytes[i]);
                }
                return btoa(binary);
            }

            function base64ToArrayBuffer(base64) {
                const binaryString = atob(base64);
                const bytes = new Uint8Array(binaryString.length);
                for (let i = 0; i < binaryString.length; i++) {
                    bytes[i] = binaryString.charCodeAt(i);
                }
                return bytes.buffer;
            }

            // Audio playback queue
            const audioQueue = [];
            let isPlaying = false;

            async function playAudioChunk(base64Audio) {
                const arrayBuffer = base64ToArrayBuffer(base64Audio);
                audioQueue.push(arrayBuffer);
                
                if (!isPlaying) {
                    playNextChunk();
                }
            }

            async function playNextChunk() {
                if (audioQueue.length === 0) {
                    isPlaying = false;
                    return;
                }
                
                isPlaying = true;
                const arrayBuffer = audioQueue.shift();
                
                if (!audioContext) {
                    audioContext = new AudioContext();
                }
                
                // Convert PCM16 to Float32
                const pcm16 = new Int16Array(arrayBuffer);
                const float32 = new Float32Array(pcm16.length);
                for (let i = 0; i < pcm16.length; i++) {
                    float32[i] = pcm16[i] / (pcm16[i] < 0 ? 0x8000 : 0x7FFF);
                }
                
                // Resample from 24kHz to audio context sample rate if needed
                const resampled = resampleAudio(float32, 24000, audioContext.sampleRate);
                
                // Create audio buffer
                const audioBuffer = audioContext.createBuffer(1, resampled.length, audioContext.sampleRate);
                audioBuffer.getChannelData(0).set(resampled);
                
                // Play audio
                const source = audioContext.createBufferSource();
                source.buffer = audioBuffer;
                source.connect(audioContext.destination);
                
                source.onended = () => {
                    playNextChunk();
                };
                
                source.start(0);
            }

            startBtn.addEventListener('click', startConversation);
            stopBtn.addEventListener('click', stopConversation);
            
            addLog('Ready to start. Click "Start Conversation" to begin.', 'info');
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for browser clients."""
    await websocket.accept()
    logger.info("Browser WebSocket connection accepted")

    # Validate configuration
    if not AZURE_VOICELIVE_ENDPOINT or not AZURE_VOICELIVE_API_KEY:
        await websocket.send_json({
            "type": "error",
            "message": "Server not configured. Missing Azure credentials."
        })
        await websocket.close()
        return

    # Create endpoint URL
    endpoint = f"wss://{AZURE_VOICELIVE_ENDPOINT}?api-version=2024-02-15&model={VOICELIVE_MODEL}"
    credential = AzureKeyCredential(AZURE_VOICELIVE_API_KEY)

    # Create and start session
    session = WebSocketVoiceSession(
        websocket=websocket,
        endpoint=endpoint,
        credential=credential,
        model=VOICELIVE_MODEL,
        voice=VOICELIVE_VOICE,
        instructions=VOICELIVE_INSTRUCTIONS,
    )

    await session.start()


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "voice-live-api-bridge"
    }


if __name__ == "__main__":
    import uvicorn
    
    # Validate environment
    if not AZURE_VOICELIVE_ENDPOINT or not AZURE_VOICELIVE_API_KEY:
        print("❌ Error: Missing required environment variables:")
        print("   - AZURE_VOICELIVE_ENDPOINT")
        print("   - AZURE_VOICELIVE_API_KEY")
        print("\nPlease set these in your .env file or environment.")
        sys.exit(1)
    
    print("🎙️  Voice Live API - FastAPI WebSocket Bridge")
    print("=" * 60)
    print(f"Model: {VOICELIVE_MODEL}")
    print(f"Voice: {VOICELIVE_VOICE}")
    print(f"Endpoint: {AZURE_VOICELIVE_ENDPOINT}")
    print("=" * 60)
    print("\n🌐 Starting server...")
    print("   Local: http://localhost:8080")
    print("   Test page: http://localhost:8080")
    print("   WebSocket: ws://localhost:8080/ws")
    print("\nPress CTRL+C to stop")
    print("=" * 60 + "\n")
    
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
