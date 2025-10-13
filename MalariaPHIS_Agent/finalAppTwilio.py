# ===================================================
# MalariaPHIS-Hausa
# ===================================================

import os, uuid, json
from datetime import datetime
from flask import Flask, request, send_from_directory
from dotenv import load_dotenv
from pydub import AudioSegment
import pandas as pd
import torch
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM, VitsModel
import soundfile as sf
from apscheduler.schedulers.background import BackgroundScheduler
from twilio.rest import Client
from pytz import timezone



# === CONFIGURATION ===
load_dotenv()
timeinterval = 7  # broadcast interval in minutes. Set to 7 for testing, 1440 for daily.
TESTING_MODE = True
if TESTING_MODE:
    from pyngrok import ngrok

os.makedirs("temp_audio", exist_ok=True)
AudioSegment.converter = "/usr/bin/ffmpeg"
SUBSCRIBER_FILE = "subscribers.json"

# === SUBSCRIBER UTILS ===
def load_subscribers():
    if os.path.exists(SUBSCRIBER_FILE):
        with open(SUBSCRIBER_FILE, "r") as f:
            return json.load(f)
    return {}

def save_subscribers(data):
    with open(SUBSCRIBER_FILE, "w") as f:
        json.dump(data, f, indent=2)

def mark_unsubscribed(phone):
    data = load_subscribers()
    data[phone] = {
        "unsubscribed": True,
        "last_seen": datetime.utcnow().isoformat()
    }
    save_subscribers(data)

def record_activity(phone):
    data = load_subscribers()
    entry = data.get(phone, {})
    entry["unsubscribed"] = False
    entry["last_seen"] = datetime.utcnow().isoformat()
    data[phone] = entry
    save_subscribers(data)

def get_active_subscribers():
    data = load_subscribers()
    return [p for p, info in data.items() if not info.get("unsubscribed")]

# === AGENTS ===
class TranslationAgent:         # Hausa translation using NLLB-200
    def __init__(self):
        print("[INFO] Loading translation model...")
        self.tokenizer = AutoTokenizer.from_pretrained("facebook/nllb-200-distilled-600M")
        self.model = AutoModelForSeq2SeqLM.from_pretrained("facebook/nllb-200-distilled-600M")
        self.hausa_token_id = self.tokenizer.convert_tokens_to_ids("hau_Latn")

    def translate(self, text):
        inputs = self.tokenizer(text, return_tensors="pt")
        out = self.model.generate(**inputs, forced_bos_token_id=self.hausa_token_id)
        return self.tokenizer.decode(out[0], skip_special_tokens=True)

class TTSAgent:             # Text-to-Speech using Facebook's MMS-TTS-Hausa
    def __init__(self):
        print("[INFO] Loading TTS model...")
        self.tokenizer = AutoTokenizer.from_pretrained("facebook/mms-tts-hau")
        self.model = VitsModel.from_pretrained("facebook/mms-tts-hau")

    def synthesize(self, text):
        inputs = self.tokenizer(text, return_tensors="pt")
        with torch.no_grad():
            waveform = self.model(**inputs).waveform
        wav_path = os.path.join("temp_audio", f"{uuid.uuid4().hex}.wav")
        sf.write(wav_path, waveform.squeeze().numpy(), samplerate=self.model.config.sampling_rate)
        mp3_path = wav_path.replace(".wav", ".mp3")
        AudioSegment.from_wav(wav_path).export(mp3_path, format="mp3")
        os.remove(wav_path)
        return os.path.basename(mp3_path)

class DeliveryAgent:            # Whatsapp delivery using Twilio
    def __init__(self, sid, token, from_number):
        self.client = Client(sid, token)
        self.from_number = from_number

    def get_subscribers(self):
        try:
            all_msgs = self.client.messages.list(to=self.from_number, limit=1000)
            active_twilio = {m.from_ for m in all_msgs if m.from_ and m.from_.startswith("whatsapp:")}
            local_active = set(get_active_subscribers())
            return list(active_twilio & local_active)
        except Exception as e:
            print(f"[ERROR]❌ Getting subscribers: {e}")
            return []

    def broadcast(self, full_text, audio_url):
        recipients = self.get_subscribers()
        print(f"📋 Found {len(recipients)} subscribers: {recipients}")
        print(f"[INFO]🚀 Broadcasting to {len(recipients)} subscribers")
        for to in recipients:
            try:
                self.client.messages.create(body=full_text, from_=self.from_number, to=to)
                self.client.messages.create(media_url=[audio_url], from_=self.from_number, to=to)
                print(f"[SENT] {to}")
            except Exception as e:
                print(f"[ERROR]❌ Sending to {to}: {e}")

# === PUBLIC URL HANDLER ===
def update_public_url():
    if TESTING_MODE:            # Uses Ngrok for Local Testing
        tunnels = ngrok.get_tunnels()
        for t in tunnels:
            if t.public_url.startswith("https://"):
                os.environ["PUBLIC_URL"] = t.public_url
                return t.public_url
    return os.getenv("PUBLIC_URL")


# === BROADCAST LOGIC ===
def broadcast():
    seprator = "=" * 20
    lang_separator = "_" * 80
    appname = f"{seprator} \n  _🌍MalariaPHIS-Hausa_ \n{seprator}\n"
    try:
        update_public_url()
        print("[INFO] Starting broadcast...")
        df = pd.read_csv("messages.csv")
        if "message" not in df.columns or "source" not in df.columns:
            raise ValueError("CSV must include 'message' and 'source' columns.")

        index_file = "last_sent.txt"
        idx = (int(open(index_file).read()) + 1 if os.path.exists(index_file) else 0) % len(df)
        open(index_file, "w").write(str(idx))
        en = df.loc[idx, "message"]
        source = df.loc[idx, "source"]

        print(f" \n💬 EN: {en} (Source: {source})")
        ha = translator.translate(en)
        print(f"🌍 HA: {ha}")

        # Construct full message with language markers
        full_text = f"{appname}[EN]🇺🇸  {en} _-(Source: {source})_ \n{lang_separator}\n*[HA]🇳🇬  {ha}*"
        mp3 = tts_agent.synthesize(ha)
        audio_url = f"{os.getenv('PUBLIC_URL')}/temp_audio/{mp3}"
        delivery_agent.broadcast(full_text, audio_url)

    except Exception as e:
        print(f"[ERROR]❌ Broadcast failed: {e}")

# === AGENT INITIALIZATION ===
translator = TranslationAgent()
tts_agent = TTSAgent()
delivery_agent = DeliveryAgent(
    os.getenv("TWILIO_ACCOUNT_SID"),
    os.getenv("TWILIO_AUTH_TOKEN"),
    os.getenv("TWILIO_NUMBER")
)

# === SCHEDULER ===
sched = BackgroundScheduler(timezone=timezone("Africa/Lagos"))
if TESTING_MODE:
    sched.add_job(broadcast, trigger="interval", minutes=timeinterval)      
else:
    sched.add_job(broadcast, trigger="cron", hour=9, minute=0)      
sched.start()

# === FLASK APP ===
app = Flask(__name__)

@app.route("/temp_audio/<file>")
def serve(file):
    return send_from_directory("temp_audio", file)

@app.route("/")
def home():
    return "✅ Agentic malaria AI is running!"

@app.route("/twilio", methods=["POST"])
def receive_whatsapp():
    incoming = request.values.get("Body", "").strip()
    sender = request.values.get("From", "")
    print(f"[📥MSG] From {sender}: {incoming}")
    
    normalized = incoming.upper()
    if normalized in {"STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT", "JOIN"}:
        mark_unsubscribed(sender)
        return "You have been unsubscribed.", 200
    if normalized in {"START", "UNSTOP"}:
        record_activity(sender)
        # send a welcome message or re-subscription confirmation
        delivery_agent.client.messages.create(
            body= f"Welcome...! You are now subscribed/re-subscribed to {timeinterval}minutes MalariaPHIS-Hausa updates.",
            from_=delivery_agent.from_number,
            to=sender
        )
        print(f"[📤MSG] Sent re-subscription confirmation to {sender}")
        return "You are re‑subscribed.", 200

    record_activity(sender)

    if incoming.lower().startswith("malaria news update"):
        content = incoming[len("malaria news update"):].strip()
        if not content:
            return "Please provide the news content after 'malaria news update'.", 200

        seprator = "=" *20
        lang_separator = "_" * 80
        appname = f"{seprator} \n  _🌍MalariaPHIS-Hausa_ \n {seprator}\n"

        hausa = translator.translate(content)
        mp3 = tts_agent.synthesize(hausa)
        url = f"{os.getenv('PUBLIC_URL')}/temp_audio/{mp3}"
        full_text = f"{appname}[EN]🇺🇸  {content}_-(Source: {sender})_  \n{lang_separator}\n*[HA]🇳🇬  {hausa}*"

        recipients = delivery_agent.get_subscribers()
        print(f"[NEWS] Broadcasting user news to {len(recipients)}")
        for to in recipients:
            try:
                delivery_agent.client.messages.create(body=full_text, from_=delivery_agent.from_number, to=to)
                delivery_agent.client.messages.create(media_url=[url], from_=delivery_agent.from_number, to=to)
                print(f"✅ News sent to: {to}")
            except Exception as e:
                print(f"[ERROR]❌ Sending news to {to}: {e}")
        return "OK", 200

    return "OK", 200

# === APP ENTRYPOINT ===
if __name__ == "__main__":
    if TESTING_MODE and not os.getenv("PUBLIC_URL"):
        tunnel = ngrok.connect(5000, "http")
        os.environ["PUBLIC_URL"] = tunnel.public_url
        print(f"[INFO] Ngrok tunnel started: {tunnel.public_url}")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
