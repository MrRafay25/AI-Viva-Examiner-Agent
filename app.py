import os
import io
import re
import csv
import uuid
import base64
import sqlite3
import random
import traceback
import requests
from datetime import datetime
from flask import Flask, render_template, request, jsonify, Response, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
import PyPDF2
from gtts import gTTS

app = Flask(__name__)
app.secret_key = "bsai_super_secret_viva_platform_key_2026"

# ==========================================
# CONFIGURATION & MULTI-USER SAAS DATABASE
# ==========================================
GEMINI_API_KEY = "AQ.Ab8RN6KKbOrVCLOyn9Vr1t22zH2ONSWX7P91FkYxj6CRNPC5XA"
DB_NAME = "viva_records.db"

# Server-Side In-Memory Session Storage (Bypasses Cookie 4KB Limit)
active_sessions = {}

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # 1. Student Viva Evaluations Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS viva_evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_name TEXT NOT NULL,
            roll_no TEXT NOT NULL,
            score TEXT,
            grade TEXT,
            transcript TEXT,
            created_at TEXT,
            room_code TEXT DEFAULT 'GLOBAL',
            student_photo TEXT DEFAULT ''
        )
    """)
    for col_def in ["room_code TEXT DEFAULT 'GLOBAL'", "student_photo TEXT DEFAULT ''"]:
        col_name = col_def.split()[0]
        try:
            cursor.execute(f"ALTER TABLE viva_evaluations ADD COLUMN {col_def}")
        except Exception:
            pass

    # 2. Teacher Accounts Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS teachers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT
        )
    """)

    # 3. Exam Rooms Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS exam_rooms (
            room_code TEXT PRIMARY KEY,
            teacher_id INTEGER,
            topic_name TEXT,
            pdf_text TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT,
            FOREIGN KEY(teacher_id) REFERENCES teachers(id)
        )
    """)

    conn.commit()
    conn.close()
    print("[DATABASE] SaaS Database initialized successfully.")

init_db()

# Resilient Fallback Question Pools
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

def save_record_to_db(student_name, roll_no, score, grade, transcript, room_code="GLOBAL", student_photo=""):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            INSERT INTO viva_evaluations (student_name, roll_no, score, grade, transcript, created_at, room_code, student_photo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (student_name, roll_no, score, grade, transcript, now, room_code, student_photo))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DATABASE ERROR]: {e}")

# ==========================================
# TEACHER AUTHENTICATION & SAAS ROUTES
# ==========================================

@app.route("/teacher/portal")
def teacher_portal():
    if "teacher_id" not in session:
        return render_template("teacher_portal.html")
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.room_code, r.topic_name, r.created_at, r.is_active, COUNT(v.id) 
        FROM exam_rooms r 
        LEFT JOIN viva_evaluations v ON r.room_code = v.room_code 
        WHERE r.teacher_id = ? 
        GROUP BY r.room_code 
        ORDER BY r.created_at DESC
    """, (session["teacher_id"],))
    rooms = cursor.fetchall()
    conn.close()
    return render_template("teacher_portal.html", rooms=rooms)

@app.route("/teacher/register", methods=["POST"])
def teacher_register():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "").strip()
    
    if not name or not email or not password:
        return render_template("teacher_portal.html", error="Please fill all registration fields.")
        
    pwd_hash = generate_password_hash(password)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO teachers (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)", (name, email, pwd_hash, now))
        conn.commit()
        teacher_id = cursor.lastrowid
        conn.close()
        
        session["teacher_id"] = teacher_id
        session["teacher_name"] = name
        return redirect(url_for("teacher_portal"))
    except sqlite3.IntegrityError:
        return render_template("teacher_portal.html", error="This email address is already registered. Please login.")

@app.route("/teacher/login", methods=["POST"])
def teacher_login():
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "").strip()
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, password_hash FROM teachers WHERE email = ?", (email,))
    teacher = cursor.fetchone()
    conn.close()
    
    if teacher and check_password_hash(teacher[2], password):
        session["teacher_id"] = teacher[0]
        session["teacher_name"] = teacher[1]
        return redirect(url_for("teacher_portal"))
    
    return render_template("teacher_portal.html", error="Invalid email address or password.")

@app.route("/teacher/logout")
def teacher_logout():
    session.clear()
    return redirect(url_for("teacher_portal"))

@app.route("/teacher/create_room", methods=["POST"])
def create_room():
    if "teacher_id" not in session:
        return redirect(url_for("teacher_portal"))
        
    topic_name = request.form.get("topic_name", "Oral Viva Exam").strip()
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
        
    room_code = str(random.randint(100000, 999999))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO exam_rooms (room_code, teacher_id, topic_name, pdf_text, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (room_code, session["teacher_id"], topic_name, extracted_text[:4000], now))
    conn.commit()
    conn.close()
    
    return redirect(url_for("teacher_portal"))

@app.route("/teacher/toggle_room/<room_code>")
def toggle_room(room_code):
    if "teacher_id" not in session:
        return redirect(url_for("teacher_portal"))
        
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT is_active FROM exam_rooms WHERE room_code = ? AND teacher_id = ?", (room_code, session["teacher_id"]))
    row = cursor.fetchone()
    if row:
        new_status = 0 if row[0] == 1 else 1
        cursor.execute("UPDATE exam_rooms SET is_active = ? WHERE room_code = ?", (new_status, room_code))
        conn.commit()
    conn.close()
    return redirect(url_for("teacher_portal"))

# ==========================================
# STUDENT VIVA ROOM & PROCTORING ROUTES
# ==========================================

@app.route("/")
def index():
    return render_template("index.html", room_code="GLOBAL", topic_name="General AI Evaluation")

@app.route("/exam/<room_code>")
def student_room(room_code):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT topic_name, is_active FROM exam_rooms WHERE room_code = ?", (room_code,))
    room = cursor.fetchone()
    conn.close()
    
    if not room:
        return "<h2 style='color:#ef4444; text-align:center; margin-top:50px;'>Invalid Room Code. Please contact your instructor.</h2>", 404
    if room[1] == 0:
        return "<h2 style='color:#ef4444; text-align:center; margin-top:50px;'>🔒 This Exam Room has been locked by the instructor. Submissions are closed.</h2>", 403
        
    return render_template("index.html", room_code=room_code, topic_name=room[0])

@app.route("/start_viva", methods=["POST"])
def start_viva():
    try:
        student_name = request.form.get("student_name", "Student").strip()
        roll_no = request.form.get("roll_no", "001").strip().upper()
        room_code = request.form.get("room_code", "GLOBAL").strip()
        student_photo = request.form.get("student_photo", "")
        pdf_file = request.files.get("pdf_file")

        # 1. Enforce One-Attempt Restriction per Roll Number
        if room_code != "GLOBAL":
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM viva_evaluations WHERE UPPER(roll_no) = ? AND room_code = ?", (roll_no, room_code))
            already_done = cursor.fetchone()
            conn.close()
            if already_done:
                return jsonify({
                    "status": "error",
                    "display_text": f"Access Denied: Roll Number '{roll_no}' has already submitted the viva for this exam room. Multiple attempts are strictly prohibited."
                }), 200

        extracted_text = ""
        if room_code != "GLOBAL":
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute("SELECT pdf_text, is_active FROM exam_rooms WHERE room_code = ?", (room_code,))
            res = cursor.fetchone()
            conn.close()
            if res and res[1] == 0:
                return jsonify({"status": "error", "display_text": "Exam room is currently locked by the instructor.", "audio": "", "q_num": 1, "is_finished": True})
            if res and res[0]:
                extracted_text = res[0]

        if not extracted_text and pdf_file and pdf_file.filename != "":
            try:
                reader = PyPDF2.PdfReader(pdf_file)
                for page in reader.pages:
                    extracted_text += page.extract_text() or ""
            except Exception:
                pass

        if not extracted_text.strip():
            extracted_text = "Machine Learning core concepts, Optimization, and Evaluation metrics."

        # Unique Viva Session Token (Server-Side Memory)
        viva_id = str(uuid.uuid4())
        session["viva_id"] = viva_id

        active_sessions[viva_id] = {
            "pdf_text": extracted_text[:2000],
            "student_name": student_name,
            "roll_no": roll_no,
            "room_code": room_code,
            "student_photo": student_photo,
            "question_count": 1,
            "chat_history": []
        }

        fallback_choice = random.choice(Q1_POOL)
        prompt = f"""
        You are a strict, smart AI Viva Examiner. Student Name: {student_name}.
        Syllabus context: {extracted_text[:2000]}.
        Task: Greet the student briefly in 1 line and ask Question #1 from syllabus.
        Format strictly: Roman Urdu + English question ||| Urdu script question
        """

        raw_reply = ask_gemini_quick(prompt, fallback_choice)
        display_text, voice_text = raw_reply.split("|||", 1) if "|||" in raw_reply else (raw_reply, raw_reply)

        active_sessions[viva_id]["chat_history"].append(f"Examiner (Q1): {display_text.strip()}")
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
        viva_id = session.get("viva_id")
        if not viva_id or viva_id not in active_sessions:
            return jsonify({"status": "error", "display_text": "Session expired. Please restart the exam.", "audio": "", "is_finished": True})

        state = active_sessions[viva_id]
        data = request.json or {}
        student_answer = data.get("answer", "").strip()
        state["chat_history"].append(f"Student Answer: {student_answer}")

        current_q = state["question_count"]

        # QUESTION 2
        if current_q == 1:
            state["question_count"] = 2
            fallback_choice = random.choice(Q2_POOL)

            prompt = f"""
            AI Examiner. Student just answered: "{student_answer}".
            Syllabus: {state['pdf_text']}
            Task: Give 1-line sharp feedback. If they gave no real answer or made excuses, call it out directly. Ask Question #2.
            Format strictly: Roman Urdu + English question ||| Urdu script question
            """

            raw_reply = ask_gemini_quick(prompt, fallback_choice)
            display_text, voice_text = raw_reply.split("|||", 1) if "|||" in raw_reply else (raw_reply, raw_reply)
            state["chat_history"].append(f"Examiner (Q2): {display_text.strip()}")
            audio_b64 = text_to_audio_base64(voice_text.strip())

            return jsonify({"status": "success", "display_text": display_text.strip(), "audio": audio_b64, "q_num": 2, "is_finished": False})

        # QUESTION 3
        elif current_q == 2:
            state["question_count"] = 3
            fallback_choice = random.choice(Q3_POOL)

            prompt = f"""
            AI Examiner. Student just answered: "{student_answer}".
            Syllabus: {state['pdf_text']}
            Task: Give 1-line feedback and ask Question #3 (Final Question).
            Format strictly: Roman Urdu + English question ||| Urdu script question
            """

            raw_reply = ask_gemini_quick(prompt, fallback_choice)
            display_text, voice_text = raw_reply.split("|||", 1) if "|||" in raw_reply else (raw_reply, raw_reply)
            state["chat_history"].append(f"Examiner (Q3): {display_text.strip()}")
            audio_b64 = text_to_audio_base64(voice_text.strip())

            return jsonify({"status": "success", "display_text": display_text.strip(), "audio": audio_b64, "q_num": 3, "is_finished": False})

        # EVALUATION & PERSISTENCE
        else:
            name = state['student_name']
            roll = state['roll_no']
            room = state.get('room_code', 'GLOBAL')
            photo = state.get('student_photo', '')
            full_transcript = "\n".join(state["chat_history"])

            all_answers = [
                entry.replace("Student Answer:", "").strip()
                for entry in state["chat_history"]
                if entry.startswith("Student Answer:")
            ]

            valid_answers = [ans for ans in all_answers if is_meaningful_answer(ans)]
            attempted_count = len(valid_answers)

            if attempted_count == 0:
                calc_score = "0.0"
                calc_grade = "Fail (F Grade)"
                calc_summary = "Student ne kisi bhi sawal ka theek technical jawab nahi diya. Sirf excuses aur irrelevant baatein ki gayin."
            elif attempted_count == 1:
                calc_score = "2.5"
                calc_grade = "Fail (F Grade)"
                calc_summary = "Sirf 1 sawal par koshish ki gayi. Baqi 2 sawalat par koi technical depth nahi thi."
            else:
                eval_prompt = f"""
                You are an uncompromising, strict university professor grading an oral viva exam.
                Student Name: {name}
                Transcript: {full_transcript}
                Format strictly:
                SCORE: <float number between 0.0 and 10.0>
                GRADE: <Fail (F Grade) / Pass (C Grade) / Good (B Grade) / Pass with Distinction (A Grade)>
                SUMMARY: <2 lines feedback in Roman Urdu>
                """
                default_tuple = ("SCORE: 2.0\nGRADE: Fail (F Grade)\nSUMMARY: Jawabat me technical depth bilkul nahi thi.", "")
                eval_res = ask_gemini_quick(eval_prompt, default_tuple)

                score_match = re.search(r"SCORE:\s*([\d\.]+)", eval_res)
                grade_match = re.search(r"GRADE:\s*(.+)", eval_res)
                summary_match = re.search(r"SUMMARY:\s*(.+)", eval_res, re.DOTALL)

                calc_score = score_match.group(1).strip() if score_match else "2.0"
                calc_grade = grade_match.group(1).strip() if grade_match else "Fail (F Grade)"
                calc_summary = summary_match.group(1).strip() if summary_match else "Concepts par mehnat ki zaroorat hai."

            final_score_str = f"{calc_score} / 10"
            save_record_to_db(name, roll, final_score_str, calc_grade, full_transcript, room, photo)

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
            
            # Clean up server-side memory
            active_sessions.pop(viva_id, None)
            session.pop("viva_id", None)

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

# ==========================================
# EXAMINER RECORDS & EXPORT ROUTES
# ==========================================

@app.route("/records")
def view_records():
    room_filter = request.args.get("room")
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    if room_filter:
        cursor.execute("SELECT id, student_name, roll_no, score, grade, created_at, transcript, room_code, student_photo FROM viva_evaluations WHERE room_code = ? ORDER BY id DESC", (room_filter,))
    else:
        cursor.execute("SELECT id, student_name, roll_no, score, grade, created_at, transcript, room_code, student_photo FROM viva_evaluations ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return render_template("records.html", records=rows, room_filter=room_filter)

@app.route("/export_csv")
def export_csv():
    room_filter = request.args.get("room")
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    if room_filter:
        cursor.execute("SELECT id, student_name, roll_no, score, grade, created_at, transcript, room_code FROM viva_evaluations WHERE room_code = ? ORDER BY id ASC", (room_filter,))
        filename = f"viva_report_room_{room_filter}.csv"
    else:
        cursor.execute("SELECT id, student_name, roll_no, score, grade, created_at, transcript, room_code FROM viva_evaluations ORDER BY id ASC")
        filename = "viva_evaluations_master_report.csv"
    rows = cursor.fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Evaluation ID", "Student Name", "Roll Number", "Viva Score", "Grade / Verdict", "Timestamp", "Full Q&A Transcript", "Room PIN"])
    for row in rows:
        clean_row = list(row)
        clean_row[6] = clean_row[6].replace("\n", " | ")
        writer.writerow(clean_row)

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)