@startuml MKR_Activity_Diagram
title MKR: Multi-Source Malaria Knowledge Retrieval

start

:Fetch Malaria Content;

:Randomly Select Primary Source
(WHO or FEDGEN-PHIS);

if (Source Selected?) then (WHO)
  if (WHO website available?) then (yes)
    :Fetch & Parse WHO Content;
    if (Valid content?) then (yes)
      :Return WHO Content;
      stop
    else (no)
    endif
  else (no)
  endif
else (FEDGEN-PHIS)
  if (FEDGEN-PHIS available?) then (yes)
    :Fetch & Parse FEDGEN Content;
    if (Valid content?) then (yes)
      :Return FEDGEN Content;
      stop
    else (no)
    endif
  else (no)
  endif
endif

:Try Alternate Primary Source;

if (Alternate Primary available?) then (yes)
  :Fetch & Parse Content;
  if (Valid content?) then (yes)
    :Return Alternate Content;
    stop
  else (no)
  endif
else (no)
endif

if (WHO-RSS available?) then (yes)
  :Parse WHO RSS Feed;
  if (Malaria entry found?) then (yes)
    :Return WHO-RSS Content;
    stop
  else (no)
  endif
else (no)
endif

if (FEDGEN-RSS available?) then (yes)
  :Parse FEDGEN RSS Feed;
  if (Malaria entry found?) then (yes)
    :Return FEDGEN-RSS Content;
    stop
  else (no)
  endif
else (no)
endif

if (messages.csv available?) then (yes)
  :Select Random CSV Message;
  :Return CSV Content;
  stop
else (no)
endif

:Return Safe Default Message;

stop

@enduml

' ============================================================================

@startuml NMT_Activity_Diagram
title NMT: English → Hausa Translation (NLLB-200)

start

:Receive English Text;

:Load NLLB-200 Model;

:Tokenize Text;

:Set Language Token (hau_Latn);

:Generate Translation
(model.generate());

:Decode to Hausa Text;

:Return Hausa Output;

stop

@enduml

' ============================================================================

@startuml TTS_Activity_Diagram
title TTS: Hausa → Audio Synthesis (MMS-TTS-Hausa)

start

:Receive Hausa Text;

:Load MMS-TTS Model;

:Tokenize Hausa Text;

:Generate Waveform
(model inference);

:Create temp_audio dir;

:Write WAV Audio File;

:Convert WAV to MP3;

:Delete WAV (cleanup);

:Return MP3 Filename;

stop

@enduml

' ============================================================================

@startuml Delivery_Statechart
title Delivery: WhatsApp Content Broadcasting

state Delivery {
  [*] --> Idle
  Idle --> FetchSubs: broadcast()
  FetchSubs --> Filter: subscribers_list
  Filter --> Send: active_subs
  Send --> Idle: complete
  Send --> Error: failure
  Error --> Send: retry
}

@enduml

' ============================================================================

@startuml WhatsApp_Sequence
title WhatsApp API Interaction Pipeline

participant User as U
participant Twilio as T
participant MalariaPHIS as M
participant Agents as A

U ->> T: Send WhatsApp Message

T ->> M: POST /twilio Webhook

alt Command (STOP/START)
  M ->> T: Send Confirmation
  T ->> U: Confirm via WhatsApp
else Malaria Update
  M ->> A: fetch_malaria_content()
  A -->> M: malaria_text
  
  M ->> A: translate(english_text)
  A -->> M: hausa_text
  
  M ->> A: synthesize(hausa_text)
  A -->> M: mp3_file
  
  M ->> M: get_subscribers()
  
  loop For each subscriber
    M ->> T: Send Text Message
    M ->> T: Send Audio File
    T ->> U: Receive on WhatsApp
  end
end

M ->> T: Return HTTP 200

@enduml

' ============================================================================

@startuml Session_Memory_ERD
title System Memory: Data Structure

entity Subscriber {
  phone <<PK>>
  status: bool
  last_seen: datetime
}

entity BroadcastMessage {
  msg_id <<PK>>
  timestamp: datetime
  source: string
  en_text: text
  ha_text: text
  audio_url: string
}

entity DeliveryLog {
  log_id <<PK>>
  msg_id <<FK>>
  phone <<FK>>
  timestamp: datetime
  status: string
  twilio_id: string
}

entity ContentCache {
  cache_id <<PK>>
  source: string
  content: text
  expiry: datetime
}

Subscriber ||--o{ DeliveryLog
BroadcastMessage ||--o{ DeliveryLog
ContentCache ||--o{ BroadcastMessage

@enduml

' ============================================================================

@startuml Deployment_Diagram
title System Deployment: MalariaPHIS Multi-Agent Architecture

node Server {
  artifact FlaskApp [ Flask App ]
  artifact Agents [ 6 Agents ]
  artifact Models [ ML Models ]
}

database LocalData [
  Local Storage
  messages.csv
  subscribers.json
]

database Twilio [ Twilio API ]
database WHO [ WHO/FEDGEN ]

entity Users [ WhatsApp Users ]

FlaskApp --> Agents
Agents --> Models
FlaskApp --> LocalData
FlaskApp --> Twilio
Agents --> WHO
Twilio --> Users

@enduml

' ============================================================================
' 
' HOW TO USE THESE DIAGRAMS:
' 
' 1. Copy each @startuml...@enduml block (separated by dashed lines)
' 2. Paste into PlantUML editor or VS Code PlantUML extension
' 3. Generate PNG/SVG/PDF output
' 
' PlantUML Online: https://www.plantuml.com/plantuml/uml/
' VS Code Extension: "PlantUML" by jebbs
' 
' ============================================================================

