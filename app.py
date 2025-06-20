import os, torch, uuid, time
from flask import Flask, send_from_directory
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM, VitsModel
from pydub import AudioSegment
from apscheduler.schedulers.background import BackgroundScheduler
import pandas as pd, requests
from dotenv import load_dotenv
from pyngrok import ngrok
import soundfile as sf
from flask import request

# Load environment variables
load_dotenv()

TESTING_MODE = True  # Set to False when deploying


# Create audio folder if not exists
os.makedirs("temp_audio", exist_ok=True)

# Optional: Ensure ffmpeg is set (adjust path if needed)
AudioSegment.converter = "/usr/bin/ffmpeg"  # Ensure ffmpeg is installed

# Load models
print("Loading models...")
tok = AutoTokenizer.from_pretrained("facebook/nllb-200-distilled-600M")
nllb = AutoModelForSeq2SeqLM.from_pretrained("facebook/nllb-200-distilled-600M")
tts_tok = AutoTokenizer.from_pretrained("facebook/mms-tts-hau")
tts = VitsModel.from_pretrained("facebook/mms-tts-hau")

# Init Flask app
app = Flask(__name__)

# Translate English → Hausa
def translate(text):
    inputs = tok(text, return_tensors="pt")
    out = nllb.generate(**inputs, forced_bos_token_id=tok.convert_tokens_to_ids("hau_Latn"))
    return tok.decode(out[0], skip_special_tokens=True)

# TTS generation
def tts_generate(text):
    inputs = tts_tok(text, return_tensors="pt")
    with torch.no_grad():
        waveform = tts(**inputs).waveform
    wav_path = os.path.join("temp_audio", f"{uuid.uuid4().hex}.wav")
    sf.write(wav_path, waveform.squeeze().numpy(), samplerate=tts.config.sampling_rate)

    # Convert to MP3
    mp3_path = wav_path.replace(".wav", ".mp3")
    AudioSegment.from_wav(wav_path).export(mp3_path, format="mp3")
    os.remove(wav_path)
    return os.path.basename(mp3_path)

# Broadcast daily message
def broadcast():
    try:
        print("🚀 Broadcasting now...")
        df = pd.read_csv("messages.csv")
        if "message" not in df.columns:
            raise ValueError("❌ CSV file must contain a 'message' column.")
        
        # idx = (pd.Timestamp.now().day - 1) % len(df)

        if TESTING_MODE:
            index_file = "last_sent.txt"
            if os.path.exists(index_file):
                with open(index_file, "r") as f:
                    last_index = int(f.read().strip())
            else:
                last_index = -1

            idx = (last_index + 1) % len(df)

            with open(index_file, "w") as f:
                f.write(str(idx))
        else:
            idx = (pd.Timestamp.now().day - 1) % len(df)
        print(f"📅 Today's message index: {idx}")


        en = df.loc[idx, "message"]
        print(f"📝 Message to translate: {en}")
        ha = translate(en)
        print(f"🌍 Translated: {ha}")
        mp3 = tts_generate(ha)
        url = f"{os.getenv('PUBLIC_URL')}/temp_audio/{mp3}"
        print(f"🎧 Audio file URL: {url}")

        for to in os.getenv("SUBSCRIBERS", "").split(","):
            print(f"📲 Sending to {to}")
            r1 = requests.post(
                f"https://graph.facebook.com/v18.0/{os.getenv('PHONE_NUMBER_ID')}/messages",
                headers={"Authorization": f"Bearer {os.getenv('WHATSAPP_TOKEN')}"},
                json={"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": ha}}
            )
            print("📤 Text message response:", r1.status_code, r1.text)

            r2 = requests.post(
                f"https://graph.facebook.com/v18.0/{os.getenv('PHONE_NUMBER_ID')}/messages",
                headers={"Authorization": f"Bearer {os.getenv('WHATSAPP_TOKEN')}"},
                json={"messaging_product": "whatsapp", "to": to, "type": "audio", "audio": {"link": url}}
            )
            print("📤 Audio message response:", r2.status_code, r2.text)

    except Exception as e:
        print(f"❌ Broadcast error: {e}")



# Schedule job: 9 AM daily
sched = BackgroundScheduler()
sched.timezone = "Africa/Lagos"
sched.add_job(broadcast, "cron", hour=9, minute=0)
# sched.add_job(broadcast, "interval", minutes=2)
sched.start()

# Serve audio files
@app.route("/temp_audio/<file>")
def serve(file):
    return send_from_directory("temp_audio", file)

# Simple health check route
@app.route("/", methods=["GET"])
def hi():
    return "✅ Malaria bot is running!"


# Verification token
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")

# Webhook route for Facebook/WhatsApp verification and events
@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        # Webhook verification
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")

        if mode == "subscribe" and token == VERIFY_TOKEN:
            print("✅ Webhook verified.")
            return challenge, 200
        else:
            print("❌ Webhook verification failed.")
            return "Verification token mismatch", 403

    elif request.method == "POST":
        # Incoming message event (handle it later if needed)
        data = request.get_json()
        print(f"📥 Received webhook event: {data}")
        return "EVENT_RECEIVED", 200


# Run app
if __name__ == "__main__":
    try:
        ngrok_tunnel = ngrok.connect(5000)
        public_url = ngrok_tunnel.public_url
        os.environ["PUBLIC_URL"] = public_url
        print(f"🌐 Ngrok tunnel: {public_url}")
        print(f"📩 Webhook URL: {public_url}/webhook")


        broadcast()  # Initial broadcast on startup

    except Exception as e:
        print(f"⚠️ Failed to start ngrok: {e}")
        os.environ["PUBLIC_URL"] = "http://localhost:5000"

    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
