import os, uuid
from flask import Flask, request, send_from_directory
from dotenv import load_dotenv
from pydub import AudioSegment
import pandas as pd
import requests
import torch
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM, VitsModel
import soundfile as sf
from apscheduler.schedulers.background import BackgroundScheduler
from twilio.rest import Client

# === CONFIGURATION ===
load_dotenv()
TESTING_MODE = True # <--- SET THIS TO False FOR DEPLOYMENT

if TESTING_MODE:
    from pyngrok import ngrok

# === SETUP ===
os.makedirs("temp_audio", exist_ok=True)
AudioSegment.converter = "/usr/bin/ffmpeg"

print("Loading models...")
tok = AutoTokenizer.from_pretrained("facebook/nllb-200-distilled-600M")
nllb = AutoModelForSeq2SeqLM.from_pretrained("facebook/nllb-200-distilled-600M")
tts_tok = AutoTokenizer.from_pretrained("facebook/mms-tts-hau")
tts = VitsModel.from_pretrained("facebook/mms-tts-hau")

app = Flask(__name__)
client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
FROM = os.getenv("TWILIO_NUMBER")

# === UTILITIES ===
def translate(text):
    inputs = tok(text, return_tensors="pt")
    out = nllb.generate(**inputs, forced_bos_token_id=tok.convert_tokens_to_ids("hau_Latn"))
    return tok.decode(out[0], skip_special_tokens=True)

def tts_generate(text):
    inputs = tts_tok(text, return_tensors="pt")
    with torch.no_grad():
        waveform = tts(**inputs).waveform
    wav_path = os.path.join("temp_audio", f"{uuid.uuid4().hex}.wav")
    sf.write(wav_path, waveform.squeeze().numpy(), samplerate=tts.config.sampling_rate)
    mp3_path = wav_path.replace(".wav", ".mp3")
    AudioSegment.from_wav(wav_path).export(mp3_path, format="mp3")
    os.remove(wav_path)
    return os.path.basename(mp3_path)

def get_all_whatsapp_subscribers():
    """Fetch all unique WhatsApp numbers that have messaged the Twilio number."""
    subscribers = set()
    try:
        messages = client.messages.list(to=FROM, limit=1000)
        for msg in messages:
            if msg.from_ and msg.from_.startswith("whatsapp:"):
                subscribers.add(msg.from_)
    except Exception as e:
        print(f"❌ Error fetching subscribers: {e}")
    return list(subscribers)

# === NGROK/URL HANDLING ===
def update_public_url():
    if TESTING_MODE:
        # Always update PUBLIC_URL from ngrok before sending
        tunnels = ngrok.get_tunnels()
        for t in tunnels:
            if t.public_url.startswith("https://"):
                os.environ["PUBLIC_URL"] = t.public_url
                return t.public_url
        return os.getenv("PUBLIC_URL")
    else:
        # Use static PUBLIC_URL from .env
        return os.getenv("PUBLIC_URL")

# === BROADCAST FUNCTION ===
def broadcast():
    try:
        # Always update PUBLIC_URL before sending
        update_public_url()
        print("🚀 Broadcasting...")
        df = pd.read_csv("messages.csv")
        if "message" not in df.columns:
            raise ValueError("CSV missing 'message' column.")

        # Message index logic
        if TESTING_MODE:
            index_file = "last_sent.txt"
            last_index = int(open(index_file).read()) if os.path.exists(index_file) else -1
            idx = (last_index + 1) % len(df)
            open(index_file, "w").write(str(idx))
        else:
            idx = (pd.Timestamp.now().day - 1) % len(df)

        en = df.loc[idx, "message"]
        ha = translate(en)
        mp3 = tts_generate(ha)
        audio_url = f"{os.getenv('PUBLIC_URL')}/temp_audio/{mp3}"

        print(f"💬 EN: {en}\n🌍 HA: {ha}")
        print(f"🎧 Audio link: {audio_url}")

        recipients = get_all_whatsapp_subscribers()
        print(f"📋 Found {len(recipients)} subscribers: {recipients}")

        for to in recipients:
            print(f"📲 Sending to {to}")
            try:
                # Send text
                client.messages.create(
                    body=ha,
                    from_=FROM,
                    to=to
                )
                print(f"✅ Text sent to {to}")
            except Exception as e:
                print(f"❌ Text send error for {to}: {e}")
            try:
                # Send audio
                client.messages.create(
                    media_url=[audio_url],
                    from_=FROM,
                    to=to
                )
                print(f"✅ Audio sent to {to}")
            except Exception as e:
                print(f"❌ Audio send error for {to}: {e}")

    except Exception as e:
        print(f"❌ Broadcast error: {e}")

# === SCHEDULER ===
from pytz import timezone
sched = BackgroundScheduler(timezone=timezone("Africa/Lagos"))
if TESTING_MODE:
    sched.add_job(broadcast, "interval", minutes=10)  # Every 1 minute for testing
else:
    sched.add_job(broadcast, "cron", hour=9, minute=0)  # 9am daily for prod
sched.start()

# === FLASK ROUTES ===
@app.route("/temp_audio/<file>")
def serve(file):
    return send_from_directory("temp_audio", file)

@app.route("/", methods=["GET"])
def home():
    return "✅ Twilio-based malaria bot is running!"

@app.route("/twilio", methods=["POST"])
def receive_whatsapp():
    incoming_msg = request.values.get("Body", "")
    sender = request.values.get("From", "")
    print(f"📥 Message from {sender}: {incoming_msg}")
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
