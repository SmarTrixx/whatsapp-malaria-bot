    # ===================================================
    # MalariaPHIS-Hausa Setup & Usage Documentation
    # ===================================================

    """
    Malaria-PHIS AI Agent: Setup & Usage Guide
    ==========================================

    This guide will help you set up and run the Malaria-PHIS AI Agent for WhatsApp-based malaria news broadcasting in Hausa.

    1. Prerequisites
    ----------------
    - Python 3.8+
    - pip
    - ffmpeg (system binary, e.g., /usr/bin/ffmpeg)
    - Ngrok (for local testing)
    - Twilio account (for WhatsApp messaging)
    - Facebook HuggingFace models access

    2. Required Files
    -----------------
    - finalAppTwilio.py         # Main application code (this file)
    - .env                      # Environment variables (see below)
    - messages.csv              # CSV file with columns: message, source
    - subscribers.json          # Will be auto-created for subscriber tracking
    - temp_audio/               # Directory for temporary audio files (auto-created)

    3. .env File Example
    --------------------
    Create a `.env` file in the project root with the following content:

    TWILIO_ACCOUNT_SID=your_twilio_account_sid
    TWILIO_AUTH_TOKEN=your_twilio_auth_token
    TWILIO_NUMBER=whatsapp:+your_twilio_whatsapp_number
    PUBLIC_URL=https://your-ngrok-or-production-url
    PORT=5000

    4. messages.csv Example
    -----------------------
    Create a `messages.csv` file with at least these columns:

    message,source
    "Malaria is a serious disease in Africa.","WHO"
    "Use mosquito nets to prevent malaria.","CDC"

    5. Install Dependencies
    -----------------------
    Run the following commands:

    pip install -r requirements.txt
    # or manually:
    pip install flask python-dotenv pydub pandas torch transformers soundfile apscheduler twilio pytz pyngrok

    6. System Dependencies
    ----------------------
    - Install ffmpeg (Linux): sudo apt-get install ffmpeg
    - Install ffmpeg (Mac): brew install ffmpeg
    - windows: Download from https://ffmpeg.org/download.html and add to PATH.

    7. Running the App
    ------------------
    - For local testing, ensure Ngrok is installed (`pip install pyngrok`).
    - Run: python finalAppTwilio.py
    - The app will start, and Ngrok will provide a public URL for Twilio webhook configuration.

    8. Twilio Setup
    ---------------
    - Set up a Twilio WhatsApp sender.
    - Configure Twilio webhook to point to: https://your-ngrok-url/twilio

    9. Usage
    --------
    - Users can subscribe/unsubscribe by sending WhatsApp messages like "START", "STOP", etc.
    - To broadcast a custom news update, send a WhatsApp message starting with "malaria news update ...".

    10. Troubleshooting
    -------------------
    - Ensure all environment variables are set.
    - Check ffmpeg path if audio conversion fails.
    - Inspect logs for errors.

    11. File Structure
    ------------------
    /finalAppTwilio.py
    /.env
    /messages.csv
    /subscribers.json
    /temp_audio/

    12. References
    --------------
    - HuggingFace models: facebook/nllb-200-distilled-600M, facebook/mms-tts-hau
    - Twilio WhatsApp API: https://www.twilio.com/docs/whatsapp
    - Ngrok: https://ngrok.com/

    """

