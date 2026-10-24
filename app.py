import os
import io
import re
import base64
import sqlite3
import random
import traceback
import requests
from datetime import datetime
from flask import Flask, render_template, request, jsonify
import PyPDF2
from gtts import gTTS

app = Flask(__name__)

# ==========================================
# CONFIGURATION & DATABASE
# ==========================================
GEMINI_API_KEY = "AQ.Ab8RN6KKbOrVCLOyn9Vr1t22zH2ONSWX7P91FkYxj6CRNPC5XA"
DB_NAME = "viva_records.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS viva_evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_name TEXT NOT NULL,
            roll_no TEXT NOT NULL,
            score TEXT,
            grade TEXT,
            transcript TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()
    print("[DATABASE] SQLite table initialized successfully.")

init_db()

# Active Session State
viva_session = {
    "pdf_text": "",
    "student_name": "",
    "roll_no": "",
    "question_count": 0,
    "max_questions": 3,
    "chat_history": []
}

# Dynamic Fallback Question Pools
Q1_POOL = [
    ("Supervised aur Unsupervised Learning me kya bunyadi farq hota hai?", "سپروائزڈ اور ان سپروائزڈ لرننگ میں کیا بنیادی فرق ہے؟"),
    ("Machine Learning me Bias aur Variance Tradeoff se kya murad hai?", "بائیس اور ویرینس ٹریڈ آف سے کیا مراد ہے؟"),
    ("Classification model evaluate karne ke liye Precision aur Recall me kya farq hai?", "پریسیژن اور ریکال میں کیا فرق ہوتا ہے؟"),
    ("Data Preprocessing me Feature Scaling aur Normalization kyun zaroori hoti hai?", "فیچر سکیلنگ اور نارملائزیشن کیوں ضروری ہے؟"),
    ("Loss Function aur Cost Function ke darmiyan kya farq hota hai?", "لاس فنکشن اور کاسٹ فنکشن کے درمیان کیا فرق ہے؟")
]

Q2_POOL = [
    ("Machine learning models me Overfitting kya hoti hai aur L1/L2 Regularization isko kaise rokti hai?", "اوور فٹنگ کیا ہوتی ہے اور ریگولرائزیشن اسے کیسے روکتی ہے؟"),
    ("Deep Learning me Vanishing Gradient problem kya hota hai aur yeh kab paish aata hai?", "وینشنگ گریڈینٹ پرابلم کیا ہے؟"),
    ("Gradient Descent ke mukhtalif types jaise SGD aur Adam Optimizer me kya farq hai?", "گریڈینٹ ڈیسینٹ اور ایڈم آپٹمائزر میں کیا فرق ہے؟"),
    ("Curse of Dimensionality kya hota hai aur PCA ise kaise hal karta hai?", "کرس آف ڈائمینشنلٹی کیا ہے اور پی سی اے اسے کیسے حل karta hai?"),
    ("K-Fold Cross-Validation ka process model evaluation me kyun mufeed mana jata hai?", "کے فولڈ کراس ویلیڈیشن کیوں مفید ہے؟")
]

Q3_POOL = [
    ("Neural Networks me Activation Functions jaise ReLU ya Sigmoid ka bunyadi role kya hai?", "نیورل نیٹ ورکس میں ایکٹیویشن فنکشنز کا کیا کردار ہے؟"),
    ("Deep Neural Networks me Dropout aur Batch Normalization ka kya maqsad hota hai?", "ڈراپ آؤٹ اور بیچ نارملائزیشن کا کیا مقصد ہے؟"),
    ("Computer Vision me Convolutional layers (CNN) dense layers ke muqablay me kyun behtar hain?", "سی این این ڈینس لیئرز کے مقابلے میں کیوں بہتر ہے؟"),
    ("Transfer Learning kya hoti hai aur pre-trained models ko Fine-tune kaise kiya jata hai?", "ٹرانسفر لرننگ اور فائن ٹیوننگ سے کیا مراد ہے؟"),
    ("Epoch, Batch Size, aur Iteration ke darmiyan kya takneeki farq hota hai?", "ایپوک، بیچ سائز اور اِٹریشن میں کیا فرق ہے؟")
]

# Strict Filter to Catch Begging, Ignorance, and Filler Bluffs
BLUFF_PATTERNS = [
    r"(ni|nahi|nhi|na|not|dont|don't)\s*(ata|aata|aati|aate|pata|pta|maloom|malom|samajh|know|idea)",
    r"number\s*(de\s*do|dedo|chahiye|dein)",
    r"pass\s*(kardo|krdo|kr\s*do|kar\s*do)",
    r"please|plz|meharbani",
    r"ahem\s*role",
    r"moderen\s*tareek",
    r"no\s*verbal\s*response",
    r"idk|skip|pass"
]

def is_meaningful_answer(ans_text):
    clean = ans_text.lower().strip()
    if not clean:
        return False
        
    for pattern in BLUFF_PATTERNS:
        if re.search(pattern, clean):
            return False
            
    # Sirf 1, 2 ya 3 words hone par bhi reject
    if len(clean.split()) < 4:
        return False
        
    return True

def ask_gemini_quick(prompt_text, fallback_tuple):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    payload = {"contents": [{"parts": [{"text": prompt_text}]}]}

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:
        pass

    eng_text, urdu_text = fallback_tuple
    return f"{eng_text} ||| {urdu_text}"

def text_to_audio_base64(text_to_speak):
    try:
        clean_text = text_to_speak.replace("*", "").replace("#", "").strip()
        if not clean_text:
            return ""
        tts = gTTS(text=clean_text[:120], lang='ur', slow=False)
        fp = io.BytesIO()
        tts.write_to_fp(fp)
        fp.seek(0)
        return base64.b64encode(fp.read()).decode('utf-8')
    except Exception:
        return ""

def save_record_to_db(student_name, roll_no, score, grade, transcript):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            INSERT INTO viva_evaluations (student_name, roll_no, score, grade, transcript, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (student_name, roll_no, score, grade, transcript, now))
        conn.commit()
        conn.close()
        print(f"[DATABASE] Saved record for {student_name} ({roll_no}) at {now}")
    except Exception as e:
        print(f"[DATABASE ERROR]: {e}")

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/records")
def view_records():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, student_name, roll_no, score, grade, created_at, transcript FROM viva_evaluations ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return render_template("records.html", records=rows)

@app.route("/start_viva", methods=["POST"])
def start_viva():
    try:
        student_name = request.form.get("student_name", "Student")
        roll_no = request.form.get("roll_no", "001")
        pdf_file = request.files.get("pdf_file")

        extracted_text = ""
        if pdf_file and pdf_file.filename != "":
            try:
                reader = PyPDF2.PdfReader(pdf_file)
                for page in reader.pages:
                    extracted_text += page.extract_text() or ""
            except Exception:
                pass

        if not extracted_text.strip():
            extracted_text = "Machine Learning core concepts, Deep Learning architectures, Optimization, and Evaluation metrics."

        viva_session["pdf_text"] = extracted_text[:2000]
        viva_session["student_name"] = student_name
        viva_session["roll_no"] = roll_no
        viva_session["question_count"] = 1
        viva_session["chat_history"] = []

        fallback_choice = random.choice(Q1_POOL)

        prompt = f"""
        You are a strict, smart AI Viva Examiner. Student Name: {student_name}.
        Syllabus context: {viva_session['pdf_text']}.
        Task: Greet the student briefly in 1 line and ask Question #1 from syllabus.
        Format strictly: Roman Urdu + English question ||| Urdu script question
        """

        raw_reply = ask_gemini_quick(prompt, fallback_choice)
        display_text, voice_text = raw_reply.split("|||", 1) if "|||" in raw_reply else (raw_reply, raw_reply)

        viva_session["chat_history"].append(f"Examiner (Q1): {display_text.strip()}")
        audio_b64 = text_to_audio_base64(voice_text.strip())

        return jsonify({
            "status": "success",
            "display_text": display_text.strip(),
            "audio": audio_b64,
            "q_num": 1,
            "is_finished": False
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "display_text": str(e), "audio": "", "q_num": 1, "is_finished": False}), 200

@app.route("/submit_answer", methods=["POST"])
def submit_answer():
    try:
        data = request.json or {}
        student_answer = data.get("answer", "").strip()
        viva_session["chat_history"].append(f"Student Answer: {student_answer}")

        current_q = viva_session["question_count"]

        # QUESTION 2
        if current_q == 1:
            viva_session["question_count"] = 2
            fallback_choice = random.choice(Q2_POOL)

            prompt = f"""
            AI Examiner. Student just answered: "{student_answer}".
            Syllabus: {viva_session['pdf_text']}
            Task: Give 1-line sharp feedback. If they gave no real answer or made excuses, call it out directly. Ask Question #2.
            Format strictly: Roman Urdu + English question ||| Urdu script question
            """

            raw_reply = ask_gemini_quick(prompt, fallback_choice)
            display_text, voice_text = raw_reply.split("|||", 1) if "|||" in raw_reply else (raw_reply, raw_reply)
            viva_session["chat_history"].append(f"Examiner (Q2): {display_text.strip()}")
            audio_b64 = text_to_audio_base64(voice_text.strip())

            return jsonify({"status": "success", "display_text": display_text.strip(), "audio": audio_b64, "q_num": 2, "is_finished": False})

        # QUESTION 3
        elif current_q == 2:
            viva_session["question_count"] = 3
            fallback_choice = random.choice(Q3_POOL)

            prompt = f"""
            AI Examiner. Student just answered: "{student_answer}".
            Syllabus: {viva_session['pdf_text']}
            Task: Give 1-line feedback and ask Question #3 (Final Question).
            Format strictly: Roman Urdu + English question ||| Urdu script question
            """

            raw_reply = ask_gemini_quick(prompt, fallback_choice)
            display_text, voice_text = raw_reply.split("|||", 1) if "|||" in raw_reply else (raw_reply, raw_reply)
            viva_session["chat_history"].append(f"Examiner (Q3): {display_text.strip()}")
            audio_b64 = text_to_audio_base64(voice_text.strip())

            return jsonify({"status": "success", "display_text": display_text.strip(), "audio": audio_b64, "q_num": 3, "is_finished": False})

        # STRICT SEMANTIC EVALUATION ENGINE
        else:
            name = viva_session['student_name']
            roll = viva_session['roll_no']
            full_transcript = "\n".join(viva_session["chat_history"])

            all_answers = [
                entry.replace("Student Answer:", "").strip()
                for entry in viva_session["chat_history"]
                if entry.startswith("Student Answer:")
            ]

            valid_answers = [ans for ans in all_answers if is_meaningful_answer(ans)]
            attempted_count = len(valid_answers)

            # SCENARIO 1: AGAR KOI BHI ASLI TECHNICAL JAWAB NAHI DIYA (TUKKE, BLUFF YA BEGGING THI)
            if attempted_count == 0:
                calc_score = "0.0"
                calc_grade = "Fail (F Grade)"
                calc_summary = "Student ne kisi bhi sawal ka theek technical jawab nahi diya. Sirf excuses aur irrelevant baatein ki gayin."

            # SCENARIO 2: SIRF 1 VALID JAWAB
            elif attempted_count == 1:
                calc_score = "2.5"
                calc_grade = "Fail (F Grade)"
                calc_summary = "Sirf 1 sawal par koshish ki gayi. Baqi 2 sawalat par koi technical concept provide nahi kiya gaya."

            # SCENARIO 3: MULTIPLE ATTEMPTS (STRICT LLM EVALUATION)
            else:
                eval_prompt = f"""
                You are an uncompromising, strict university professor grading an oral viva exam.
                Student Name: {name}
                Full Transcript:
                {full_transcript}

                Strict Grading Rules:
                - If answers are empty fillers (like 'ahem role hota hai'), begging for marks, or technically incorrect, award ZERO marks.
                - Only award marks above 5.0 if the student explained real definitions, equations, or mechanisms.
                - If all answers are vague or wrong, give score 0.0 or maximum 2.0 (Fail).

                Format strictly:
                SCORE: <float number between 0.0 and 10.0>
                GRADE: <Fail (F Grade) / Pass (C Grade) / Good (B Grade) / Pass with Distinction (A Grade)>
                SUMMARY: <2 lines feedback in Roman Urdu>
                """

                default_tuple = ("SCORE: 2.0\nGRADE: Fail (F Grade)\nSUMMARY: Jawabat me technical depth bilkul nahi thi aur concepts na-mukammal thay.", "")
                eval_res = ask_gemini_quick(eval_prompt, default_tuple)

                score_match = re.search(r"SCORE:\s*([\d\.]+)", eval_res)
                grade_match = re.search(r"GRADE:\s*(.+)", eval_res)
                summary_match = re.search(r"SUMMARY:\s*(.+)", eval_res, re.DOTALL)

                calc_score = score_match.group(1).strip() if score_match else "2.0"
                calc_grade = grade_match.group(1).strip() if grade_match else "Fail (F Grade)"
                calc_summary = summary_match.group(1).strip() if summary_match else "Concepts par mazeed mehnat ki shadeed zaroorat hai."

            final_score_str = f"{calc_score} / 10"

            save_record_to_db(name, roll, final_score_str, calc_grade, full_transcript)

            report = f"""📊 FINAL VIVA EVALUATION REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Student Name: {name}
• Roll Number: {roll}
• Meaningful Answers: {attempted_count} of 3
• Total Viva Score: {final_score_str}
• Examiner Verdict: {calc_grade}
• Performance Feedback: {calc_summary}
• Database Status: Record saved permanently in SQLite!
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
|||
آپ کا رزلٹ تیار ہے اور ڈیٹا بیس میں محفوظ کر لیا گیا ہے۔"""

            audio_b64 = text_to_audio_base64("آپ کا رزلٹ تیار ہے اور ڈیٹا بیس میں محفوظ کر لیا گیا ہے۔")

            return jsonify({
                "status": "success",
                "display_text": report.split("|||")[0].strip(),
                "audio": audio_b64,
                "q_num": 3,
                "is_finished": True
            })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "display_text": str(e), "audio": "", "is_finished": True}), 200

if __name__ == "__main__":
    app.run(debug=True)