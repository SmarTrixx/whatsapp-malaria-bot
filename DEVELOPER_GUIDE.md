# MalariaPHIS-Hausa: Developer Quick Reference

## 📋 Quick Links

- **Main Application:** `finalAppTwilio.py` (541 lines)
- **Implementation Summary:** `IMPLEMENTATION_SUMMARY.md`
- **Verification Report:** `VERIFICATION_REPORT.md`
- **Execution Examples:** `EXECUTION_EXAMPLES.md`
- **Architecture Analysis:** `ARCHITECTURAL_ANALYSIS.md`

---

## 🚀 Running the System

### Start the Application
```bash
# Set environment variables
export TWILIO_ACCOUNT_SID="your_sid"
export TWILIO_AUTH_TOKEN="your_token"
export TWILIO_NUMBER="whatsapp:+1234567890"
export PUBLIC_URL="https://your-ngrok-url"
export PORT=5000

# Run the application
python finalAppTwilio.py
```

### Testing Locally with Ngrok
The application automatically creates an ngrok tunnel in TESTING_MODE:
```
[INFO] Ngrok tunnel started: https://abc123.ngrok.io
```

### Scheduled Broadcasts
- **Testing:** Every 7 minutes (configured in `timeinterval`)
- **Production:** Daily at 9:00 AM West Africa Time (Lagos)

### User-Triggered Messages
Send WhatsApp messages to the bot:
- `STOP` / `STOPALL` / `UNSUBSCRIBE` - Unsubscribe
- `START` / `UNSTOP` - Re-subscribe
- `malaria news update <content>` - Broadcast user-provided news

---

## 🏗️ Code Organization

### Agents by Lines
| Component | Lines | Status |
|-----------|-------|--------|
| TranslationAgent | 63-70 | Original ✅ |
| TTSAgent | 72-83 | Original ✅ |
| DeliveryAgent | 85-117 | Original ✅ |
| MalariaKnowledgeRetriever | 121-161 | **NEW** |
| QualityAssuranceAgent | 164-236 | **NEW** |
| OrchestratorAgent | 239-414 | **NEW** |
| Utility Functions | 32-60 | Original ✅ |
| Flask App | 480+ | Enhanced |
| Configuration | 18-30 | Original ✅ |

---

## 🔧 Configuration & Customization

### Disable MKR (Use CSV Only)
```python
# In agent initialization
mkr_agent = None  # or MalariaKnowledgeRetriever()

orchestrator = OrchestratorAgent(
    translator=translator,
    tts_agent=tts_agent,
    delivery_agent=delivery_agent,
    mkr_agent=None,  # ← Disabled
    qa_agent=qa_agent
)
```

### Disable QA (Skip Validation)
```python
qa_agent = None  # or QualityAssuranceAgent()

orchestrator = OrchestratorAgent(
    translator=translator,
    tts_agent=tts_agent,
    delivery_agent=delivery_agent,
    mkr_agent=mkr_agent,
    qa_agent=None  # ← Disabled
)
```

### Change Broadcast Interval
```python
# Testing: every 7 minutes
timeinterval = 7

# Production: daily at 9 AM
timeinterval = 1440  # (24 hours in minutes)

# Or use cron trigger in scheduler:
# sched.add_job(broadcast, trigger="cron", hour=9, minute=0)
```

### Change Audio Duration Threshold
```python
qa_agent.min_audio_duration = 0.5  # seconds (default: 1.0)
```

### Add New Content Source to MKR
```python
# MKR agent now randomly selects between primary sources
def __init__(self):
    self.primary_sources = {
        "WHO": {
            "url": "https://www.who.int/news/fact-sheets/detail/malaria",
            "type": "web"
        },
        "FEDGEN-PHIS": {
            "url": "https://fedgen.health.gov.ng/phis/malaria",
            "type": "web"
        },
        # Add new primary source here:
        # "NEW_SOURCE": { "url": "https://...", "type": "web" }
    }
    self.rss_feeds = {
        "WHO-RSS": "https://www.who.int/feeds/entity/csr/don/en/feed.xml",
        "FEDGEN-RSS": "https://fedgen.health.gov.ng/feeds/malaria",
        # Add new RSS feed here:
        # "NEW_RSS": "https://..."
    }

# Implement new fetch method (optional):
def _fetch_newsource_malaria_info(self):
    """Fetch from new source"""
    # Follow pattern of _fetch_who_malaria_info() or _fetch_fedgen_malaria_info()
```

**Fallback Chain (Automatic):**
1. Try randomly selected primary source
2. Try alternate primary source
3. Try WHO RSS feed
4. Try FEDGEN RSS feed
5. Try random CSV message
6. Use safe default message

---

## 🐛 Debugging Tips

### Enable Verbose Logging
The system logs prefixes make debugging easy:
```
[INFO]   - System information
[ORCH]   - Orchestrator decisions
[MKR]    - Knowledge retrieval events
[QA]     - Validation results
[ERROR]  - Critical failures
[📥MSG]  - Incoming messages
[📤MSG]  - Outgoing confirmations
```

### Check Broadcast Status
Look for:
- `[ORCH] ✅ Message delivery completed` - Success
- `[ORCH] ❌ Pipeline error` - Failure
- `[ORCH] ⚠️ Falling back to CSV` - Fallback triggered
- `[QA] ❌ Validation failed` - QA issue

### Test MKR Integration
```python
# In Python shell
from finalAppTwilio import mkr_agent
result = mkr_agent.fetch_malaria_content()
print(result)
```

### Test Translation QA
```python
from finalAppTwilio import qa_agent, translator

en_text = "Malaria is a disease"
ha_text = translator.translate(en_text)
is_valid = qa_agent.validate_translation(en_text, ha_text)
print(f"Valid: {is_valid}")
```

### Test Audio QA
```python
from finalAppTwilio import qa_agent

is_valid = qa_agent.validate_audio("temp_audio/sample.mp3")
print(f"Audio valid: {is_valid}")
```

### Manually Trigger Broadcast
```bash
# SSH into server
python -c "from finalAppTwilio import broadcast; broadcast()"
```

---

## 📊 Monitoring & Maintenance

### Key Files to Monitor
- `subscribers.json` - Active subscriber list
- `last_sent.txt` - Current CSV index
- `temp_audio/` - Generated audio files (auto-cleaned)
- Application logs - Real-time system status

### Regular Tasks
- Clean up old audio files in `temp_audio/`
- Review `subscribers.json` for inactive users
- Monitor Twilio message logs for delivery issues
- Test MKR API connectivity periodically

### Performance Metrics
- Broadcast latency: 4-30 seconds (see ARCHITECTURAL_ANALYSIS.md)
- Subscriber throughput: ~1 per second
- Audio file size: 20-100 KB per message
- Model memory: ~2-3 GB (TransformersHF + Torch)

---

## 🛠️ Common Issues & Solutions

### Issue: "ModuleNotFoundError: No module named 'torch'"
**Solution:** Install dependencies
```bash
pip install torch transformers pydub soundfile flask-cors python-dotenv twilio apscheduler pyngrok
```

### Issue: ffmpeg not found
**Solution:** Install ffmpeg system package
```bash
# Ubuntu/Debian
sudo apt-get install ffmpeg

# macOS
brew install ffmpeg

# Windows
choco install ffmpeg
```

### Issue: No subscribers receiving messages
**Solution:** Check Twilio logs and subscriber file
```bash
# View active subscribers
cat subscribers.json

# Check Twilio message history
# (from Twilio dashboard)
```

### Issue: Audio files growing too large
**Solution:** Enable audio cleanup
```bash
# Add to broadcast() after successful delivery:
import os
from pathlib import Path

old_audio_dir = Path("temp_audio")
for audio_file in old_audio_dir.glob("*.mp3"):
    age = (datetime.now() - Path(audio_file).stat().st_mtime)
    if age.total_seconds() > 3600:  # 1 hour
        audio_file.unlink()
```

### Issue: Orchestrator not found in globals
**Solution:** Ensure initialization completes
```python
# orchestrator = OrchestratorAgent(...)  must be BEFORE scheduler starts
sched.add_job(broadcast, ...)
sched.start()
```

---

## 📚 API Reference

### MalariaKnowledgeRetriever

```python
mkr = MalariaKnowledgeRetriever()

# Fetch content
content = mkr.fetch_malaria_content()
# Returns: {
#     "message": str,
#     "source": str,
#     "timestamp": str
# } or None on failure
```

### QualityAssuranceAgent

```python
qa = QualityAssuranceAgent()

# Validate translation
is_valid = qa.validate_translation(
    en_text="...",
    ha_text="..."
)
# Returns: bool

# Validate audio
is_valid = qa.validate_audio(
    mp3_path="temp_audio/sample.mp3"
)
# Returns: bool
```

### OrchestratorAgent

```python
orch = OrchestratorAgent(
    translator=translator_agent,
    tts_agent=tts_agent,
    delivery_agent=delivery_agent,
    mkr_agent=mkr_agent,  # Optional
    qa_agent=qa_agent  # Optional
)

# Auto broadcast (scheduled)
success = orch.auto_broadcast()
# Returns: bool

# Process custom message
success = orch.process_message(
    en_text="Message in English",
    source="USER"
)
# Returns: bool
```

### DeliveryAgent (Unchanged)

```python
delivery = DeliveryAgent(
    sid=os.getenv("TWILIO_ACCOUNT_SID"),
    token=os.getenv("TWILIO_AUTH_TOKEN"),
    from_number=os.getenv("TWILIO_NUMBER")
)

# Get subscribers
subs = delivery.get_subscribers()
# Returns: list of WhatsApp numbers

# Broadcast to all
delivery.broadcast(
    full_text="Message text...",
    audio_url="https://..."
)
```

### TranslationAgent (Unchanged)

```python
translator = TranslationAgent()

# Translate to Hausa
hausa_text = translator.translate(
    text="English text..."
)
# Returns: str (Hausa)
```

### TTSAgent (Unchanged)

```python
tts = TTSAgent()

# Synthesize audio
filename = tts.synthesize(
    text="Hausa text..."
)
# Returns: str (filename in temp_audio/)
```

---

## 🔄 Integration Points

### Flask Routes
```python
@app.route("/")
# System status - unchanged

@app.route("/temp_audio/<file>")
# Serve audio files - unchanged

@app.route("/twilio", methods=["POST"])
# Receive WhatsApp - ENHANCED to use orchestrator
```

### Scheduler
```python
# Testing: every N minutes
sched.add_job(broadcast, trigger="interval", minutes=timeinterval)

# Production: daily at 9 AM
sched.add_job(broadcast, trigger="cron", hour=9, minute=0)
```

---

## 📝 Key Code Examples

### Example 1: Use System with Custom Message
```python
from finalAppTwilio import orchestrator

success = orchestrator.process_message(
    en_text="Malaria prevention is important",
    source="CustomSource"
)

if success:
    print("Message delivered!")
else:
    print("Failed to deliver")
```

### Example 2: Disable QA for Performance
```python
# Modify initialization
qa_agent = None

orchestrator = OrchestratorAgent(
    translator=translator,
    tts_agent=tts_agent,
    delivery_agent=delivery_agent,
    mkr_agent=mkr_agent,
    qa_agent=None  # Skip validation
)
# System runs faster but without quality checks
```

### Example 3: Monitor MKR Success Rate
```python
success_count = 0
attempts = 100

for i in range(attempts):
    content = mkr_agent.fetch_malaria_content()
    if content:
        success_count += 1

print(f"MKR Success Rate: {success_count/attempts*100:.1f}%")
```

---

## 🚀 Deployment Checklist

- [ ] All environment variables set (TWILIO_*, PUBLIC_URL, PORT)
- [ ] Dependencies installed (`pip install -r requirements.txt`)
- [ ] ffmpeg system package installed
- [ ] `messages.csv` present with "message" and "source" columns
- [ ] Twilio account configured with WhatsApp sandbox or production
- [ ] Public URL configured (Ngrok in testing, proper URL in production)
- [ ] Verify logs show successful initialization of all agents
- [ ] Test broadcast with known subscriber
- [ ] Monitor first few broadcasts for errors
- [ ] Set up log aggregation (optional but recommended)

---

**Last Updated:** January 22, 2026

**System Version:** MalariaPHIS-Hausa with Multi-Agent Orchestration v1.0
