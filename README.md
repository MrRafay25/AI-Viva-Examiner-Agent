# 🎓 Agentic AI Oral Examination & Viva System (BSAI Capstone)

An autonomous, multi-modal oral examination platform engineered with Python, Flask, and the Google Gemini Flash LLM. The system ingests academic curriculum notes via dynamic PDF parsing, constructs interactive examination sessions, conducts bilingual (Roman Urdu + English) voice evaluations, and persists student assessment data into a relational SQLite database.

---

## 🌟 Key Architectural Features

- **Document Ingestion (RAG Ground Truth):** Ingests course syllabus and lecture notes directly via `PyPDF2`, dynamically constraining evaluation questions to the supplied curriculum.
- **Agentic Session State Management:** Tracks multi-turn conversational context, student responses, and progression state across sequential viva tiers.
- **Dynamic Question Generation:** Utilizes generative reasoning alongside randomized question pools to eliminate predictability across consecutive student sessions.
- **Bilingual Multi-Modal Voice Pipeline:** Employs browser-native Web Speech API for low-latency Speech-to-Text (STT) alongside server-synthesized Google Text-to-Speech (`gTTS`) encoded in base64 audio streams.
- **Fail-Safe Low-Latency REST Architecture:** Connects via direct HTTPS endpoints with strict request timeouts (4 seconds) and deterministic fallback routing to prevent Windows socket deadlocks.
- **Persistent Evaluation Storage:** Automatically commits complete Q&A transcripts, quantitative scores, qualitative feedback, and timestamps to an SQLite relational database (`viva_records.db`).
- **Interactive Examiner Dashboard:** Provides academic evaluators with a unified management interface to inspect student performance metrics and view full conversational transcripts via dynamic modal windows.

---

## 🛠️ Technology Stack

| Layer | Technology |
|---|---|
| **Backend Framework** | Python 3.10+ / Flask |
| **Large Language Model** | Google Gemini 3.8 Flash (via Google Generative Language REST API) |
| **Document Processing** | PyPDF2 |
| **Voice Synthesis (TTS)** | Google Text-to-Speech (`gTTS`) / Base64 Audio Streaming |
| **Speech Recognition (STT)**| Web Speech API (`webkitSpeechRecognition`) |
| **Database Layer** | SQLite3 |
| **Frontend UI/UX** | HTML5, CSS3 Modern Flexbox, Vanilla JavaScript ES6 |

---

## 📂 Project Structure

```text
AI_Viva_Agent/
│
├── app.py                  # Core Flask application, REST routes, Gemini API client
├── viva_records.db         # Persistent SQLite database storing student records
│
└── templates/
    ├── index.html          # Student Examination HUD with real-time audio visualizer & timer
    └── records.html        # Examiner Dashboard with interactive transcript modal views