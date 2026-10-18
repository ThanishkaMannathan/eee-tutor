"""
app.py — Flask Web Server for EEE Tutor Web App
================================================
Run with:  python app.py
Then open: http://localhost:5000 on your phone (on the same WiFi)
Or:        http://your-computer-ip:5000

This file creates a REST API that the web app's JavaScript calls.
"""

import os
import sys
import io
import json
import logging
from datetime import datetime

# Fix Windows console cp1252 encoding for emojis
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

from flask import Flask, render_template, request, jsonify, session
from flask_cors import CORS
from dotenv import load_dotenv

# Add the parent folder so we can import our modules
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import memory
import tutor
import knowledge

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

# ── Directory & Logging Setup ─────────────────────
LOGS_DIR = os.path.join(os.path.dirname(__file__), '..', 'logs')
DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

log_handlers = [logging.StreamHandler(sys.stdout)]
try:
    log_handlers.append(logging.FileHandler(os.path.join(LOGS_DIR, 'webapp.log'), encoding='utf-8'))
except Exception:
    pass

logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s | %(levelname)s | %(message)s",
    handlers= log_handlers
)
logger = logging.getLogger(__name__)

# ── Flask App ─────────────────────────────────────
app = Flask(__name__, template_folder='templates', static_folder='static')
app.secret_key = os.urandom(24)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
CORS(app)

STUDENT_LEVEL = os.getenv("STUDENT_LEVEL", "beginner")
SYLLABUS_PATH = os.path.join(os.path.dirname(__file__), '..', 'syllabus.json')


# ═════════════════════════════════════════════════
#  STARTUP
# ═════════════════════════════════════════════════

@app.before_request
def startup():
    """Initialize DB and syllabus on first request."""
    if not hasattr(app, '_initialized'):
        os.makedirs(os.path.join(os.path.dirname(__file__), '..', 'logs'), exist_ok=True)
        memory.init_db()
        if os.path.exists(SYLLABUS_PATH):
            memory.load_syllabus_into_db(SYLLABUS_PATH)
        knowledge.index_knowledge_folder()
        app._initialized = True


# ═════════════════════════════════════════════════
#  PAGE ROUTES
# ═════════════════════════════════════════════════

@app.route('/')
def index():
    return render_template('index.html')


# ═════════════════════════════════════════════════
#  API: DASHBOARD
# ═════════════════════════════════════════════════

@app.route('/api/dashboard')
def api_dashboard():
    """Return all data needed for the home screen."""
    try:
        progress    = memory.get_weekly_progress()
        current_topic   = memory.get_setting("current_topic", "")
        current_subject = memory.get_setting("current_subject", "")
        quiz_done       = memory.get_setting("quiz_done_today", "false")
        next_topic      = memory.get_next_topic()

        hour = datetime.now().hour
        if hour < 12:   greeting = "Good Morning"
        elif hour < 17: greeting = "Good Afternoon"
        else:           greeting = "Good Evening"

        return jsonify({
            "greeting"        : greeting,
            "current_topic"   : current_topic,
            "current_subject" : current_subject,
            "quiz_done_today" : quiz_done == "true",
            "next_topic"      : next_topic["topic"] if next_topic else "All done!",
            "next_subject"    : next_topic["subject"] if next_topic else "",
            "total_taught"    : progress["total_taught"],
            "total_topics"    : progress["total_topics"],
            "completion_pct"  : progress["completion_pct"],
            "avg_score"       : progress["avg_score_this_week"],
            "lessons_this_week": progress["lessons_this_week"],
            "weak_topics"     : [t["topic"] for t in progress["weak_topics"][:3]],
        })
    except Exception as e:
        logger.error("Dashboard error: %s", e)
        return jsonify({"error": str(e)}), 500


# ═════════════════════════════════════════════════
#  API: LESSON
# ═════════════════════════════════════════════════

@app.route('/api/lesson', methods=['POST'])
def api_lesson():
    """Generate and return today's lesson."""
    try:
        topic_data = memory.get_next_topic()
        if not topic_data:
            return jsonify({"error": "All topics completed! Add more to syllabus.json"}), 404

        topic    = topic_data["topic"]
        subject  = topic_data["subject"]
        topic_id = topic_data["id"]

        context_text = knowledge.retrieve_context(f"{subject}: {topic}")
        lesson = tutor.generate_lesson(
            topic=topic, subject=subject,
            student_level=STUDENT_LEVEL, context=context_text
        )

        memory.mark_topic_taught(topic_id)
        memory.save_setting("current_topic",    topic)
        memory.save_setting("current_subject",  subject)
        memory.save_setting("current_topic_id", str(topic_id))
        memory.save_setting("lesson_sent_today", datetime.now().isoformat())
        memory.save_setting("quiz_done_today",  "false")

        return jsonify({
            "topic"   : topic,
            "subject" : subject,
            "lesson"  : lesson
        })
    except Exception as e:
        logger.error("Lesson error: %s", e)
        return jsonify({"error": str(e)}), 500


# ═════════════════════════════════════════════════
#  API: QUIZ
# ═════════════════════════════════════════════════

@app.route('/api/quiz/start', methods=['POST'])
def api_quiz_start():
    """Generate 20 quiz questions for the current topic."""
    try:
        topic   = memory.get_setting("current_topic", "")
        subject = memory.get_setting("current_subject", "")

        if not topic:
            return jsonify({"error": "Please get today's lesson first!"}), 400

        progress   = memory.get_weekly_progress()
        weak_areas = [t["topic"] for t in progress.get("weak_topics", [])[:3]]

        questions = tutor.generate_quiz(
            topic=topic, subject=subject,
            weak_areas=weak_areas, student_level=STUDENT_LEVEL
        )

        # Store in server-side session
        session['quiz_questions'] = questions
        session['quiz_topic']     = topic
        session['quiz_subject']   = subject
        session['quiz_index']     = 0
        session['quiz_score']     = 0
        session['quiz_log']       = []

        return jsonify({
            "topic"     : topic,
            "subject"   : subject,
            "total"     : len(questions),
            "questions" : questions   # Send all at once for smooth UX
        })
    except Exception as e:
        logger.error("Quiz start error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route('/api/quiz/grade', methods=['POST'])
def api_quiz_grade():
    """Grade a single answer and return feedback."""
    try:
        data        = request.get_json()
        question    = data.get("question")
        user_answer = data.get("answer", "")

        result = tutor.grade_answer(question, user_answer, STUDENT_LEVEL)
        return jsonify(result)
    except Exception as e:
        logger.error("Grade error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route('/api/quiz/submit', methods=['POST'])
def api_quiz_submit():
    """Save completed quiz results to the database."""
    try:
        data       = request.get_json()
        topic      = data.get("topic")
        subject    = data.get("subject")
        score      = data.get("score", 0)
        total      = data.get("total", 20)
        weak_areas = data.get("weak_areas", [])
        quiz_log   = data.get("quiz_log", [])

        session_id = memory.save_quiz_session(
            topic=topic, subject=subject,
            score=score, total=total,
            weak_areas=weak_areas, questions_log=quiz_log
        )
        memory.save_setting("quiz_done_today", "true")
        percentage = round((score / total) * 100, 1) if total else 0

        return jsonify({
            "session_id" : session_id,
            "score"      : score,
            "total"      : total,
            "percentage" : percentage
        })
    except Exception as e:
        logger.error("Quiz submit error: %s", e)
        return jsonify({"error": str(e)}), 500


# ═════════════════════════════════════════════════
#  API: DOUBT SOLVER
# ═════════════════════════════════════════════════

@app.route('/api/ask', methods=['POST'])
def api_ask():
    """Answer any EEE doubt question."""
    try:
        data     = request.get_json()
        question = data.get("question", "").strip()

        if not question:
            return jsonify({"error": "Please type a question!"}), 400

        context_text = knowledge.retrieve_context(question)
        answer = tutor.answer_doubt(question, STUDENT_LEVEL, context_text)

        return jsonify({"answer": answer})
    except Exception as e:
        logger.error("Ask error: %s", e)
        return jsonify({"error": str(e)}), 500


# ═════════════════════════════════════════════════
#  API: PROGRESS
# ═════════════════════════════════════════════════

@app.route('/api/progress')
def api_progress():
    """Return full progress stats."""
    try:
        weekly  = memory.get_weekly_progress()
        alltime = memory.get_all_time_stats()
        kb      = knowledge.get_knowledge_stats()

        return jsonify({
            "weekly"  : weekly,
            "alltime" : alltime,
            "kb"      : kb
        })
    except Exception as e:
        logger.error("Progress error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route('/api/progress/report', methods=['POST'])
def api_progress_report():
    """Generate AI weekly summary."""
    try:
        progress = memory.get_weekly_progress()
        summary  = tutor.generate_weekly_summary(progress, STUDENT_LEVEL)
        return jsonify({"summary": summary})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ═════════════════════════════════════════════════
#  API: SYLLABUS
# ═════════════════════════════════════════════════

@app.route('/api/syllabus')
def api_syllabus():
    """Return the full syllabus with completion status."""
    try:
        with open(SYLLABUS_PATH) as f:
            syllabus = json.load(f)

        import sqlite3
        conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), '..', 'data', 'tutor.db'))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        for subj in syllabus["subjects"]:
            enriched = []
            for topic in subj["topics"]:
                cursor.execute(
                    "SELECT times_taught, weak_score, last_taught FROM topics WHERE topic=? AND subject=?",
                    (topic, subj["name"])
                )
                row = cursor.fetchone()
                enriched.append({
                    "topic"       : topic,
                    "taught"      : bool(row and row["times_taught"] > 0),
                    "weak_score"  : round((row["weak_score"] if row else 0) * 100),
                    "last_taught" : row["last_taught"] if row else None
                })
            subj["topics"] = enriched
        conn.close()

        return jsonify(syllabus)
    except Exception as e:
        logger.error("Syllabus error: %s", e)
        return jsonify({"error": str(e)}), 500


# ═════════════════════════════════════════════════
#  RUN
# ═════════════════════════════════════════════════

if __name__ == '__main__':
    # host='0.0.0.0' allows phones on the same WiFi to connect
    print("\n=== [EEE Tutor Web App Starting] ===")
    print("Local access:  http://localhost:5000")
    try:
        import socket
        ip = socket.gethostbyname(socket.gethostname())
        print(f"Phone/LAN:     http://{ip}:5000\n")
    except Exception:
        pass
    app.run(host='0.0.0.0', port=5000, debug=False)
