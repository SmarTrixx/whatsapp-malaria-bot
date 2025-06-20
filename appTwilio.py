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

# Load environment variables
load_dotenv()

TESTING_MODE = True
os.makedirs("temp_audio", exist_ok=True)
AudioSegment.converter = "/usr/bin/ffmpeg"

# Load models
print("Loading models...")
tok = AutoTokenizer.from_pretrained("facebook/nllb-200-distilled-600M")
nllb = AutoModelForSeq2SeqLM.from_pretrained("facebook/nllb-200-distilled-600M")
tts_tok = AutoTokenizer.from_pretrained("facebook/mms-tts-hau")
tts = VitsModel.from_pretrained("facebook/mms-tts-hau")

# Flask app
app = Flask(__name__)

# Twilio setup
client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
FROM = os.getenv("TWILIO_NUMBER")

# Dynamic PUBLIC_URL
@app.before_request
def set_public_url():
    if not os.getenv("PUBLIC_URL"):
        os.environ["PUBLIC_URL"] = request.host_url.rstrip("/")

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

def broadcast():
    try:
        print("🚀 Broadcasting...")
        df = pd.read_csv("messages.csv")
        if "message" not in df.columns:
            raise ValueError("CSV missing 'message' column.")

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

        # Send to each number in the comma-separated list
        recipients = [r.strip() for r in os.getenv("RECIPIENT_NUMBER", "").split(",") if r.strip()]
        for to in recipients:
            print(f"📲 Sending to {to}")
            # Send text
            client.messages.create(
                body=ha,
                from_=FROM,
                to=to
            )
            # Send audio
            client.messages.create(
                media_url=[audio_url],
                from_=FROM,
                to=to
            )

    except Exception as e:
        print(f"❌ Broadcast error: {e}")

# Scheduler (every 9am daily)
sched = BackgroundScheduler(timezone="Africa/Lagos")
sched.add_job(broadcast, "cron", hour=9, minute=0)
# sched.add_job(broadcast, "interval", minutes=30)  # For testing every 30 minutes 
sched.start()

@app.route("/temp_audio/<file>")
def serve(file):
    return send_from_directory("temp_audio", file)

@app.route("/", methods=["GET"])
def home():
    return "✅ Twilio-based malaria bot is running on Railway!"

@app.route("/twilio", methods=["POST"])
def receive_whatsapp():
    incoming_msg = request.values.get("Body", "")
    sender = request.values.get("From", "")
    print(f"📥 Message from {sender}: {incoming_msg}")
    return "OK", 200

# Run app
if __name__ == "__main__":
    broadcast()  # Trigger first message on start
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
