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
import requests
from bs4 import BeautifulSoup
import feedparser



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

# === CORE AGENTS (Original) ===
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

# === Malaria Knowledge Retriever AGENT ===

class MalariaKnowledgeRetriever:     # Malaria information retrieval from trusted sources
    """
    Autonomously fetches malaria information from multiple sources (WHO, FEDGEN-PHIS, RSS feeds).
    Randomly selects between primary sources and implements multi-tier fallback strategy.
    Provides structured data for broadcast without manual CSV updates.
    """
    def __init__(self):
        print("[INFO] Initializing Malaria Knowledge Retriever...")
        self.primary_sources = {
            "WHO": {
                "url": "https://www.who.int/news/fact-sheets/detail/malaria",
                "type": "web"
            },
            "FEDGEN-PHIS": {
                "url": "https://fedgen.health.gov.ng/phis/malaria",
                "type": "web"
            }
        }
        self.rss_feeds = {
            "WHO-RSS": "https://www.who.int/feeds/entity/csr/don/en/feed.xml",
            "FEDGEN-RSS": "https://fedgen.health.gov.ng/feeds/malaria"
        }
    
    def fetch_malaria_content(self):
        """
        Autonomously retrieves malaria information from trusted sources.
        Randomly selects between WHO and FEDGEN-PHIS primary sources.
        Returns structured dict or None on failure (never raises exceptions).
        
        Returns:
            dict or None: {"message": str, "source": str, "timestamp": str} or None
        """
        try:
            import random
            print("[MKR] Attempting to retrieve malaria knowledge from random source...")
            
            # Randomly select primary source
            sources_list = list(self.primary_sources.keys())
            selected_source = random.choice(sources_list)
            print(f"[MKR] Selected primary source: {selected_source}")
            
            # Try selected primary source
            if selected_source == "WHO":
                content = self._fetch_who_malaria_info()
            else:  # FEDGEN-PHIS
                content = self._fetch_fedgen_malaria_info()
            
            if content:
                return {
                    "message": content,
                    "source": selected_source,
                    "timestamp": datetime.utcnow().isoformat()
                }
            
            # If primary source fails, try the other primary source
            fallback_source = [s for s in sources_list if s != selected_source][0]
            print(f"[MKR] Primary source failed, trying fallback: {fallback_source}")
            
            if fallback_source == "WHO":
                content = self._fetch_who_malaria_info()
            else:  # FEDGEN-PHIS
                content = self._fetch_fedgen_malaria_info()
            
            if content:
                return {
                    "message": content,
                    "source": fallback_source,
                    "timestamp": datetime.utcnow().isoformat()
                }
            
            # Try WHO RSS feed
            feed_content = self._fetch_malaria_rss("WHO-RSS")
            if feed_content:
                return {
                    "message": feed_content,
                    "source": "WHO-RSS",
                    "timestamp": datetime.utcnow().isoformat()
                }
            
            # Try FEDGEN RSS feed
            feed_content = self._fetch_malaria_rss("FEDGEN-RSS")
            if feed_content:
                return {
                    "message": feed_content,
                    "source": "FEDGEN-RSS",
                    "timestamp": datetime.utcnow().isoformat()
                }
            
            # Fallback to CSV-based message
            csv_fallback = self._fetch_csv_fallback()
            if csv_fallback:
                return csv_fallback
            
            # Ultimate fallback: hardcoded safe default
            content = (
                "Malaria is a life-threatening disease transmitted by Anopheles mosquitoes. "
                "Prevention: Use insecticide-treated nets, indoor spraying, and antimalarial drugs. "
                "Early treatment with artemisinin-based therapies is critical for recovery."
            )
            
            result = {
                "message": content,
                "source": "SafeDefault",
                "timestamp": datetime.utcnow().isoformat()
            }
            print(f"[MKR] Successfully retrieved content (safe default) (length: {len(content)} chars)")
            return result
            
        except Exception as e:
            # Log error but do NOT propagate exception (fail-safe design)
            print(f"[MKR] ⚠️  Retrieval failed: {e}. Will fallback to CSV.")
            return None
    
    def _fetch_who_malaria_info(self):
        """Fetch malaria information from WHO website."""
        try:
            print("[MKR] Fetching from WHO website...")
            response = requests.get(
                "https://www.who.int/news/fact-sheets/detail/malaria",
                timeout=5,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extract main content paragraphs
            paragraphs = soup.find_all('p')
            content_parts = []
            
            for para in paragraphs[:5]:  # Take first 5 paragraphs
                text = para.get_text().strip()
                if len(text) > 50:  # Only meaningful paragraphs
                    content_parts.append(text)
            
            if content_parts:
                content = " ".join(content_parts)
                # Limit to reasonable length
                if len(content) > 500:
                    content = content[:500] + "..."
                print(f"[MKR] ✓ WHO website content retrieved ({len(content)} chars)")
                return content
            
            return None
            
        except Exception as e:
            print(f"[MKR] ⚠️  WHO website fetch failed: {e}")
            return None
    
    def _fetch_fedgen_malaria_info(self):
        """Fetch malaria information from FEDGEN-PHIS website (Nigeria health system)."""
        try:
            print("[MKR] Fetching from FEDGEN-PHIS website...")
            response = requests.get(
                "https://fedgen.health.gov.ng/phis/malaria",
                timeout=5,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extract main content paragraphs
            paragraphs = soup.find_all('p')
            content_parts = []
            
            for para in paragraphs[:5]:  # Take first 5 paragraphs
                text = para.get_text().strip()
                if len(text) > 50:  # Only meaningful paragraphs
                    content_parts.append(text)
            
            if content_parts:
                content = " ".join(content_parts)
                # Limit to reasonable length
                if len(content) > 500:
                    content = content[:500] + "..."
                print(f"[MKR] ✓ FEDGEN-PHIS website content retrieved ({len(content)} chars)")
                return content
            
            return None
            
        except Exception as e:
            print(f"[MKR] ⚠️  FEDGEN-PHIS website fetch failed: {e}")
            return None
    
    def _fetch_malaria_rss(self, feed_source="WHO-RSS"):
        """Fetch malaria information from RSS feed (WHO or FEDGEN)."""
        try:
            print(f"[MKR] Fetching from {feed_source} feed...")
            
            # Select appropriate RSS feed URL
            if feed_source == "WHO-RSS":
                feed_url = self.rss_feeds.get("WHO-RSS")
            else:  # FEDGEN-RSS
                feed_url = self.rss_feeds.get("FEDGEN-RSS")
            
            if not feed_url:
                return None
            
            feed = feedparser.parse(feed_url)
            
            if not feed.entries:
                return None
            
            # Look for malaria-related entries
            for entry in feed.entries[:5]:
                entry_text = f"{entry.get('title', '')} {entry.get('summary', '')}"
                if 'malaria' in entry_text.lower():
                    content = entry.get('summary', entry.get('title', ''))
                    # Clean HTML tags
                    soup = BeautifulSoup(content, 'html.parser')
                    clean_content = soup.get_text().strip()
                    
                    if len(clean_content) > 50:
                        if len(clean_content) > 500:
                            clean_content = clean_content[:500] + "..."
                        print(f"[MKR] ✓ {feed_source} malaria entry retrieved ({len(clean_content)} chars)")
                        return clean_content
            
            return None
            
        except Exception as e:
            print(f"[MKR] ⚠️  {feed_source} feed fetch failed: {e}")
            return None
    
    def _fetch_csv_fallback(self):
        """Fetch a random malaria message from messages.csv file."""
        try:
            print("[MKR] Fetching fallback content from messages.csv...")
            df = pd.read_csv("messages.csv")
            
            if "message" not in df.columns or "source" not in df.columns:
                print("[MKR] ⚠️  CSV validation failed")
                return None
            
            # Get a random message from CSV
            import random
            idx = random.randint(0, len(df) - 1)
            message = df.loc[idx, "message"]
            source = df.loc[idx, "source"]
            
            print(f"[MKR] ✓ CSV fallback message retrieved from {source}")
            return {
                "message": message,
                "source": f"CSV-{source}",
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            print(f"[MKR] ⚠️  CSV fallback fetch failed: {e}")
            return None


# === Quality Assurance AGENT ===

class QualityAssuranceAgent:        # Validates translation and audio quality
    """
     QA agent that validates translation quality and audio output.
    Implements trust and verification: ensures human-readable Hausa and valid audio.
    """
    def __init__(self):
        print("[INFO] Initializing Quality Assurance Agent...")
        self.min_audio_duration = 1.0  # seconds
    
    def validate_translation(self, en_text, ha_text):
        """
        Validates that Hausa translation is meaningful and differs from English.
        
        Args:
            en_text (str): Original English text
            ha_text (str): Translated Hausa text
        
        Returns:
            bool: True if translation passes validation, False otherwise
        """
        try:
            # Check 1: Hausa text not empty
            if not ha_text or len(ha_text.strip()) == 0:
                print("[QA] ❌ Translation validation failed: Empty Hausa text")
                return False
            
            # Check 2: Hausa differs from English (ensure actual translation occurred)
            if ha_text.strip() == en_text.strip():
                print("[QA] ❌ Translation validation failed: Hausa identical to English")
                return False
            
            # Check 3: Reasonable length (not too short or too long)
            if len(ha_text) < len(en_text) * 0.3:
                print("[QA] ⚠️  Translation validation warning: Hausa much shorter than English")
            
            print("[QA] ✅ Translation validation passed")
            return True
        
        except Exception as e:
            print(f"[QA] ❌ Translation validation error: {e}")
            return False
    
    def validate_audio(self, mp3_path):
        """
        Validates that synthesized audio file is valid and meets minimum duration.
        
        Args:
            mp3_path (str): Path to MP3 file (relative or absolute)
        
        Returns:
            bool: True if audio passes validation, False otherwise
        """
        try:
            # Construct absolute path if needed
            if not os.path.isabs(mp3_path):
                mp3_path = os.path.join("temp_audio", mp3_path)
            
            # Check 1: File exists
            if not os.path.exists(mp3_path):
                print(f"[QA] ❌ Audio validation failed: File not found {mp3_path}")
                return False
            
            # Check 2: File size is reasonable (> 100 bytes)
            file_size = os.path.getsize(mp3_path)
            if file_size < 100:
                print(f"[QA] ❌ Audio validation failed: File too small ({file_size} bytes)")
                return False
            
            # Check 3: Audio duration using pydub
            try:
                audio = AudioSegment.from_mp3(mp3_path)
                duration_seconds = len(audio) / 1000.0
                
                if duration_seconds < self.min_audio_duration:
                    print(f"[QA] ❌ Audio validation failed: Duration {duration_seconds}s < {self.min_audio_duration}s")
                    return False
                
                print(f"[QA] ✅ Audio validation passed (duration: {duration_seconds:.2f}s)")
                return True
            
            except Exception as e:
                print(f"[QA] ⚠️  Could not verify audio duration: {e}. Assuming valid.")
                # Fallback: if we can't verify duration but file exists, assume valid
                return True
        
        except Exception as e:
            print(f"[QA] ❌ Audio validation error: {e}")
            return False


# === ORCHESTRATOR AGENT ===
class OrchestratorAgent:             # Coordinates all agents for autonomous broadcasts
    """
    Orchestrates the autonomous malaria information system.
    Decides content source (MKR vs CSV), coordinates translation → QA → TTS → QA → delivery.
    Implements agent collaboration with graceful fallback.
    """
    def __init__(self, translator, tts_agent, delivery_agent, mkr_agent=None, qa_agent=None):
        """
        Initialize Orchestrator with existing agents via dependency injection.
        All agents are optional; system degrades gracefully if any are None.
        
        Args:
            translator (TranslationAgent): Required for translation
            tts_agent (TTSAgent): Required for text-to-speech
            delivery_agent (DeliveryAgent): Required for WhatsApp delivery
            mkr_agent (MalariaKnowledgeRetriever, optional): For autonomous content retrieval
            qa_agent (QualityAssuranceAgent, optional): For validation
        """
        self.translator = translator
        self.tts_agent = tts_agent
        self.delivery_agent = delivery_agent
        self.mkr_agent = mkr_agent
        self.qa_agent = qa_agent
        print("[ORCH] Orchestrator initialized with dependency injection")
    
    def auto_broadcast(self):
        """
        Attempts autonomous broadcast using MKR if available, falls back to CSV on failure.
        This is the primary entry point for automatic scheduled broadcasts.
        
        Returns:
            bool: True if broadcast succeeded, False otherwise
        """
        print("[ORCH] 🎯 Starting auto-broadcast orchestration...")
        
        # Step 1: Try MKR content, fallback to CSV
        content_data = self._get_broadcast_content()
        if content_data is None:
            print("[ORCH] ❌ Auto-broadcast failed (no content available)")
            return False
        
        en_text = content_data["message"]
        source = content_data["source"]
        
        # Step 2: Process through translation pipeline with QA
        return self.process_message(en_text, source)
    
    def process_message(self, en_text, source):
        """
        Processes a message through the full pipeline: translate → QA → TTS → QA → deliver.
        Implements retry logic and graceful fallback.
        
        Args:
            en_text (str): English message content
            source (str): Source identifier (WHO, FEDGEN, CSV, user, etc.)
        
        Returns:
            bool: True if delivery succeeded, False otherwise
        """
        print(f"[ORCH] 📝 Processing message from {source}")
        
        try:
            # ============ TRANSLATION STAGE ============
            print(f"[ORCH] → Translation stage (EN→HA)")
            ha_text = self.translator.translate(en_text)
            print(f"[ORCH]   ✓ Translation complete")
            
            # ============ TRANSLATION QA STAGE ============
            if self.qa_agent:
                print(f"[ORCH] → Quality check (translation)")
                if not self.qa_agent.validate_translation(en_text, ha_text):
                    print(f"[ORCH]   ⚠️  Translation QA failed. Retrying translation...")
                    ha_text = self.translator.translate(en_text)
                    if not self.qa_agent.validate_translation(en_text, ha_text):
                        print(f"[ORCH]   ❌ Translation QA failed twice. Aborting.")
                        return False
            
            # ============ TTS STAGE ============
            print(f"[ORCH] → Text-to-speech stage (HA→audio)")
            mp3_filename = self.tts_agent.synthesize(ha_text)
            print(f"[ORCH]   ✓ Audio synthesis complete: {mp3_filename}")
            
            # ============ AUDIO QA STAGE ============
            if self.qa_agent:
                print(f"[ORCH] → Quality check (audio)")
                if not self.qa_agent.validate_audio(mp3_filename):
                    print(f"[ORCH]   ⚠️  Audio QA failed. Retrying TTS...")
                    mp3_filename = self.tts_agent.synthesize(ha_text)
                    if not self.qa_agent.validate_audio(mp3_filename):
                        print(f"[ORCH]   ❌ Audio QA failed twice. Aborting.")
                        return False
            
            # ============ DELIVERY STAGE ============
            print(f"[ORCH] → Delivery stage (WhatsApp)")
            
            # Format final message
            separator = "=" * 20
            lang_separator = "_" * 80
            appname = f"{separator} \n  _🌍MalariaPHIS-Hausa_ \n{separator}\n"
            full_text = f"{appname}[EN]🇺🇸  {en_text} _-(Source: {source})_ \n{lang_separator}\n*[HA]🇳🇬  {ha_text}*"
            
            # Get public URL and construct audio URL
            audio_url = f"{os.getenv('PUBLIC_URL')}/temp_audio/{mp3_filename}"
            
            # Broadcast via delivery agent
            self.delivery_agent.broadcast(full_text, audio_url)
            print(f"[ORCH] ✅ Message delivery completed")
            return True
        
        except Exception as e:
            print(f"[ORCH] ❌ Pipeline error: {e}")
            return False
    
    def _get_broadcast_content(self):
        """
        Decides content source: tries MKR first, falls back to CSV.
        Implements orchestration logic for autonomous vs manual content.
        
        Returns:
            dict or None: {"message": str, "source": str, "timestamp": str} or None
        """
        # Try MKR first (autonomous content retrieval)
        if self.mkr_agent:
            print("[ORCH] 🔍 Attempting MKR (Malaria Knowledge Retrieval)...")
            content = self.mkr_agent.fetch_malaria_content()
            if content:
                print("[ORCH]   ✓ MKR provided content")
                return content
            print("[ORCH]   ⚠️  MKR failed, falling back to CSV")
        
        # Fallback: CSV (preserves existing behavior)
        try:
            print("[ORCH] 📋 Falling back to CSV-based content")
            df = pd.read_csv("messages.csv")
            if "message" not in df.columns or "source" not in df.columns:
                print("[ORCH]   ❌ CSV validation failed")
                return None
            
            # Cyclic index to iterate through messages
            index_file = "last_sent.txt"
            idx = (int(open(index_file).read()) + 1 if os.path.exists(index_file) else 0) % len(df)
            open(index_file, "w").write(str(idx))
            
            return {
                "message": df.loc[idx, "message"],
                "source": df.loc[idx, "source"],
                "timestamp": datetime.utcnow().isoformat()
            }
        
        except Exception as e:
            print(f"[ORCH]   ❌ CSV fallback failed: {e}")
            return None

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
    """
    Main broadcast function that delegates to orchestrator.
    Preserves existing CSV-based pipeline while enabling autonomous MKR broadcasts.
    
    Academic Note: Demonstrates graceful integration of new agents with existing system.
    Orchestrator handles: MKR → CSV fallback, translation QA, audio QA, delivery.
    """
    try:
        update_public_url()
        print("\n" + "="*60)
        print("[INFO] 📡 Starting scheduled broadcast via Orchestrator...")
        print("="*60)
        
        # Delegate to orchestrator for full pipeline orchestration
        success = orchestrator.auto_broadcast()
        
        if success:
            print("[INFO] ✅ Broadcast completed successfully")
        else:
            print("[INFO] ⚠️  Broadcast completed with errors (see logs above)")
        
        print("="*60 + "\n")
    
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

# === MKR, QA, ORCHESTRATOR INITIALIZATION ===
mkr_agent = MalariaKnowledgeRetriever()
qa_agent = QualityAssuranceAgent()
orchestrator = OrchestratorAgent(
    translator=translator,
    tts_agent=tts_agent,
    delivery_agent=delivery_agent,
    mkr_agent=mkr_agent,
    qa_agent=qa_agent
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

        print(f"[INFO] User-triggered news broadcast from {sender}")
        
        # Use orchestrator to process user-provided news
        success = orchestrator.process_message(content, f"user:{sender}")
        
        if success:
            return "✅ Your news has been broadcast.", 200
        else:
            return "⚠️  There was an issue broadcasting your news. Please try again.", 200

    return "OK", 200

# === APP ENTRYPOINT ===
if __name__ == "__main__":
    if TESTING_MODE and not os.getenv("PUBLIC_URL"):
        tunnel = ngrok.connect(5000, "http")
        os.environ["PUBLIC_URL"] = tunnel.public_url
        print(f"[INFO] Ngrok tunnel started: {tunnel.public_url}")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
