"""
memory.py — Database & Spaced Repetition Engine
================================================
This file handles ALL data storage for the EEE Tutor:
  - Storing every topic from the syllabus
  - Tracking quiz scores and weak areas
  - Deciding WHICH topic to teach next (spaced repetition)
  - Saving user settings (like preferred study time)

Database: SQLite (built into Python — no installation needed)
"""

import sqlite3          # Built-in Python module for the database
import json             # For storing lists as text in the database
import logging          # For writing log messages
import os               # For file path operations
from datetime import date, timedelta, datetime

# Set up logging so we can see what's happening
logger = logging.getLogger(__name__)

# Path to the SQLite database file
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "tutor.db")


# ─────────────────────────────────────────────
#  DATABASE SETUP
# ─────────────────────────────────────────────

def init_db():
    """
    Create the database and all tables if they don't exist yet.
    This is safe to call every time the app starts.
    """
    # Make sure the data/ folder exists
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # --- Table 1: topics ---
    # Stores every topic from syllabus.json plus progress tracking
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS topics (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            subject      TEXT NOT NULL,       -- e.g. "Circuit Theory"
            short_code   TEXT NOT NULL,       -- e.g. "CT"
            topic        TEXT NOT NULL,       -- e.g. "Ohm's Law and Kirchhoff's Laws"
            order_index  INTEGER NOT NULL,    -- Position in the syllabus (0-based)
            times_taught INTEGER DEFAULT 0,  -- How many times this topic was taught
            last_taught  TEXT,               -- Date string "YYYY-MM-DD"
            next_review  TEXT,               -- When spaced repetition says to review it
            weak_score   REAL DEFAULT 0.0    -- 0.0 = strong, 1.0 = very weak
        )
    """)

    # --- Table 2: quiz_sessions ---
    # Logs every quiz the user takes
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS quiz_sessions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            topic       TEXT NOT NULL,
            subject     TEXT NOT NULL,
            date        TEXT NOT NULL,        -- "YYYY-MM-DD"
            score       INTEGER NOT NULL,     -- Number of correct answers
            total       INTEGER NOT NULL,     -- Total questions asked
            percentage  REAL NOT NULL,        -- score / total * 100
            weak_areas  TEXT DEFAULT '[]'     -- JSON list of sub-topics with mistakes
        )
    """)

    # --- Table 3: question_log ---
    # Logs every individual question for detailed analysis
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS question_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  INTEGER NOT NULL,
            question    TEXT NOT NULL,
            user_answer TEXT,
            correct     INTEGER NOT NULL,     -- 1 = correct, 0 = wrong
            topic       TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES quiz_sessions(id)
        )
    """)

    # --- Table 4: settings ---
    # Stores user preferences as key-value pairs
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()
    logger.info("Database initialized at: %s", DB_PATH)


# ─────────────────────────────────────────────
#  SYLLABUS LOADING
# ─────────────────────────────────────────────

def load_syllabus_into_db(syllabus_path: str):
    """
    Read syllabus.json and insert all topics into the database.
    Topics that are already there will be skipped (no duplicates).
    """
    with open(syllabus_path, "r") as f:
        syllabus = json.load(f)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    total_inserted = 0
    for subject_data in syllabus["subjects"]:
        subject_name = subject_data["name"]
        short_code   = subject_data["short_code"]

        for idx, topic_name in enumerate(subject_data["topics"]):
            # Only insert if this topic doesn't exist yet
            cursor.execute(
                "SELECT id FROM topics WHERE subject = ? AND topic = ?",
                (subject_name, topic_name)
            )
            if cursor.fetchone() is None:
                cursor.execute("""
                    INSERT INTO topics (subject, short_code, topic, order_index)
                    VALUES (?, ?, ?, ?)
                """, (subject_name, short_code, topic_name, idx))
                total_inserted += 1

    conn.commit()
    conn.close()
    logger.info("Loaded %d new topics from syllabus into database.", total_inserted)


# ─────────────────────────────────────────────
#  SPACED REPETITION: PICK NEXT TOPIC
# ─────────────────────────────────────────────

def get_next_topic() -> dict:
    """
    Decide which topic to teach today using spaced repetition logic:

    Priority order:
      1. Topics due for review today (weak topics whose next_review <= today)
      2. The next untaught topic in syllabus order
      3. The weakest topic overall (fallback)

    Returns a dict with topic info, or None if all topics are done.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row   # Makes rows behave like dicts
    cursor = conn.cursor()

    today = date.today().isoformat()

    # --- Priority 1: Due-for-review weak topics ---
    cursor.execute("""
        SELECT * FROM topics
        WHERE next_review <= ? AND times_taught > 0 AND weak_score > 0.3
        ORDER BY weak_score DESC, next_review ASC
        LIMIT 1
    """, (today,))
    row = cursor.fetchone()

    if row:
        topic = dict(row)
        conn.close()
        logger.info("Spaced repetition: reviewing weak topic '%s'", topic["topic"])
        return topic

    # --- Priority 2: Next untaught topic in order ---
    cursor.execute("""
        SELECT * FROM topics
        WHERE times_taught = 0
        ORDER BY
            -- Rotate through subjects so we don't do all of one subject first
            order_index ASC,
            id ASC
        LIMIT 1
    """)
    row = cursor.fetchone()

    if row:
        topic = dict(row)
        conn.close()
        logger.info("New topic: '%s' from '%s'", topic["topic"], topic["subject"])
        return topic

    # --- Priority 3: Weakest topic (all topics have been taught) ---
    cursor.execute("""
        SELECT * FROM topics
        ORDER BY weak_score DESC, last_taught ASC
        LIMIT 1
    """)
    row = cursor.fetchone()

    topic = dict(row) if row else None
    conn.close()

    if topic:
        logger.info("All topics taught. Reviewing weakest: '%s'", topic["topic"])
    return topic


# ─────────────────────────────────────────────
#  TOPIC: MARK AS TAUGHT
# ─────────────────────────────────────────────

def mark_topic_taught(topic_id: int):
    """
    Update the database when a topic has been taught today.
    Sets last_taught = today and increments times_taught.
    """
    today = date.today().isoformat()

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE topics
        SET times_taught = times_taught + 1,
            last_taught  = ?
        WHERE id = ?
    """, (today, topic_id))
    conn.commit()
    conn.close()
    logger.info("Marked topic ID %d as taught on %s", topic_id, today)


# ─────────────────────────────────────────────
#  QUIZ: SAVE RESULTS & UPDATE WEAK SCORE
# ─────────────────────────────────────────────

def save_quiz_session(topic: str, subject: str, score: int, total: int,
                      weak_areas: list, questions_log: list) -> int:
    """
    Save a completed quiz session to the database.
    Also updates the topic's weak_score and next_review date.

    Parameters:
      topic       : Topic name (e.g. "Ohm's Law and Kirchhoff's Laws")
      subject     : Subject name (e.g. "Circuit Theory")
      score       : Number of correct answers
      total       : Total questions asked
      weak_areas  : List of sub-topic strings where mistakes were made
      questions_log: List of dicts with question, user_answer, correct

    Returns: The session ID (integer)
    """
    today = date.today().isoformat()
    percentage = round((score / total) * 100, 1) if total > 0 else 0.0

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Insert the session summary
    cursor.execute("""
        INSERT INTO quiz_sessions (topic, subject, date, score, total, percentage, weak_areas)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (topic, subject, today, score, total, percentage, json.dumps(weak_areas)))
    session_id = cursor.lastrowid

    # Insert individual question logs
    for q in questions_log:
        cursor.execute("""
            INSERT INTO question_log (session_id, question, user_answer, correct, topic)
            VALUES (?, ?, ?, ?, ?)
        """, (session_id, q["question"], q.get("user_answer", ""), int(q["correct"]), topic))

    conn.commit()

    # Update the topic's weak_score and next_review using spaced repetition rules
    _update_topic_after_quiz(cursor, conn, topic, percentage)

    conn.close()
    logger.info("Quiz saved: topic='%s', score=%d/%d (%.1f%%)", topic, score, total, percentage)
    return session_id


def _update_topic_after_quiz(cursor, conn, topic: str, percentage: float):
    """
    Internal helper: update weak_score and next_review based on quiz performance.

    Spaced repetition intervals:
      Score < 60%  → review in 1 day  (weak, needs urgent attention)
      Score 60-80% → review in 3 days (moderate)
      Score > 80%  → review in 7 days (strong, longer break)
    """
    today = date.today()

    if percentage < 60:
        weak_score   = 0.8          # Very weak
        review_days  = 1
    elif percentage < 80:
        weak_score   = 0.4          # Moderate
        review_days  = 3
    else:
        weak_score   = 0.1          # Strong
        review_days  = 7

    next_review = (today + timedelta(days=review_days)).isoformat()

    cursor.execute("""
        UPDATE topics
        SET weak_score  = ?,
            next_review = ?
        WHERE topic = ?
    """, (weak_score, next_review, topic))
    conn.commit()


# ─────────────────────────────────────────────
#  PROGRESS REPORTS
# ─────────────────────────────────────────────

def get_weekly_progress() -> dict:
    """
    Generate a weekly progress summary containing:
      - Number of lessons this week
      - Average quiz score this week
      - Topics covered this week
      - Top 3 weakest topics overall
      - Study streak (consecutive days with a quiz)
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Calculate the date 7 days ago
    week_ago = (date.today() - timedelta(days=7)).isoformat()

    # Sessions this week
    cursor.execute("""
        SELECT topic, subject, score, total, percentage, date
        FROM quiz_sessions
        WHERE date >= ?
        ORDER BY date DESC
    """, (week_ago,))
    sessions = [dict(row) for row in cursor.fetchall()]

    # Overall weakest topics
    cursor.execute("""
        SELECT subject, topic, weak_score, times_taught
        FROM topics
        WHERE times_taught > 0
        ORDER BY weak_score DESC
        LIMIT 5
    """)
    weak_topics = [dict(row) for row in cursor.fetchall()]

    # Topics taught this week
    cursor.execute("""
        SELECT DISTINCT subject, topic, last_taught
        FROM topics
        WHERE last_taught >= ?
        ORDER BY last_taught DESC
    """, (week_ago,))
    topics_this_week = [dict(row) for row in cursor.fetchall()]

    # Total topics taught so far
    cursor.execute("SELECT COUNT(*) as cnt FROM topics WHERE times_taught > 0")
    total_taught = cursor.fetchone()["cnt"]

    cursor.execute("SELECT COUNT(*) as cnt FROM topics")
    total_topics = cursor.fetchone()["cnt"]

    conn.close()

    # Calculate averages
    avg_score = 0.0
    if sessions:
        avg_score = round(sum(s["percentage"] for s in sessions) / len(sessions), 1)

    return {
        "sessions_this_week"  : sessions,
        "lessons_this_week"   : len(sessions),
        "avg_score_this_week" : avg_score,
        "topics_this_week"    : topics_this_week,
        "weak_topics"         : weak_topics,
        "total_taught"        : total_taught,
        "total_topics"        : total_topics,
        "completion_pct"      : round((total_taught / total_topics) * 100, 1) if total_topics else 0,
    }


def get_all_time_stats() -> dict:
    """Return lifetime statistics for the /report command."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) as cnt, AVG(percentage) as avg FROM quiz_sessions")
    row = cursor.fetchone()
    total_quizzes = row["cnt"]
    avg_score     = round(row["avg"] or 0, 1)

    cursor.execute("SELECT COUNT(*) as cnt FROM topics WHERE times_taught > 0")
    topics_taught = cursor.fetchone()["cnt"]

    cursor.execute("""
        SELECT subject, topic, weak_score FROM topics
        WHERE times_taught > 0 ORDER BY weak_score DESC LIMIT 3
    """)
    weakest = [dict(r) for r in cursor.fetchall()]

    cursor.execute("""
        SELECT subject, topic, weak_score FROM topics
        WHERE times_taught > 0 ORDER BY weak_score ASC LIMIT 3
    """)
    strongest = [dict(r) for r in cursor.fetchall()]

    conn.close()
    return {
        "total_quizzes" : total_quizzes,
        "avg_score"     : avg_score,
        "topics_taught" : topics_taught,
        "weakest"       : weakest,
        "strongest"     : strongest,
    }


# ─────────────────────────────────────────────
#  SETTINGS (User Preferences)
# ─────────────────────────────────────────────

def get_setting(key: str, default: str = "") -> str:
    """Get a user setting from the database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else default


def save_setting(key: str, value: str):
    """Save or update a user setting."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO settings (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
    """, (key, value))
    conn.commit()
    conn.close()


def get_all_settings() -> dict:
    """Return all user settings as a dictionary."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM settings")
    rows = cursor.fetchall()
    conn.close()
    return {row[0]: row[1] for row in rows}
