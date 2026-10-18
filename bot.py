"""
bot.py — Telegram Bot (Main Entry Point)
=========================================
This is the main file you run to start the EEE Tutor bot.

Run it with:  python bot.py

What it does:
  - Starts the Telegram bot and listens for your messages
  - Handles all commands: /start, /lesson, /quiz, /ask, /progress, /settings, /report
  - Manages the quiz conversation (asking questions one by one)
  - Connects everything: tutor, memory, knowledge, scheduler

Important Telegram concepts:
  - "Handler" = a function that runs when you send a specific command or message
  - "ConversationHandler" = manages multi-step dialogs (like a quiz with 20 questions)
  - "Context" = stores temporary data about the current user's session
"""

import os
import logging
import asyncio
from datetime import datetime
from typing import Optional

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from dotenv import load_dotenv

# Our custom modules
import memory
import tutor
import knowledge
import scheduler as sched

# Load .env file
load_dotenv()

# ─────────────────────────────────────────────
#  LOGGING SETUP
# ─────────────────────────────────────────────

# Create logs/ directory if it doesn't exist
os.makedirs("logs", exist_ok=True)

# Configure logging to write to both file and console
logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt = "%Y-%m-%d %H:%M:%S",
    handlers = [
        logging.FileHandler("logs/tutor.log", encoding="utf-8"),
        logging.StreamHandler()   # Also print to terminal
    ]
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  CONFIGURATION
# ─────────────────────────────────────────────

TELEGRAM_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID         = os.getenv("YOUR_TELEGRAM_CHAT_ID")
STUDENT_LEVEL   = os.getenv("STUDENT_LEVEL", "beginner")
SYLLABUS_PATH   = os.path.join(os.path.dirname(__file__), "syllabus.json")

# ─────────────────────────────────────────────
#  CONVERSATION STATES (for the quiz flow)
# ─────────────────────────────────────────────

# Each state is just a number. ConversationHandler uses these
# to know which step of the conversation we're on.
QUIZ_ANSWERING  = 1   # User is answering quiz questions
SETTINGS_TIME   = 10  # User is entering new study time


# ─────────────────────────────────────────────
#  SECURITY: Only accept messages from YOU
# ─────────────────────────────────────────────

def _is_authorized(update: Update) -> bool:
    """
    Check if the incoming message is from your Telegram account.
    This prevents others from using your bot (and spending your API credits).
    """
    if not CHAT_ID:
        return True   # If no chat ID configured, allow all (development mode)
    return str(update.effective_chat.id) == str(CHAT_ID)


async def _unauthorized_reply(update: Update):
    """Reply to unauthorized users."""
    await update.message.reply_text(
        "🔒 This is a private bot. Sorry, I only respond to my owner!"
    )


# ─────────────────────────────────────────────
#  HELPER: Split long messages for Telegram
# ─────────────────────────────────────────────

async def send_long_message(update: Update, text: str, parse_mode: str = "Markdown"):
    """
    Telegram limits messages to 4096 characters.
    This helper splits long text and sends it in multiple messages.
    """
    MAX_LEN = 4000
    chunks  = [text[i:i+MAX_LEN] for i in range(0, len(text), MAX_LEN)]

    for chunk in chunks:
        try:
            await update.message.reply_text(chunk, parse_mode=parse_mode)
        except Exception:
            # If Markdown parsing fails, try sending as plain text
            try:
                await update.message.reply_text(chunk)
            except Exception as e:
                logger.error("Failed to send message chunk: %s", str(e))


# ─────────────────────────────────────────────
#  COMMAND: /start
# ─────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /start command — welcome message and first-time setup."""
    if not _is_authorized(update):
        await _unauthorized_reply(update)
        return

    chat_id = update.effective_chat.id
    logger.info("/start from chat_id=%s", chat_id)

    # Save the chat ID if not already set (useful for first run)
    memory.save_setting("chat_id", str(chat_id))

    study_time    = os.getenv("STUDY_TIME", "08:00")
    total_topics  = 140   # 7 subjects × 20 topics

    # Get current progress
    stats        = memory.get_all_time_stats() if memory.get_all_time_stats()["total_quizzes"] > 0 else None
    taught_count = memory.get_weekly_progress()["total_taught"]

    welcome = (
        "🎓 *Welcome to EEE Tutor!*\n\n"
        "I'm your personal Electrical & Electronics Engineering study assistant, "
        "powered by Claude AI.\n\n"
        "📅 *Daily Schedule:*\n"
        f"  • Lesson sent every day at *{study_time}*\n"
        "  • Quiz after each lesson\n"
        "  • Weekly progress report every Sunday\n\n"
        f"📚 *Your Syllabus:* {taught_count}/{total_topics} topics covered\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "*Available Commands:*\n"
        "📖 /lesson — Get today's lesson now\n"
        "📝 /quiz — Take the quiz\n"
        "❓ /ask — Ask any EEE question\n"
        "📊 /progress — See your weekly stats\n"
        "📋 /report — Full all-time report\n"
        "⚙️ /settings — Change preferences\n\n"
        "_Tip: Just type your question anytime — I'll answer it!_ 💬"
    )

    await update.message.reply_text(welcome, parse_mode="Markdown")


# ─────────────────────────────────────────────
#  COMMAND: /lesson
# ─────────────────────────────────────────────

async def cmd_lesson(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /lesson — generate and send today's lesson immediately."""
    if not _is_authorized(update):
        await _unauthorized_reply(update)
        return

    logger.info("/lesson requested")
    await update.message.reply_text("📖 Picking your next topic... ⏳")

    # Get next topic
    topic_data = memory.get_next_topic()
    if not topic_data:
        await update.message.reply_text(
            "🎉 You've covered all topics in your syllabus!\n"
            "Add new topics to syllabus.json to continue."
        )
        return

    topic    = topic_data["topic"]
    subject  = topic_data["subject"]
    topic_id = topic_data["id"]

    await update.message.reply_text(
        f"📚 *Topic:* {topic}\n"
        f"📖 *Subject:* {subject}\n\n"
        f"Generating your lesson... This takes about 10 seconds ⏳",
        parse_mode="Markdown"
    )

    # Retrieve context from knowledge base
    context_text = knowledge.retrieve_context(f"{subject}: {topic}")

    # Generate the lesson
    lesson = tutor.generate_lesson(
        topic         = topic,
        subject       = subject,
        student_level = STUDENT_LEVEL,
        context       = context_text
    )

    # Send the lesson (split if long)
    await send_long_message(update, lesson)

    # Save progress
    memory.mark_topic_taught(topic_id)
    memory.save_setting("current_topic", topic)
    memory.save_setting("current_subject", subject)
    memory.save_setting("current_topic_id", str(topic_id))
    memory.save_setting("lesson_sent_today", datetime.now().isoformat())
    memory.save_setting("quiz_done_today", "false")

    await update.message.reply_text(
        "✅ *Lesson complete!*\n\n"
        "Send /quiz when you're ready to test yourself! 📝\n"
        "Or ask any doubt with /ask",
        parse_mode="Markdown"
    )


# ─────────────────────────────────────────────
#  COMMAND: /quiz  (ConversationHandler)
# ─────────────────────────────────────────────

async def cmd_quiz_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Start the quiz conversation.
    This begins a ConversationHandler that asks questions one at a time.
    """
    if not _is_authorized(update):
        await _unauthorized_reply(update)
        return

    topic   = memory.get_setting("current_topic", "")
    subject = memory.get_setting("current_subject", "")

    if not topic:
        await update.message.reply_text(
            "📚 Please get today's lesson first with /lesson before taking the quiz!"
        )
        return ConversationHandler.END

    logger.info("/quiz started for topic: '%s'", topic)

    await update.message.reply_text(
        f"📝 *Quiz Time!*\n\n"
        f"Topic: *{topic}*\n"
        f"Questions: 20 (15 MCQ + 5 Short Answer)\n\n"
        f"Generating questions... ⏳\n"
        f"_Type /cancel at any time to stop the quiz._",
        parse_mode="Markdown"
    )

    # Get weak areas from recent quiz sessions
    progress = memory.get_weekly_progress()
    weak_areas = [t["topic"] for t in progress.get("weak_topics", [])[:3]]

    # Generate 20 questions
    questions = tutor.generate_quiz(
        topic         = topic,
        subject       = subject,
        weak_areas    = weak_areas,
        student_level = STUDENT_LEVEL
    )

    if not questions:
        await update.message.reply_text("❌ Failed to generate quiz. Please try again.")
        return ConversationHandler.END

    # Store quiz state in context.user_data (temporary memory for this conversation)
    context.user_data["quiz_questions"]   = questions
    context.user_data["quiz_topic"]       = topic
    context.user_data["quiz_subject"]     = subject
    context.user_data["quiz_index"]       = 0          # Current question number
    context.user_data["quiz_score"]       = 0          # Running total of correct answers
    context.user_data["quiz_log"]         = []         # Log of all answers
    context.user_data["quiz_weak_areas"]  = []         # Sub-topics with mistakes

    # Send the first question
    await _send_quiz_question(update, context)
    return QUIZ_ANSWERING


async def _send_quiz_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Helper: format and send the current quiz question."""
    questions = context.user_data["quiz_questions"]
    idx       = context.user_data["quiz_index"]
    total     = len(questions)

    if idx >= total:
        return   # Safety check

    q = questions[idx]

    # Question header
    q_type_label = "Multiple Choice" if q["type"] == "mcq" else "Short Answer"
    header = f"*Question {idx + 1}/{total}* ({q_type_label})\n\n"
    body   = q["question"]

    # For MCQ, show the options with quick-reply buttons effect (plain text)
    options_text = ""
    if q["type"] == "mcq" and "options" in q:
        options_text = "\n\n" + "\n".join(q["options"])
        options_text += "\n\n_Reply with: A, B, C, or D_"
    else:
        options_text = "\n\n_Type your answer below:_"

    try:
        await update.message.reply_text(
            header + body + options_text,
            parse_mode = "Markdown"
        )
    except Exception:
        await update.message.reply_text(header + body + options_text)


async def cmd_quiz_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle each quiz answer as it comes in.
    Grade it, show feedback, then move to the next question (or finish).
    """
    if not _is_authorized(update):
        await _unauthorized_reply(update)
        return QUIZ_ANSWERING

    questions   = context.user_data.get("quiz_questions", [])
    idx         = context.user_data.get("quiz_index", 0)
    user_answer = update.message.text.strip()

    if idx >= len(questions):
        return await _finish_quiz(update, context)

    current_q = questions[idx]

    # Grade the answer
    result = tutor.grade_answer(current_q, user_answer, STUDENT_LEVEL)

    # Update score
    if result["correct"]:
        context.user_data["quiz_score"] += 1
    else:
        # Track weak areas (topic name for wrong answers)
        weak = context.user_data.get("quiz_weak_areas", [])
        weak.append(context.user_data["quiz_topic"])
        context.user_data["quiz_weak_areas"] = weak

    # Log this question
    log = context.user_data.get("quiz_log", [])
    log.append({
        "question"    : current_q["question"],
        "user_answer" : user_answer,
        "correct"     : result["correct"]
    })
    context.user_data["quiz_log"] = log

    # Send feedback
    score_so_far = context.user_data["quiz_score"]
    next_idx     = idx + 1
    context.user_data["quiz_index"] = next_idx

    feedback_msg = (
        result["feedback"] + "\n\n"
        f"_Score so far: {score_so_far}/{next_idx}_"
    )

    try:
        await update.message.reply_text(feedback_msg, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text(result["feedback"])

    # Check if quiz is complete
    if next_idx >= len(questions):
        return await _finish_quiz(update, context)

    # Otherwise send the next question
    await _send_quiz_question(update, context)
    return QUIZ_ANSWERING


async def _finish_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Called when all quiz questions are done.
    Calculate final score, save to database, send summary.
    """
    score       = context.user_data.get("quiz_score", 0)
    questions   = context.user_data.get("quiz_questions", [])
    topic       = context.user_data.get("quiz_topic", "Unknown")
    subject     = context.user_data.get("quiz_subject", "Unknown")
    quiz_log    = context.user_data.get("quiz_log", [])
    weak_areas  = list(set(context.user_data.get("quiz_weak_areas", [])))
    total       = len(questions)
    percentage  = round((score / total) * 100, 1) if total > 0 else 0

    # Pick an emoji based on score
    if percentage >= 85:
        emoji = "🌟"
        grade = "Excellent!"
    elif percentage >= 70:
        emoji = "✅"
        grade = "Good job!"
    elif percentage >= 55:
        emoji = "📚"
        grade = "Keep studying!"
    else:
        emoji = "💪"
        grade = "Don't give up — review and try again!"

    # Save to database
    memory.save_quiz_session(
        topic       = topic,
        subject     = subject,
        score       = score,
        total       = total,
        weak_areas  = weak_areas,
        questions_log = quiz_log
    )

    # Mark quiz as done today
    memory.save_setting("quiz_done_today", "true")

    # Calculate next review date for context
    if percentage < 60:
        review_msg = "⚠️ This topic is marked for *review tomorrow*."
    elif percentage < 80:
        review_msg = "📅 This topic will come back for review in *3 days*."
    else:
        review_msg = "🗓️ Great! This topic will return in *7 days* for spaced review."

    summary = (
        f"{emoji} *Quiz Complete!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📚 Topic: {topic}\n"
        f"✅ Score: *{score}/{total}* ({percentage}%)\n"
        f"🏅 Grade: {grade}\n\n"
        f"{review_msg}\n\n"
        f"Send /lesson for your next topic, or /ask for any doubts! 💬"
    )

    try:
        await update.message.reply_text(summary, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text(f"Quiz done! Score: {score}/{total} ({percentage}%)")

    # Clear quiz state
    context.user_data.clear()

    logger.info("Quiz finished: topic='%s', score=%d/%d (%.1f%%)", topic, score, total, percentage)
    return ConversationHandler.END


async def cmd_quiz_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /cancel during a quiz."""
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Quiz cancelled. Your progress for this session was not saved.\n"
        "Send /quiz to start again anytime."
    )
    return ConversationHandler.END


# ─────────────────────────────────────────────
#  COMMAND: /ask
# ─────────────────────────────────────────────

async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /ask <question> — answer any EEE doubt."""
    if not _is_authorized(update):
        await _unauthorized_reply(update)
        return

    # The question is everything after /ask
    args     = context.args
    question = " ".join(args).strip() if args else ""

    if not question:
        await update.message.reply_text(
            "❓ *How to ask a doubt:*\n\n"
            "Type: `/ask your question here`\n\n"
            "Example: `/ask How does a transformer work?`\n"
            "Or: `/ask What is the formula for resonant frequency in an RLC circuit?`",
            parse_mode="Markdown"
        )
        return

    logger.info("Doubt question: '%s'", question[:80])
    await update.message.reply_text(f"🤔 Looking that up for you... ⏳")

    # Search knowledge base first
    context_text = knowledge.retrieve_context(question)

    # Get step-by-step answer from Claude
    answer = tutor.answer_doubt(question, STUDENT_LEVEL, context_text)
    await send_long_message(update, answer)


# ─────────────────────────────────────────────
#  FREE-TEXT: Handle questions without /ask
# ─────────────────────────────────────────────

async def handle_free_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    If the user just types a question (without any command prefix),
    treat it as a doubt question. This makes the bot feel more natural.
    """
    if not _is_authorized(update):
        return

    text = update.message.text.strip()

    # If it looks like a question (has a ?) or is long enough
    if "?" in text or len(text) > 20:
        await update.message.reply_text("🤔 Let me answer that... ⏳")
        context_text = knowledge.retrieve_context(text)
        answer       = tutor.answer_doubt(text, STUDENT_LEVEL, context_text)
        await send_long_message(update, answer)
    else:
        await update.message.reply_text(
            "I'm your EEE tutor! Ask me anything about Electrical & Electronics Engineering.\n\n"
            "Commands: /lesson /quiz /ask /progress /report /settings"
        )


# ─────────────────────────────────────────────
#  COMMAND: /progress
# ─────────────────────────────────────────────

async def cmd_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /progress — show weekly stats."""
    if not _is_authorized(update):
        await _unauthorized_reply(update)
        return

    logger.info("/progress requested")
    await update.message.reply_text("📊 Fetching your progress... ⏳")

    progress = memory.get_weekly_progress()
    kb_stats = knowledge.get_knowledge_stats()

    # Format the topics covered this week
    topics_list = ""
    if progress["topics_this_week"]:
        topics_list = "\n".join(
            [f"  • {t['topic']} ({t['subject'][:2]})" for t in progress["topics_this_week"][:5]]
        )
    else:
        topics_list = "  _No topics covered this week yet_"

    # Format weak topics
    weak_list = ""
    if progress["weak_topics"]:
        weak_list = "\n".join(
            [f"  • {t['topic']} ({round(t['weak_score']*100)}% weak)"
             for t in progress["weak_topics"][:3]]
        )
    else:
        weak_list = "  _No weak topics — great job!_ 🌟"

    report = (
        "📊 *Weekly Progress*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📅 *This Week:*\n"
        f"  Lessons/Quizzes: {progress['lessons_this_week']}\n"
        f"  Avg Score: {progress['avg_score_this_week']}%\n\n"
        f"📚 *Topics This Week:*\n{topics_list}\n\n"
        f"⚠️ *Weak Topics (for review):*\n{weak_list}\n\n"
        f"🎯 *Overall Syllabus Progress:*\n"
        f"  {progress['total_taught']}/{progress['total_topics']} topics "
        f"({progress['completion_pct']}%)\n\n"
        f"🧠 *Knowledge Base:*\n"
        f"  {kb_stats['files_indexed']} files, "
        f"{kb_stats['article_summaries']} web articles"
    )

    try:
        await update.message.reply_text(report, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text(report)


# ─────────────────────────────────────────────
#  COMMAND: /report
# ─────────────────────────────────────────────

async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /report — full all-time stats plus AI-generated summary."""
    if not _is_authorized(update):
        await _unauthorized_reply(update)
        return

    await update.message.reply_text("📋 Generating your full report... ⏳")

    stats    = memory.get_all_time_stats()
    progress = memory.get_weekly_progress()

    # Generate AI summary
    ai_summary = tutor.generate_weekly_summary(progress, STUDENT_LEVEL)

    lifetime = (
        "📋 *All-Time Report*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📝 Total Quizzes Taken: {stats['total_quizzes']}\n"
        f"📊 All-Time Avg Score: {stats['avg_score']}%\n"
        f"📚 Topics Taught: {stats['topics_taught']}\n\n"
    )

    if stats["strongest"]:
        strongest = "\n".join([f"  • {t['topic']}" for t in stats["strongest"][:3]])
        lifetime += f"💪 *Strongest Topics:*\n{strongest}\n\n"

    if stats["weakest"]:
        weakest = "\n".join([f"  • {t['topic']}" for t in stats["weakest"][:3]])
        lifetime += f"⚠️ *Weakest Topics (focus here):*\n{weakest}\n\n"

    lifetime += "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n" + ai_summary

    await send_long_message(update, lifetime)


# ─────────────────────────────────────────────
#  COMMAND: /settings
# ─────────────────────────────────────────────

async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /settings — show current settings."""
    if not _is_authorized(update):
        await _unauthorized_reply(update)
        return

    study_time    = os.getenv("STUDY_TIME", "08:00")
    timezone      = os.getenv("TIMEZONE", "Asia/Kolkata")
    student_level = os.getenv("STUDENT_LEVEL", "beginner")
    student_year  = os.getenv("STUDENT_YEAR", "2")

    await update.message.reply_text(
        "⚙️ *Current Settings*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⏰ Daily Lesson Time: *{study_time}*\n"
        f"🌍 Timezone: *{timezone}*\n"
        f"🎓 Student Level: *{student_level}*\n"
        f"📅 Year of Study: *{student_year}*\n\n"
        "To change settings, edit the *.env* file and restart the bot.\n\n"
        "📁 To add study material:\n"
        "  Drop PDF/TXT files into the *knowledge/* folder\n"
        "  They'll be indexed automatically within 10 minutes!",
        parse_mode="Markdown"
    )


# ─────────────────────────────────────────────
#  ERROR HANDLER
# ─────────────────────────────────────────────

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Log errors and send a friendly message to the user."""
    logger.error("Telegram error: %s", context.error, exc_info=True)

    if isinstance(update, Update) and update.message:
        try:
            await update.message.reply_text(
                "⚠️ Something went wrong on my end. Please try again in a moment!\n"
                "If the problem persists, check the logs/ folder."
            )
        except Exception:
            pass


# ─────────────────────────────────────────────
#  BOT STARTUP
# ─────────────────────────────────────────────

async def post_init(application: Application):
    """
    Called once after the bot starts up.
    Sets up the database, loads the syllabus, indexes the knowledge folder,
    and starts the scheduler.
    """
    logger.info("=== EEE TUTOR BOT STARTING ===")

    # Initialize database and load syllabus
    memory.init_db()
    if os.path.exists(SYLLABUS_PATH):
        memory.load_syllabus_into_db(SYLLABUS_PATH)
    else:
        logger.warning("syllabus.json not found at %s", SYLLABUS_PATH)

    # Index any existing files in the knowledge folder
    logger.info("Indexing knowledge folder on startup...")
    knowledge.index_knowledge_folder()

    # Give the scheduler access to the bot
    sched.set_bot_app(application)

    # Start the scheduler
    scheduler = sched.create_scheduler()
    scheduler.start()
    logger.info("Scheduler started with %d jobs.", len(scheduler.get_jobs()))

    logger.info("=== BOT READY! Listening for messages... ===")


def main():
    """
    Main function — sets up the bot and starts polling for messages.
    This is the function that runs when you do: python bot.py
    """
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set in .env file! Cannot start bot.")
        return

    if not os.getenv("CLAUDE_API_KEY"):
        logger.error("CLAUDE_API_KEY not set in .env file! Cannot start bot.")
        return

    logger.info("Building Telegram application...")

    # Build the Telegram application
    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .post_init(post_init)
        .build()
    )

    # ── Register command handlers ──

    # /start
    app.add_handler(CommandHandler("start", cmd_start))

    # /lesson
    app.add_handler(CommandHandler("lesson", cmd_lesson))

    # /ask <question>
    app.add_handler(CommandHandler("ask", cmd_ask))

    # /progress
    app.add_handler(CommandHandler("progress", cmd_progress))

    # /report
    app.add_handler(CommandHandler("report", cmd_report))

    # /settings
    app.add_handler(CommandHandler("settings", cmd_settings))

    # /quiz — uses a ConversationHandler (multi-step conversation)
    quiz_handler = ConversationHandler(
        entry_points = [CommandHandler("quiz", cmd_quiz_start)],
        states       = {
            QUIZ_ANSWERING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_quiz_answer)
            ],
        },
        fallbacks    = [CommandHandler("cancel", cmd_quiz_cancel)],
        allow_reentry = True
    )
    app.add_handler(quiz_handler)

    # Handle any free-text messages (doubt questions without /ask)
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_free_text)
    )

    # Error handler
    app.add_error_handler(error_handler)

    # ── Start the bot ──
    logger.info("Starting bot polling... (Press Ctrl+C to stop)")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
