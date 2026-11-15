"""Offline Bangla Xiaozhi-compatible HTTPS + WebSocket gateway."""
import asyncio
from contextlib import asynccontextmanager, suppress
import hmac
import ipaddress
import json
import logging
from pathlib import Path
import struct
import time
import uuid
import sys
import httpx

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from audio import OpusInput, OpusOutput, Utterances
from engine import Engine
from conversation_activity import keep_session_active
from groq_llm import model_name
from groq_llm import GroqError
from expression import SpokenPhrase
from speech_lookahead import lookahead_audio

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "private/config.json").read_text())
LOGGER = logging.getLogger("deskter")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
MODEL = None
DEVICE_LOCK = asyncio.Lock()
ACTIVE_CONVERSATION = None


class LocalNtp(asyncio.DatagramProtocol):
    """LAN-only clock source, so a cold ESP32 boot does not need Internet SNTP."""
    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, packet, peer):
        if len(packet) < 48 or not ipaddress.ip_address(peer[0]).is_private:
            return
        seconds = time.time() + 2208988800
        stamp = struct.pack("!II", int(seconds), int(seconds % 1 * 2**32))
        response = bytearray(48)
        response[0:4] = bytes([0x24, 2, 6, 0xEC])  # NTP v4 server, stratum 2.
        response[12:16] = b"LOCL"
        response[16:24] = stamp
        response[24:32] = packet[40:48]
        response[32:40] = stamp
        response[40:48] = stamp
        self.transport.sendto(response, peer)


@asynccontextmanager
async def lifespan(app):
    global MODEL
    LOGGER.info("Loading local speech models; LLM provider=%s",CONFIG.get('llm_provider','groq'))
    MODEL = await asyncio.to_thread(Engine, CONFIG)
    if MODEL.speech.backend in ('mithi',):
        # The worker already loaded and encoded its references. A full CPU
        # generation here needlessly blocks device reconnection for minutes.
        async with httpx.AsyncClient(trust_env=False,timeout=5) as client:
            response=await client.get(MODEL.speech.voice.url+'/health')
            response.raise_for_status()
            speech_health=response.json()
            if not speech_health.get('ready'):raise RuntimeError('Local speech worker is not ready')
            MODEL.speech.voice.device=speech_health.get('device','unknown')
    else:
        await asyncio.to_thread(MODEL.synthesize, "হ্যালো, আমি ডেস্কটার।")
    LOGGER.info("Checking language model: %s",model_name(CONFIG))
    async for _ in MODEL.sentences([{"role":"user", "content":"হ্যালো"}]):
        pass
    LOGGER.info("Local speech models ready")
    ntp = None
    try:
        ntp, _ = await asyncio.get_running_loop().create_datagram_endpoint(LocalNtp, local_addr=("0.0.0.0", 8123))
        LOGGER.info("Offline LAN clock listening on UDP 8123")
    except OSError as error:
        LOGGER.warning("LAN clock unavailable (%s); board can use saved USB-provisioned time", type(error).__name__)
    from dashboard import create_dashboard
    import uvicorn
    panel = uvicorn.Server(uvicorn.Config(create_dashboard(sys.modules[__name__]),
        host='127.0.0.1', port=8787, log_level='warning', access_log=False,
        lifespan='off', limit_concurrency=12))
    panel.capture_signals = lambda: suppress()
    panel_task = asyncio.create_task(panel.serve())
    LOGGER.info('Deskter dashboard: http://127.0.0.1:8787')
    try:
        yield
    finally:
        panel.should_exit = True
        await panel_task
        if ntp:
            ntp.close()
        await MODEL.close()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)


def authorized(headers):
    try:
        uuid.UUID(headers.get("client-id", ""), version=4)
    except ValueError:
        return False
    return (headers.get("device-id", "").lower() == CONFIG["allowed_device_mac"]
            and hmac.compare_digest(headers.get("authorization", ""), "Bearer " + CONFIG["device_token"]))


@app.get("/health")
async def health():
    return {"ready": MODEL is not None, "offline": CONFIG.get('llm_provider','groq')!='groq', "language": "bn",
            "languages": ["bn", "en", "bn-en"], "emotion_tags": True,
            "llm": model_name(CONFIG), 'llm_provider':CONFIG.get('llm_provider','groq'),
            'tts':CONFIG.get('tts_backend','mithi'),
            'tts_device':getattr(MODEL.speech.voice,'device','cpu') if MODEL else None,
            "device_connected": DEVICE_LOCK.locked()}


@app.post("/xiaozhi/ota/")
async def configuration(request: Request):
    if not authorized(request.headers):
        raise HTTPException(401, "Device authentication required")
    base = f"wss://{CONFIG['host']}:{CONFIG['port']}"
    return {"websocket": {"url": base + "/xiaozhi/v1/", "token": CONFIG["device_token"], "version": 1},
            "server_time": {"timestamp": int(time.time()*1000), "timezone_offset": 0},
            "firmware": {"version": "1.0.0", "url": ""}}


class Conversation:
    def __init__(self, socket):
        self.socket = socket
        self.id = str(uuid.uuid4())
        self.decoder = OpusInput()
        self.segmenter = Utterances(CONFIG)
        self.listening = self.busy = False
        self.task = None
        self.history = []
        self.packets_in = self.packets_out = self.turns = 0

    async def message(self, kind, **fields):
        await self.socket.send_json({"type": kind, "session_id": self.id, **fields})

    async def respond(self, audio):
        began = time.perf_counter()
        metrics = {"audio_s": round(len(audio)/16000, 3), "endpoint_silence_ms": CONFIG.get("silence_ms", 500),
                   'llm_model':model_name(CONFIG), 'llm_provider':CONFIG.get('llm_provider','groq'),
                   'tts_backend':CONFIG.get('tts_backend','mithi'),
                   'utc_ms':int(time.time()*1000), 'output_bitrate':CONFIG.get('output_bitrate',48000),
                   'prefill_frames':CONFIG.get('playback_prefill_frames',3)}
        try:
            text = await asyncio.to_thread(MODEL.transcribe, audio)
            metrics["asr_ms"] = round((time.perf_counter()-began)*1000)
            metrics.update(MODEL.last_asr_route)
            if not text:
                return
            if CONFIG.get("log_transcripts"):
                LOGGER.info("User: %s", text)
            self.history.append({"role": "user", "content": MODEL.heard_message(text)})
            await self.message("stt", text=text)
            texts, sounds = asyncio.Queue(4), asyncio.Queue(4)
            reply = []
            speech_finished=asyncio.Event()

            async def generate():
                route=MODEL.last_asr_route.get('asr_route','bangla')
                hint='en' if route=='english' else 'bn-en' if 'alternative' in route else 'bn'
                try:
                    async for phrase in MODEL.reply_phrases(self.history, metrics, language_hint=hint):
                        if not phrase.text.strip(" .!?।\n"):
                            continue
                        reply.append(phrase.text)
                        metrics.setdefault('tts_planned_words',[]).append(len(phrase.text.split()))
                        await texts.put(phrase)
                except GroqError as error:
                    # Bounded primary/fallback attempts already failed. Give an
                    # audible explanation and reopen listening, rather than silence.
                    metrics['llm_unavailable']=True
                    LOGGER.warning('Groq reply unavailable after recovery: %s',error)
                    notice=('I could not get a reply just now. Could you ask me again?'
                            if hint=='en' else 'এই মুহূর্তে উত্তরটা আনতে পারলাম না। আর একবার বলবে?')
                    phrase=SpokenPhrase(notice,'neutral')
                    reply.append(phrase.text)
                    await texts.put(phrase)
                await texts.put(None)

            async def synthesize():
                while (phrase := await texts.get()) is not None:
                    started = time.perf_counter()
                    deliveries = metrics.setdefault('delivery_counts', {})
                    deliveries[phrase.emotion] = deliveries.get(phrase.emotion, 0) + 1
                    first = True
                    samples=0
                    async for pcm in MODEL.synthesize_chunks(phrase):
                        samples+=len(pcm)
                        await sounds.put((phrase if first else None, pcm, (time.perf_counter()-started)*1000))
                        first = False
                    chunk_ms=round((time.perf_counter()-started)*1000)
                    metrics.setdefault('tts_chunk_timings',[]).append({'words':len(phrase.text.split()),
                        'generation_ms':chunk_ms,'audio_ms':round(samples/24)})
                await sounds.put(None)

            async def play():
                encoder = OpusOutput(bitrate=CONFIG.get('output_bitrate',48000))
                started = False
                buffered = 0
                prefill = max(1,min(4,CONFIG.get('playback_prefill_frames',3)))
                deadline = time.perf_counter()
                primer=[]
                primed=False

                async def send_packet(packet):
                    nonlocal buffered, deadline
                    if 'first_audio_after_endpoint_ms' in metrics:
                        metrics['max_audio_gap_ms']=max(metrics.get('max_audio_gap_ms',0),
                            round(max(0,time.perf_counter()-deadline)*1000))
                    await asyncio.sleep(max(0, deadline-time.perf_counter()))
                    if 'first_audio_after_endpoint_ms' not in metrics:
                        metrics['first_audio_after_endpoint_ms']=round((time.perf_counter()-began)*1000)
                    await self.socket.send_bytes(packet)
                    self.packets_out+=1
                    buffered+=1
                    if buffered>=prefill:
                        deadline=max(deadline,time.perf_counter()-0.12)+0.06

                async def offer_packet(packet):
                    nonlocal primed, deadline
                    if not primed:
                        primer.append(packet)
                        if len(primer)<prefill:return
                        primed=True
                        deadline=time.perf_counter()
                        for initial in primer:await send_packet(initial)
                        primer.clear()
                    else:
                        await send_packet(packet)
                async for item in lookahead_audio(sounds,0,metrics):
                    phrase, pcm, synth_ms = item
                    if not started:
                        await self.message("tts", state="start")
                        started = True
                        deadline = time.perf_counter()
                        metrics["first_tts_ms"] = round(synth_ms)
                    if phrase is not None:
                        await self.message("tts", state="sentence_start", text=phrase.text)
                        # Xiaozhi-compatible expression event; unknown fields are safe for current firmware.
                        await self.message("llm", emotion=phrase.emotion)
                    for packet in encoder.encode(pcm):
                        await offer_packet(packet)
                if started:
                    for packet in encoder.finish():
                        await offer_packet(packet)
                    # A genuinely short utterance may contain fewer than prefill packets.
                    if primer:
                        deadline=time.perf_counter()
                        for packet in primer:await send_packet(packet)
                    await self.message("tts", state="stop")
                speech_finished.set()

            async with asyncio.TaskGroup() as group:
                if MODEL.speech.backend in ('mithi',):
                    group.create_task(keep_session_active(self.message,speech_finished))
                group.create_task(generate())
                group.create_task(synthesize())
                group.create_task(play())
            if reply:
                answer = " ".join(reply)
                self.history.append({"role": "assistant", "content": answer})
                self.history = self.history[-8:]
                if CONFIG.get("log_transcripts"):
                    LOGGER.info("Deskter: %s", answer)
            self.turns += 1
            metrics.update(turn=self.turns, packets_in=self.packets_in, packets_out=self.packets_out)
            LOGGER.info("TURN %s", json.dumps(metrics))
            (ROOT / "logs").mkdir(exist_ok=True)
            with (ROOT / "logs/latency.jsonl").open("a", encoding="utf-8") as file:
                file.write(json.dumps(metrics)+"\n")
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Conversation failed")
            with suppress(Exception):
                await self.message("error", message="Local speech processing failed; please try again")
                await self.message("tts", state="stop")
        finally:
            self.busy = False
            self.segmenter.reset()
            # Empty ASR/error paths still need to let firmware restart listening.
            if not self.history or "first_audio_after_endpoint_ms" not in metrics:
                with suppress(Exception):
                    await self.message("tts", state="stop")

    async def run(self):
        while True:
            incoming = await self.socket.receive()
            if incoming["type"] == "websocket.disconnect":
                break
            if incoming.get("text") is not None:
                message = json.loads(incoming["text"])
                if message.get("type") == "hello":
                    audio = message.get("audio_params", {})
                    if audio.get("format") != "opus" or audio.get("sample_rate") != 16000 or audio.get("channels") != 1:
                        await self.socket.close(1003, "Expected mono 16 kHz Opus")
                        break
                    await self.message("hello", version=1, transport="websocket",
                                       audio_params={"format":"opus", "sample_rate":24000,"channels":1,"frame_duration":60})
                elif message.get("type") == "listen":
                    self.listening = message.get("state") == "start"
                    self.segmenter = Utterances(CONFIG)
            elif incoming.get("bytes") is not None:
                packet = incoming["bytes"]
                if len(packet) > 1500:
                    await self.socket.close(1009, "Audio packet too large")
                    break
                self.packets_in += 1
                if self.listening and not self.busy:
                    audio = self.segmenter.feed(self.decoder.decode(packet))
                    if audio is not None:
                        self.busy, self.listening = True, False
                        self.task = asyncio.create_task(self.respond(audio))


@app.websocket("/xiaozhi/v1/")
async def websocket(socket: WebSocket):
    global ACTIVE_CONVERSATION
    if not authorized(socket.headers):
        await socket.close(1008)
        return
    if DEVICE_LOCK.locked():
        await socket.close(1013)
        return
    async with DEVICE_LOCK:
        await socket.accept()
        conversation = Conversation(socket)
        ACTIVE_CONVERSATION = conversation
        LOGGER.info("XIAO connected to Deskter server")
        try:
            await conversation.run()
        except WebSocketDisconnect:
            pass
        except Exception:
            LOGGER.exception("Device connection failed")
        finally:
            if conversation.task:
                conversation.task.cancel()
                with suppress(asyncio.CancelledError):
                    await conversation.task
            ACTIVE_CONVERSATION = None
            LOGGER.info("XIAO disconnected; received=%d sent=%d", conversation.packets_in, conversation.packets_out)
