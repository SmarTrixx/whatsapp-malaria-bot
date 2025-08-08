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
TESTING_MODE = True
if TESTING_MODE:
    from pyngrok import ngrok

LANG_CODES = {
    "HAUSA": ("hau_Latn", "facebook/mms-tts-hau"),
    "YORUBA": ("yor_Latn", "facebook/mms-tts-yor"),
    "IGBO": ("ibo_Latn", "facebook/mms-tts-ibo")
}

DEFAULT_LANG = "HAUSA"

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
    entry = data.get(phone, {})
    entry["unsubscribed"] = True
    entry["last_seen"] = datetime.utcnow().isoformat()
    data[phone] = entry
    save_subscribers(data)

def record_activity(phone, lang=None):
    data = load_subscribers()
    entry = data.get(phone, {})
    entry["unsubscribed"] = False
    entry["last_seen"] = datetime.utcnow().isoformat()
    if lang:
        entry["lang"] = lang
    data[phone] = entry
    save_subscribers(data)

def get_lang(phone):
    data = load_subscribers()
    return data.get(phone, {}).get("lang", DEFAULT_LANG)

def get_active_subscribers():
    data = load_subscribers()
    return [p for p, info in data.items() if not info.get("unsubscribed")]

# === TRANSLATION AGENT ===
class TranslationAgent:
    def __init__(self):
        print("[INFO] Loading translation model...")
        self.tokenizer = AutoTokenizer.from_pretrained("facebook/nllb-200-distilled-600M")
        self.model = AutoModelForSeq2SeqLM.from_pretrained("facebook/nllb-200-distilled-600M")

    def translate(self, text, lang_code):
        lang_token_id = self.tokenizer.convert_tokens_to_ids(lang_code)
        inputs = self.tokenizer(text, return_tensors="pt")
        out = self.model.generate(**inputs, forced_bos_token_id=lang_token_id)
        return self.tokenizer.decode(out[0], skip_special_tokens=True)

class TTSAgent:
    def __init__(self):
        self.models = {}

    def synthesize(self, text, lang_name):
        model_id = LANG_CODES[lang_name][1]
        if lang_name not in self.models:
            print(f"[INFO] Loading TTS for {lang_name}")
            tokenizer = AutoTokenizer.from_pretrained(model_id)
            model = VitsModel.from_pretrained(model_id)
            self.models[lang_name] = (tokenizer, model)
        tokenizer, model = self.models[lang_name]
        inputs = tokenizer(text, return_tensors="pt")
        with torch.no_grad():
            waveform = model(**inputs).waveform
        wav_path = os.path.join("temp_audio", f"{uuid.uuid4().hex}.wav")
        sf.write(wav_path, waveform.squeeze().numpy(), samplerate=model.config.sampling_rate)
        mp3_path = wav_path.replace(".wav", ".mp3")
        AudioSegment.from_wav(wav_path).export(mp3_path, format="mp3")
        os.remove(wav_path)
        return os.path.basename(mp3_path)

class DeliveryAgent:
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
            print(f"[ERROR] Getting subscribers: {e}")
            return []

    def send(self, to, message, audio_url):
        self.client.messages.create(body=message, from_=self.from_number, to=to)
        self.client.messages.create(media_url=[audio_url], from_=self.from_number, to=to)

def update_public_url():
    if TESTING_MODE:
        tunnels = ngrok.get_tunnels()
        for t in tunnels:
            if t.public_url.startswith("https://"):
                os.environ["PUBLIC_URL"] = t.public_url
                return t.public_url
    return os.getenv("PUBLIC_URL")

def broadcast():
    try:
        update_public_url()
        df = pd.read_csv("messages2.csv")
        if "message" not in df.columns or "source" not in df.columns:
            raise ValueError("CSV must contain 'message' and 'source' columns.")
        index_file = "last_sent.txt"
        idx = (int(open(index_file).read()) + 1 if os.path.exists(index_file) else 0) % len(df)
        open(index_file, "w").write(str(idx))
        en = df.loc[idx, "message"]
        src = df.loc[idx, "source"]
        subs = delivery_agent.get_subscribers()

        for user in subs:
            lang = get_lang(user)
            lang_code = LANG_CODES[lang][0]
            trans = translator.translate(en, lang_code)
            msg = f"[EN]🇺🇸 {en} _-(Source: {src})_\n---------------------------------\n*[{lang[:2]}]🇳🇬 {trans}*"
            mp3 = tts_agent.synthesize(trans, lang)
            url = f"{os.getenv('PUBLIC_URL')}/temp_audio/{mp3}"
            delivery_agent.send(user, msg, url)
            print(f"✅ Sent to {user} in {lang}")

    except Exception as e:
        print(f"[ERROR] Broadcast failed: {e}")

# === INITIALIZE ===
translator = TranslationAgent()
tts_agent = TTSAgent()
delivery_agent = DeliveryAgent(
    os.getenv("TWILIO_ACCOUNT_SID"),
    os.getenv("TWILIO_AUTH_TOKEN"),
    os.getenv("TWILIO_NUMBER")
)

sched = BackgroundScheduler(timezone=timezone("Africa/Lagos"))
if TESTING_MODE:
    sched.add_job(broadcast, "interval", minutes=3)
else:
    sched.add_job(broadcast, "cron", hour=9, minute=0)
sched.start()

# === FLASK ===
app = Flask(__name__)

@app.route("/temp_audio/<file>")
def serve(file):
    return send_from_directory("temp_audio", file)

@app.route("/")
def home():
    return "✅ Language-aware malaria bot is running!"

@app.route("/twilio", methods=["POST"])
def receive_whatsapp():
    body = request.values.get("Body", "").strip()
    sender = request.values.get("From", "")
    print(f"[MSG] {sender}: {body}")
    normalized = body.upper()

    if normalized.startswith("LANGUAGE:"):
        lang = normalized.split(":")[1].strip()
        if lang in LANG_CODES:
            record_activity(sender, lang)
            return f"✅ Language set to {lang}.", 200
        else:
            return "❌ Invalid language. Use HAUSA, YORUBA, or IGBO.", 200

    if normalized in {"STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT", "JOIN"}:
        mark_unsubscribed(sender)
        return "You have been unsubscribed.", 200

    if normalized in {"START", "UNSTOP"}:
        record_activity(sender)
        return "You are re‑subscribed.", 200
    
# if message has malaria news update header, then translate message and broadcast
    if body.lower().startswith("malaria news update"):
        content = body[len("malaria news update"):].strip()
        if not content:
            return "Please provide the news content after 'malaria news update'.", 200

        en = content
        src = sender
        subs = delivery_agent.get_subscribers()

        for user in subs:
            lang = get_lang(user)
            lang_code = LANG_CODES[lang][0]
            trans = translator.translate(en, lang_code)
            msg = f"[EN]🇺🇸 {en} _-(Source: {src})_\n---------------------------------\n*[{lang[:2]}]🇳🇬 {trans}*"
            mp3 = tts_agent.synthesize(trans, lang)
            url = f"{os.getenv('PUBLIC_URL')}/temp_audio/{mp3}"
            delivery_agent.send(user, msg, url)
            print(f"✅ Sent to {user} in {lang}")

    record_activity(sender)
    return "✅ Message received.", 200

if __name__ == "__main__":
    if TESTING_MODE and not os.getenv("PUBLIC_URL"):
        tunnel = ngrok.connect(5000, "http")
        os.environ["PUBLIC_URL"] = tunnel.public_url
        print(f"[NGROK] Tunnel: {tunnel.public_url}")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
