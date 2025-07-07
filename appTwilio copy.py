"""
Malaria Agentic AI (Multi-Agent Architecture)
========================================================

This application demonstrates a multi-agent system for broadcasting malaria awareness messages via WhatsApp using Twilio.
It is designed for both local testing (with ngrok) and production deployment (like on Railway).

Multi-Agent Design:WhatsApp Broadcast Bot
-------------------
- TranslationAgent: This Translates English messages to Hausa using a neural machine translation model.
- TTSAgent: This agent converts the Hausa text to speech (audio) using a neural TTS model.
- DeliveryAgent: Delivers both text and audio messages to WhatsApp community(subscribers) via Twilio.

Features of the System:
---------
- The System consist of a Scheduler for daily or interval-based broadcasts.
- The System automatically discover subscriber (so, no human intervension).
- There's Test mode with ngrok used for the local development.
- Production mode for cloud hosting/deployment.

Usage:
------
- Set TESTING_MODE = True for local development (ngrok auto-starts).
- Set TESTING_MODE = False for deployment (use PUBLIC_URL from .env).
- Prepare and Place English messages(Malaria related) in messages.csv (with a 'message' column).
- Run the script. The system will broadcast to all WhatsApp users who are active subscriber.

"""

import os, uuid
from flask import Flask, request, send_from_directory
from dotenv import load_dotenv
from pydub import AudioSegment
import pandas as pd
import torch
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM, VitsModel
import soundfile as sf
from apscheduler.schedulers.background import BackgroundScheduler
from twilio.rest import Client

# === CONFIGURATION ===
load_dotenv()
TESTING_MODE = True

if TESTING_MODE:
    from pyngrok import ngrok

# === SETUP ===
os.makedirs("temp_audio", exist_ok=True)
# Set ffmpeg path for audio conversion
AudioSegment.converter = "/usr/bin/ffmpeg"


# === AGENT DEFINITIONS ===
print("Loading models...")

class TranslationAgent:
    """
    This is the Agent responsible for translating English text to Hausa.
    It uses the Facebook NLLB model for neural machine translation.
    """
    def __init__(self):
        print("Loading translation model...")
        self.tokenizer = AutoTokenizer.from_pretrained("facebook/nllb-200-distilled-600M")
        self.model = AutoModelForSeq2SeqLM.from_pretrained("facebook/nllb-200-distilled-600M")
        self.hausa_token_id = self.tokenizer.convert_tokens_to_ids("hau_Latn")

    def translate(self, text):
        """
        Translate English text to Hausa.
        """
        inputs = self.tokenizer(text, return_tensors="pt")
        out = self.model.generate(**inputs, forced_bos_token_id=self.hausa_token_id)
        return self.tokenizer.decode(out[0], skip_special_tokens=True)

class TTSAgent:
    """
    And this is the Agent responsible for synthesizing Hausa text to speech (audio).
    This agent uses the Facebook MMS-TTS model for neural text-to-speech.
    """
    def __init__(self):
        print("Loading TTS model...")
        self.tokenizer = AutoTokenizer.from_pretrained("facebook/mms-tts-hau")
        self.model = VitsModel.from_pretrained("facebook/mms-tts-hau")

    def synthesize(self, text):
        """
        Synthesize Hausa text to MP3 audio.
        Returns the filename of the generated MP3.
        """
        inputs = self.tokenizer(text, return_tensors="pt")
        with torch.no_grad():
            waveform = self.model(**inputs).waveform
        wav_path = os.path.join("temp_audio", f"{uuid.uuid4().hex}.wav")
        sf.write(wav_path, waveform.squeeze().numpy(), samplerate=self.model.config.sampling_rate)
        mp3_path = wav_path.replace(".wav", ".mp3")
        AudioSegment.from_wav(wav_path).export(mp3_path, format="mp3")
        os.remove(wav_path)  # Clean up the intermediate WAV file
        return os.path.basename(mp3_path)

class DeliveryAgent:
    """
    This is the Agent responsible for delivering messages (text and audio) to WhatsApp subscribers (via Twilio).
    it also handles automatic discovery of subscribers, so that there won't be manual intervention needed.
    """
    def __init__(self, twilio_sid, twilio_token, from_number):
        self.client = Client(twilio_sid, twilio_token)
        self.from_number = from_number

    def get_subscribers(self):
        """
        Fetch all unique WhatsApp numbers that are active subscribers.
        This ensures broadcasts go only to users who have opted in.
        """
        subscribers = set()
        try:
            messages = self.client.messages.list(to=self.from_number, limit=1000)
            for msg in messages:
                if msg.from_ and msg.from_.startswith("whatsapp:"):
                    subscribers.add(msg.from_)
        except Exception as e:
            print(f"❌ Error fetching subscribers: {e}")
        return list(subscribers)

    def broadcast(self, hausa_text, audio_url):
        """
        This function broadcast the generated Hausa text and audio to all WhatsApp subscribers.
        """
        recipients = self.get_subscribers()
        print(f"📋 Found {len(recipients)} subscribers: {recipients}")
        for to in recipients:
            print(f"📲 Sending to {to}")
            try:
                # Send Hausa text
                self.client.messages.create(
                    body=hausa_text,
                    from_=self.from_number,
                    to=to
                )
                print(f"✅ Text sent to {to}")
            except Exception as e:
                print(f"❌ Text send error for {to}: {e}")
            try:
                # Send Hausa audio
                self.client.messages.create(
                    media_url=[audio_url],
                    from_=self.from_number,
                    to=to
                )
                print(f"✅ Audio sent to {to}")
            except Exception as e:
                print(f"❌ Audio send error for {to}: {e}")

# === NGROK/URL HANDLING ===
def update_public_url():
    """
    In test mode, this function always update PUBLIC_URL from ngrok before sending.
    In production, use the static PUBLIC_URL from .env.
    """
    if TESTING_MODE:
        tunnels = ngrok.get_tunnels()
        for t in tunnels:
            if t.public_url.startswith("https://"):
                os.environ["PUBLIC_URL"] = t.public_url
                return t.public_url
        return os.getenv("PUBLIC_URL")
    else:
        return os.getenv("PUBLIC_URL")

# === MAIN BROADCAST FUNCTION ===
def broadcast():
    """
    Main broadcast routine:
    - Loads the next message(Malaria message) from CSV.
    - Translates to Hausa.
    - Synthesizes audio.
    - Broadcasts to all WhatsApp subscribers.
    """
    try:
        # Always update PUBLIC_URL before sending (for ngrok/test mode)
        update_public_url()
        print("🚀 Broadcasting...")
        df = pd.read_csv("messages.csv")
        if "message" not in df.columns:
            raise ValueError("CSV missing 'message' column.")

        # Message index logic: cycle through messages in test mode, use calendar day in prod
        if TESTING_MODE:
            index_file = "last_sent.txt"
            last_index = int(open(index_file).read()) if os.path.exists(index_file) else -1
            idx = (last_index + 1) % len(df)
            open(index_file, "w").write(str(idx))
        else:
            idx = (pd.Timestamp.now().day - 1) % len(df)

        en = df.loc[idx, "message"]
        print(f"💬 EN: {en}")

        ha = translator.translate(en)
        print(f"🌍 HA: {ha}")

        mp3 = tts_agent.synthesize(ha)
        audio_url = f"{os.getenv('PUBLIC_URL')}/temp_audio/{mp3}"
        print(f"🎧 Audio link: {audio_url}")

        delivery_agent.broadcast(ha, audio_url)

    except Exception as e:
        print(f"❌ Broadcast error: {e}")

# === AGENT INSTANTIATION ===
# Instantiate each agent once for efficiency and clarity
translator = TranslationAgent()
tts_agent = TTSAgent()
delivery_agent = DeliveryAgent(
    os.getenv("TWILIO_ACCOUNT_SID"),
    os.getenv("TWILIO_AUTH_TOKEN"),
    os.getenv("TWILIO_NUMBER")
)

# === SCHEDULER ===
from pytz import timezone
sched = BackgroundScheduler(timezone=timezone("Africa/Lagos"))
if TESTING_MODE:
    # In test mode, broadcast every 10 minutes (adjust as needed)
    sched.add_job(broadcast, "interval", minutes=10)
else:
    # In production, broadcast daily at 9am
    sched.add_job(broadcast, "cron", hour=9, minute=0)
sched.start()

# === FLASK ROUTES ===

app = Flask(__name__)

@app.route("/temp_audio/<file>")
def serve(file):
    """
    Serve generated audio files for Twilio to fetch.
    """
    return send_from_directory("temp_audio", file)

@app.route("/", methods=["GET"])
def home():
    """
    Health check endpoint.
    """
    return "✅ Twilio-based malaria bot is running!"

@app.route("/twilio", methods=["POST"])
def receive_whatsapp():
    """
    Endpoint for receiving WhatsApp messages.
    If the message starts with 'malaria news update', translate and broadcast to all subscribers (text + audio).
    """
    incoming_msg = request.values.get("Body", "")
    sender = request.values.get("From", "")
    print(f"📥 Message from {sender}: {incoming_msg}")

    # Check for 'malaria news update' heading (case-insensitive, must be at the start)
    if incoming_msg.lower().startswith("malaria news update"):
        # Remove the heading and any leading/trailing whitespace
        content = incoming_msg[len("malaria news update"):].strip()
        if not content:
            reply_text = "Please provide the news content after 'malaria news update'."
            return reply_text, 200

        # Translate and synthesize
        hausa_text = translator.translate(content)
        mp3 = tts_agent.synthesize(hausa_text)
        audio_url = f"{os.getenv('PUBLIC_URL')}/temp_audio/{mp3}"

        # Broadcast Hausa text and audio to all subscribers
        try:
            recipients = delivery_agent.get_subscribers()
            print(f"📢 Broadcasting user-submitted news to {len(recipients)} subscribers: {recipients}")
            for to in recipients:
                try:
                    delivery_agent.client.messages.create(
                        body=hausa_text,
                        from_=delivery_agent.from_number,
                        to=to
                    )
                    delivery_agent.client.messages.create(
                        media_url=[audio_url],
                        from_=delivery_agent.from_number,
                        to=to
                    )
                    print(f"✅ News sent to {to}")
                except Exception as e:
                    print(f"❌ Error sending news to {to}: {e}")
        except Exception as e:
            print(f"❌ Error broadcasting news: {e}")
        return "OK", 200

    # If not a malaria news update message, do not respond
    return "OK", 200

# === APP ENTRYPOINT ===
if __name__ == "__main__":
    if TESTING_MODE:
        # Start ngrok tunnel for port 5000 if not already started
        if not os.getenv("PUBLIC_URL"):
            tunnel = ngrok.connect(5000, "http")
            os.environ["PUBLIC_URL"] = tunnel.public_url
            print(f"ngrok tunnel started: {tunnel.public_url}")
            broadcast()  # Trigger first message on start
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
