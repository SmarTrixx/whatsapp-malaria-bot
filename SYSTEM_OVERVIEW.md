# MalariaPHIS-Hausa: Autonomous Multi-Agent System for WhatsApp Malaria Broadcasting

## Executive Summary

MalariaPHIS-Hausa is a **multi-agent AI system** designed to autonomously generate, validate, and broadcast malaria prevention information to Hausa-speaking communities via WhatsApp. The system orchestrates six specialized agents (TranslationAgent, TTSAgent, DeliveryAgent, MalariaKnowledgeRetriever, QualityAssuranceAgent, and OrchestratorAgent) to implement an end-to-end pipeline from content retrieval through multilingual synthesis to WhatsApp delivery.

**Core Innovation:** Autonomous content retrieval with multi-source fallback strategy (WHO/FEDGEN-PHIS web scraping, RSS feeds, CSV cache) combined with quality validation at each pipeline stage.

---

## System Architecture

### High-Level Pipeline

```
OrchestratorAgent (orchestration & decision)
    ↓
MKR Agent (content: WHO/FEDGEN/RSS/CSV)
    ↓
TranslationAgent (EN → Hausa via NLLB-200)
    ↓
QA Agent (validate translation)
    ↓
TTSAgent (Hausa → MP3 audio via MMS-TTS-Hausa)
    ↓
QA Agent (validate audio)
    ↓
DeliveryAgent (WhatsApp broadcast via Twilio)
    ↓
Subscribers receive multilingual content
```

**Execution Flow:** Seven stages executed sequentially within each broadcast cycle:
1. **Stage 1 (Orchestration):** OrchestratorAgent decides content source and coordinates pipeline
2. **Stage 2 (Content):** MalariaKnowledgeRetriever fetches autonomous content
3. **Stage 3 (Translation):** TranslationAgent converts English to Hausa
4. **Stage 4 (Translation QA):** QualityAssuranceAgent validates translation quality
5. **Stage 5 (Synthesis):** TTSAgent synthesizes Hausa text to MP3 audio
6. **Stage 6 (Audio QA):** QualityAssuranceAgent validates audio properties
7. **Stage 7 (Delivery):** DeliveryAgent broadcasts text + audio to all subscribers

---

## Core Agents

### 1. TranslationAgent
**Purpose:** Convert English content to Hausa for local audiences

**Technology:**
- Model: `facebook/nllb-200-distilled-600M` (NLLB-200 from Meta/Facebook)
- Language Pair: English → Hausa (hau_Latn token)
- Framework: HuggingFace Transformers (PyTorch backend)

**Key Method:** `translate(text: str) → str`
- Input: English text (arbitrary length)
- Process: Tokenize → Load model → Set Hausa token → Generate → Decode
- Output: Hausa translation
- **Failure Mode:** Gracefully propagates; OrchestratorAgent handles errors

---

### 2. TTSAgent (Text-to-Speech)
**Purpose:** Convert Hausa text to natural-sounding MP3 audio

**Technology:**
- Model: `facebook/mms-tts-hau` (Massively Multilingual Speech, Hausa)
- Output Format: MP3 (44.1 kHz, mono)
- Framework: HuggingFace Transformers + PyDub
- Storage: `/temp_audio/<uuid>.mp3` (temporary, cleaned up)

**Key Method:** `synthesize(text: str) → str`
- Input: Hausa text (max ~500 chars recommended)
- Process: Tokenize Hausa → Load VitsModel → Generate waveform → Write WAV → Convert MP3
- Output: MP3 filename (UUID-based)
- Typical Duration: 5-30 seconds depending on text length
- **Failure Mode:** Logs error; OrchestratorAgent triggers rollback

**Audio Validation:** QA Agent checks file existence, size, and duration (minimum 1 second).

---

### 3. DeliveryAgent
**Purpose:** Broadcast finalized messages to WhatsApp subscribers

**Technology:**
- API: Twilio WhatsApp API
- Authentication: Account SID + Auth Token (environment variables)
- Subscriber Tracking: Local JSON file + Twilio sync
- Message Format: Text + media (audio URL)

**Key Methods:**
- `get_subscribers() → List[str]`: Retrieves active subscriber phone numbers
- `broadcast(full_text: str, audio_url: str) → bool`: Sends text + audio to all subscribers

**Data Management:**
- Subscriber file: `subscribers.json` (local persistence)
- Unsubscribe handling: `mark_unsubscribed(phone)` via STOP keyword
- Activity tracking: `record_activity(phone)` on each interaction

**Message Format:**
```
====================
  🌍 MalariaPHIS-Hausa
====================

[EN] 🇺🇸 <English content>
-(Source: WHO/FEDGEN-PHIS/RSS/CSV)

_________________________________________________________________

[HA] 🇳🇬 <Hausa translation>
[🎧] Audio: <public_url_to_mp3>
```

---

### 4. MalariaKnowledgeRetriever (MKR) - Autonomous Content
**Purpose:** Autonomously fetch credible malaria information from trusted health organizations

**Technology Stack:**
- Web Scraping: BeautifulSoup + Requests
- RSS Parsing: Feedparser
- Data Fallback: Pandas (CSV reading)
- Multi-source: Randomly selects primary source each broadcast

**Multi-Tier Fallback Chain:**

**Tier 1 - Primary Web Sources (Randomly Selected):**
1. **WHO Website** - Scrapes fact sheets from `who.int/news/fact-sheets/detail/malaria`
   - Extracts first 5 meaningful paragraphs (>50 chars each)
   - Limits output to 500 chars max
2. **FEDGEN-PHIS** - Nigeria Federal Ministry health system portal at `fedgen.health.gov.ng/phis/malaria`
   - Same extraction logic as WHO
   - Provides localized Nigerian malaria context

**Tier 2 - Alternate Primary Source:**
- If selected source fails, automatically tries the alternate primary source

**Tier 3 - RSS News Feeds:**
1. **WHO RSS Feed** - Disease Outbreak News (https://who.int/feeds/entity/csr/don/en/feed.xml)
   - Searches for malaria-related entries
   - Extracts summary, cleans HTML tags
2. **FEDGEN RSS Feed** - Nigeria health news feed

**Tier 4 - CSV Cache:**
- Reads `messages.csv` (columns: message, source)
- Selects random row for diversity
- Source attribution: `CSV-{original_source}`

**Tier 5 - Safe Default:**
- Hardcoded fallback message: "Malaria is a life-threatening disease transmitted by Anopheles mosquitoes..."
- Ensures system never fails silently

**Key Method:** `fetch_malaria_content() → Dict`
```python
Returns:
{
    "message": "Malaria prevention information...",
    "source": "WHO" | "FEDGEN-PHIS" | "WHO-RSS" | "FEDGEN-RSS" | "CSV-{source}" | "SafeDefault",
    "timestamp": "2026-01-22T10:30:00.000Z"
}
```

**Error Handling:** Never raises exceptions; always returns structured data or None. OrchestratorAgent handles None gracefully.

---

### 5. QualityAssuranceAgent (QA)
**Purpose:** Validate translation quality and audio output at critical pipeline stages

**Two-Stage Validation:**

**Stage 4A - Translation Quality Validation**
Validates Hausa translation with 3 checks:
1. **Non-empty:** Translation must contain text (len > 0)
2. **Language Difference:** Hausa must differ from English (prevents pass-through)
3. **Length Reasonableness:** 20 ≤ word_count ≤ 500 words

**Logic:** All 3 checks must pass. If translation fails QA, OrchestratorAgent retries once. If fails again, aborts broadcast.

**Stage 6B - Audio Quality Validation**
Validates MP3 audio with 3 checks:
1. **File Existence:** MP3 file exists on disk
2. **File Size:** Size > 100 bytes (rules out corrupted/empty files)
3. **Audio Duration:** Duration ≥ 1.0 second

**Logic:** Reads MP3 using PyDub, measures duration. If audio is invalid, aborts broadcast (audio QA is terminal - no retry).

**Key Methods:**
- `validate_translation(en_text, ha_text) → bool`
- `validate_audio(mp3_path) → bool`

**Academic Note:** Demonstrates lightweight verification layer. QA agent is optional (gracefully disabled if unavailable) but recommended for production systems.

---

### 6. OrchestratorAgent
**Purpose:** Coordinate all agents, manage fallback logic, implement fail-safe orchestration

**Dependency Injection Model:**
```python
orchestrator = OrchestratorAgent(
    translator=TranslationAgent(),
    tts_agent=TTSAgent(),
    delivery_agent=DeliveryAgent(...),
    mkr_agent=MalariaKnowledgeRetriever(),  # Optional
    qa_agent=QualityAssuranceAgent()         # Optional
)
```

All agents are optional; system degrades gracefully if any are unavailable.

**Two Entry Points:**

**1. `auto_broadcast()` - Scheduled Autonomous Broadcasting**
- Triggered by scheduler (every 7 minutes in testing, 9 AM daily in production)
- Delegates to `_get_broadcast_content()` for source selection
- Calls `process_message()` for full pipeline orchestration
- Returns: bool (success/failure)

**2. `process_message(en_text, source)` - Full Pipeline Orchestration**
- Input: English text + source identifier
- Orchestrates all seven stages:
  ```
  translate(en_text)
    ↓ [QA validation if enabled]
  synthesize(ha_text)
    ↓ [QA validation if enabled]
  broadcast(text, audio_url)
  ```
- Returns: bool (success/failure)

**Content Source Strategy:**

**Primary:** Attempts MKR autonomous content retrieval
```
If MKR succeeds → Use MKR content
Else → Fallback to CSV cyclic message
```

**Fallback Logic:**
- MKR Agent implements internal 5-tier fallback (WHO → FEDGEN → RSS → CSV → Safe Default)
- Orchestrator only falls back to CSV if MKR returns None
- CSV uses cyclic indexing (increments pointer each broadcast, wraps around)

**Error Handling - Retry Strategy:**
- **Translation Failure:** Retries once; aborts if fails twice
- **Translation QA Failure:** Retries translation once; aborts if QA fails twice
- **Audio Synthesis Failure:** Aborts immediately (no retry)
- **Audio QA Failure:** Aborts immediately (no retry)
- **Delivery Failure:** Aborts but logs error

---

## Data Structures

### Subscriber Management
```json
{
  "whatsapp:+2348123456789": {
    "unsubscribed": false,
    "last_seen": "2026-01-22T10:30:00.000Z"
  }
}
```
**Storage:** `subscribers.json` (local file)
**Sync:** Loaded from Twilio API on startup; updated on each interaction

### Broadcast Message
```json
{
  "english": "Malaria prevention requires...",
  "hausa": "Jiya malaria shine...",
  "audio_url": "https://public.url/temp_audio/a1b2c3d4.mp3",
  "source": "WHO",
  "timestamp": "2026-01-22T10:30:00.000Z"
}
```

---

## Integration Points

### 1. Flask Web Application
- **Route: `/twilio`** - WhatsApp webhook receiver
  - Receives incoming messages from Twilio
  - Parses sender phone + message body
  - Handles commands: STOP/START (subscription management)
  - Supports user-triggered broadcasts: "malaria news update <content>"
  - Returns HTTP 200 OK to Twilio

- **Route: `/`** - Health check
  - Returns: "✅ Agentic malaria AI is running!"

- **Route: `/temp_audio/<file>`** - Audio file server
  - Serves MP3 files from `temp_audio/` directory
  - Generates public URL for WhatsApp media attachment

### 2. Twilio WhatsApp API
- **Bidirectional Communication:**
  - Inbound: Flask webhook receives messages
  - Outbound: DeliveryAgent sends text + audio via Twilio client
- **Rate Limiting:** Depends on Twilio account tier
- **Media Hosting:** Audio files served via public Flask route

### 3. Background Scheduler (APScheduler)
- **Testing Mode:** Broadcasts every 7 minutes
- **Production Mode:** Broadcasts daily at 9 AM (Africa/Lagos timezone)
- **Timezone:** Africa/Lagos (Nigeria)

### 4. Environment Configuration (.env)
```
TWILIO_ACCOUNT_SID=<from Twilio console>
TWILIO_AUTH_TOKEN=<from Twilio console>
TWILIO_NUMBER=whatsapp:+<your_twilio_number>
PUBLIC_URL=https://<ngrok_or_production_domain>
PORT=5000
```

### 5. CSV Data File
**Filename:** `messages.csv`
**Required Columns:** message, source
**Usage:** Fallback content for MKR or primary source for CSV-only mode
**Format:**
```csv
message,source
"Malaria is a serious disease transmitted by mosquitoes...","WHO"
"Use insecticide-treated bed nets for protection...","CDC"
"Visit health facilities for early treatment...","FEDGEN"
```

---

## Execution Workflow

### Scheduled Broadcast (Every 7 mins/Daily at 9 AM)
```
1. Scheduler triggers broadcast()
2. broadcast() calls orchestrator.auto_broadcast()
3. Orchestrator calls _get_broadcast_content()
   → Attempts MKR.fetch_malaria_content()
   → Falls back to CSV if MKR fails
4. Returns {message, source, timestamp}
5. Orchestrator calls process_message(message, source)
6. Stage 1-7 pipeline executes sequentially
7. On success: Messages delivered to all active subscribers
8. On failure: Logged; next broadcast scheduled
```

### User-Triggered Command (Incoming WhatsApp)
```
1. User sends "malaria news update <content>" to bot
2. Twilio webhook calls /twilio route
3. Flask extracts message body
4. orchestrator.process_message(content, f"user:{sender}")
5. Content runs through full pipeline
6. Responds to user: "✅ Your news has been broadcast" or "⚠️  Error"
```

### Subscription Management (Incoming WhatsApp)
```
User: "STOP"
→ mark_unsubscribed(phone)
→ Update subscribers.json
→ Excluded from future broadcasts

User: "START"
→ record_activity(phone)
→ Update subscribers.json
→ Sent re-subscription confirmation
→ Included in future broadcasts
```

---

## Technology Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| **Framework** | Flask | 2.x |
| **Translation** | HuggingFace NLLB-200 | distilled-600M |
| **TTS** | HuggingFace MMS-TTS-Hausa | facebook/mms-tts-hau |
| **PyTorch** | Deep Learning Backend | 2.0+ |
| **Messaging** | Twilio WhatsApp API | Latest |
| **Scheduling** | APScheduler | 3.10+ |
| **Web Scraping** | BeautifulSoup + Requests | 4.x |
| **Data Processing** | Pandas | 1.5+ |
| **Audio Processing** | PyDub + FFmpeg | 0.25+, /usr/bin/ffmpeg |
| **Testing/Dev** | Ngrok | Latest (tunneling) |
| **Python** | CPython | 3.8+ |
| **OS** | Linux | Any (tested on Ubuntu) |

---

## Key Design Principles

### 1. Fail-Safe Design
- **No Silent Failures:** Every agent logs status (success/warning/error)
- **Multi-Tier Fallback:** MKR implements 5-tier fallback chain; Orchestrator implements CSV fallback
- **Exception Isolation:** Each agent catches exceptions internally; never propagates

### 2. Autonomous Operation
- **Zero Manual Intervention:** Scheduled broadcasts operate independently
- **Content Freshness:** MKR fetches latest WHO/FEDGEN content automatically
- **Random Source Selection:** Each broadcast randomly selects primary source (WHO or FEDGEN-PHIS) for diversity

### 3. Quality Assurance
- **Two-Stage Validation:** Translation QA + Audio QA at critical pipeline stages
- **Retry Logic:** Single retry for translation; terminal aborts for audio
- **Source Attribution:** Every message tagged with source (WHO, FEDGEN, etc.)

### 4. Modularity & Extensibility
- **Dependency Injection:** All agents are optional; new agents easily added
- **Agent Interface:** Each agent implements consistent interface (init, key_method)
- **CSV Extension:** New content sources added to CSV without code changes
- **RSS Feed Extension:** New feeds added to MKR.rss_feeds dictionary

### 5. Multi-Source Trust
- **Credible Sources:** WHO (international authority) + FEDGEN-PHIS (local Nigeria health authority)
- **Multiple Representations:** Web + RSS feeds + CSV cache ensures availability
- **Fallback Chain:** 5-tier strategy ensures system never lacks content

---

## Performance Metrics

### Typical Latency Per Stage
| Stage | Component | Latency |
|-------|-----------|---------|
| 1 | MKR (WHO web) | 2-5 sec |
| 2 | MKR (FEDGEN web) | 2-5 sec |
| 3 | MKR (RSS parse) | 1-3 sec |
| 3 | MKR (CSV load) | <100 ms |
| 4 | Translation (NLLB) | 2-5 sec |
| 5 | Translation QA | <100 ms |
| 6 | TTS (MMS) | 5-15 sec |
| 7 | Audio QA | 1-3 sec |
| 8 | Delivery (Twilio) | 2-10 sec |
| **Total (Typical)** | **End-to-End** | **15-45 sec** |

### Resource Requirements
- **Memory:** 4-6 GB (model loading)
- **CPU:** 2+ cores (translation + TTS inference)
- **GPU:** Optional (accelerates translation/TTS 5-10x)
- **Storage:** 2 GB (model caches + temp audio)
- **Network:** HTTPS connectivity to WHO, FEDGEN, Twilio APIs

---

## Limitations & Future Work

### Current Limitations
1. **Web Scraping Brittleness:** HTML structure changes break extraction
2. **RSS Feed Dependency:** If feeds unavailable, falls back to CSV
3. **Language Limitation:** Only English → Hausa; no bidirectional translation
4. **Model Size:** NLLB-200 (600M parameters) requires 6 GB RAM
5. **Subscriber Sync:** Local JSON may drift from Twilio API if out of sync

### Future Enhancements
1. **API Wrapper:** WHO/FEDGEN official APIs instead of web scraping
2. **Multi-Language:** Support EN→Yoruba, EN→Igbo for West African regions
3. **Caching:** Cache WHO/FEDGEN content for 24 hours to reduce API calls
4. **Analytics:** Track engagement metrics (delivery rate, read rate, unsubscribe rate)
5. **User Feedback:** Collect ratings on broadcast content quality
6. **Content Moderation:** NLP-based filtering for harmful/misinformation content
7. **Sentiment Analysis:** Gauge public sentiment on malaria topics

---

## Academic Contributions

This system demonstrates:

1. **Autonomous Multi-Agent Orchestration:** Coordination of 6 specialized agents with clear separation of concerns
2. **Multi-Source Information Retrieval:** Robust fallback chain for autonomous content gathering
3. **Quality Assurance in ML Pipelines:** Two-stage validation (translation + audio) in production system
4. **Fail-Safe Design Patterns:** Graceful degradation when agents unavailable
5. **Language Technology Integration:** NLLB-200 + MMS-TTS applied to underrepresented language (Hausa)
6. **Healthcare Accessibility:** WhatsApp-based dissemination for low-bandwidth communities

---

## Conclusion

MalariaPHIS-Hausa provides an extensible, resilient framework for autonomous health information broadcasting to understaffed communities. The multi-agent architecture enables specialization (each agent has single responsibility) while maintaining system-level robustness through orchestration and fallback logic. The system prioritizes reliability over feature richness, implementing multiple content sources and validation stages to ensure malaria prevention information reaches Hausa speakers accurately and consistently.

