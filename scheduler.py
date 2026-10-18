"""
scheduler.py — Automated Job Scheduler
=======================================
This file sets up all timed/automated tasks using APScheduler.

Jobs scheduled:
  1. Daily lesson   — Every day at your configured STUDY_TIME
  2. Study reminder — 2 hours after a lesson, if no quiz was started
  3. Weekly report  — Every Sunday at 8:00 AM
  4. Weekly RSS     — Every Sunday at 6:00 AM (before the report)
  5. PDF watcher    — Every 10 minutes, check for new files in /knowledge

Each job is a simple Python function that the scheduler calls automatically.
"""

import os
import logging
import asyncio
from datetime import datetime

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv

import memory
import tutor
import knowledge

load_dotenv()

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  CONFIGURATION
# ─────────────────────────────────────────────

TIMEZONE       = os.getenv("TIMEZONE", "Asia/Kolkata")
STUDY_TIME     = os.getenv("STUDY_TIME", "08:00")   # e.g. "08:00"
STUDENT_LEVEL  = os.getenv("STUDENT_LEVEL", "beginner")

# Parse the study time into hour and minute
try:
    _study_hour, _study_minute = [int(x) for x in STUDY_TIME.split(":")]
except ValueError:
    logger.warning("Invalid STUDY_TIME '%s', defaulting to 08:00", STUDY_TIME)
    _study_hour, _study_minute = 8, 0

# We hold a reference to the Telegram bot application here
# so the scheduler can send messages
_bot_app = None


def set_bot_app(app):
    """
    Called from bot.py to give the scheduler a reference to the
    running Telegram bot application (so it can send messages).
    """
    global _bot_app
    _bot_app = app
    logger.info("Bot app reference set in scheduler.")


async def _send_telegram_message(text: str, parse_mode: str = "Markdown"):
    """
    Internal helper: send a message to the configured Telegram chat.
    Uses the YOUR_TELEGRAM_CHAT_ID from the .env file.
    """
    if _bot_app is None:
        logger.error("Bot app not set — cannot send scheduled message.")
        return

    chat_id = os.getenv("YOUR_TELEGRAM_CHAT_ID")
    if not chat_id:
        logger.error("YOUR_TELEGRAM_CHAT_ID not set in .env file.")
        return

    try:
        await _bot_app.bot.send_message(
            chat_id    = int(chat_id),
            text       = text[:4096],   # Telegram message length limit
            parse_mode = parse_mode
        )
        logger.info("Scheduled message sent to chat_id=%s", chat_id)
    except Exception as e:
        logger.error("Failed to send scheduled message: %s", str(e))


# ─────────────────────────────────────────────
#  JOB 1: DAILY LESSON
# ─────────────────────────────────────────────

async def job_daily_lesson():
    """
    Triggered every day at STUDY_TIME.
    Picks the next topic, generates a lesson, sends it via Telegram.
    """
    logger.info("=== DAILY LESSON JOB STARTED ===")

    # Step 1: Pick the next topic using spaced repetition
    topic_data = memory.get_next_topic()
    if not topic_data:
        await _send_telegram_message(
            "🎉 Amazing! You've completed your entire EEE syllabus! "
            "Start adding new topics to syllabus.json to continue learning."
        )
        return

    topic   = topic_data["topic"]
    subject = topic_data["subject"]
    topic_id = topic_data["id"]

    # Step 2: Search knowledge base for relevant context (RAG)
    context = knowledge.retrieve_context(f"{subject}: {topic}")

    # Step 3: Generate the lesson using Claude
    await _send_telegram_message(
        f"📖 *Good morning! Time to study!*\n\n"
        f"Today's topic: *{topic}*\n"
        f"Subject: _{subject}_\n\n"
        f"Generating your lesson... ⏳"
    )

    lesson_text = tutor.generate_lesson(
        topic         = topic,
        subject       = subject,
        student_level = STUDENT_LEVEL,
        context       = context
    )

    # Step 4: Send the lesson
    # Telegram has a 4096 character limit — split if needed
    if len(lesson_text) > 4000:
        # Send in two parts
        await _send_telegram_message(lesson_text[:4000])
        await _send_telegram_message(lesson_text[4000:])
    else:
        await _send_telegram_message(lesson_text)

    # Step 5: Save that this topic was taught today
    memory.mark_topic_taught(topic_id)

    # Step 6: Store today's topic in settings so bot.py quiz knows what to ask about
    memory.save_setting("current_topic", topic)
    memory.save_setting("current_subject", subject)
    memory.save_setting("current_topic_id", str(topic_id))
    memory.save_setting("lesson_sent_today", datetime.now().isoformat())
    memory.save_setting("quiz_done_today", "false")

    # Step 7: Prompt user to take the quiz
    await _send_telegram_message(
        "✅ Lesson complete!\n\n"
        "Ready to test what you learned? Send /quiz to start your 20-question quiz!\n\n"
        "💬 Or ask any doubt with: /ask your question here"
    )

    logger.info("Daily lesson sent for topic: '%s'", topic)


# ─────────────────────────────────────────────
#  JOB 2: STUDY REMINDER
# ─────────────────────────────────────────────

async def job_study_reminder():
    """
    Triggered 2 hours after the lesson time, if the user hasn't started the quiz.
    A gentle nudge — not annoying!
    """
    logger.info("Checking if study reminder is needed...")

    quiz_done  = memory.get_setting("quiz_done_today", "false")
    lesson_sent = memory.get_setting("lesson_sent_today", "")

    if quiz_done == "true" or not lesson_sent:
        logger.info("No reminder needed (quiz done or no lesson today).")
        return

    topic   = memory.get_setting("current_topic", "today's topic")
    subject = memory.get_setting("current_subject", "")

    await _send_telegram_message(
        f"⏰ *Study reminder!*\n\n"
        f"Hey! You haven't taken your quiz on *{topic}* yet.\n\n"
        f"It only takes 10 minutes and really helps you remember! "
        f"Send /quiz whenever you're ready. 📝\n\n"
        f"_You've got this!_ 💪"
    )
    logger.info("Study reminder sent.")


# ─────────────────────────────────────────────
#  JOB 3: WEEKLY PROGRESS REPORT
# ─────────────────────────────────────────────

async def job_weekly_report():
    """
    Triggered every Sunday morning.
    Generates and sends a weekly progress summary.
    """
    logger.info("=== WEEKLY REPORT JOB STARTED ===")

    try:
        # Get progress data from SQLite
        progress_data = memory.get_weekly_progress()
        kb_stats      = knowledge.get_knowledge_stats()

        # Generate a human-friendly summary using Claude
        summary = tutor.generate_weekly_summary(progress_data, STUDENT_LEVEL)

        # Add knowledge base stats
        kb_info = (
            f"\n\n📚 *Knowledge Base:* "
            f"{kb_stats['files_indexed']} files indexed, "
            f"{kb_stats['article_summaries']} web articles stored"
        )

        report = (
            "📊 *WEEKLY PROGRESS REPORT*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            + summary
            + kb_info
            + "\n\n_Keep it up! See you tomorrow for the next lesson._ 🎓"
        )

        await _send_telegram_message(report)
        logger.info("Weekly report sent.")

    except Exception as e:
        logger.error("Weekly report failed: %s", str(e))
        await _send_telegram_message(
            "📊 *Weekly Summary*\n\n"
            "I tried to generate your progress report but ran into an issue. "
            "Use /progress to check your stats manually!"
        )


# ─────────────────────────────────────────────
#  JOB 4: WEEKLY RSS FETCH
# ─────────────────────────────────────────────

async def job_fetch_rss():
    """
    Triggered every Sunday morning (before the weekly report).
    Fetches new EEE articles and adds them to the knowledge base.
    """
    logger.info("=== WEEKLY RSS FETCH JOB STARTED ===")

    try:
        count = knowledge.fetch_rss_articles()
        if count > 0:
            await _send_telegram_message(
                f"🔄 *Knowledge base updated!*\n"
                f"Added {count} new EEE articles from the web. "
                f"Your lessons will be even better this week! 📡"
            )
    except Exception as e:
        logger.error("RSS fetch job failed: %s", str(e))


# ─────────────────────────────────────────────
#  JOB 5: PDF FOLDER WATCHER
# ─────────────────────────────────────────────

async def job_watch_knowledge_folder():
    """
    Runs every 10 minutes.
    Checks if any new PDFs or notes were added to /knowledge and indexes them.
    """
    try:
        new_count = knowledge.index_knowledge_folder()
        if new_count > 0:
            logger.info("Knowledge folder: indexed %d new files.", new_count)
            await _send_telegram_message(
                f"📥 *New study material detected!*\n"
                f"Indexed {new_count} new file(s) from your /knowledge folder.\n"
                f"I'll use these in your future lessons! 🧠"
            )
    except Exception as e:
        logger.error("Knowledge folder watcher failed: %s", str(e))


# ─────────────────────────────────────────────
#  SCHEDULER INITIALIZATION
# ─────────────────────────────────────────────

def create_scheduler() -> AsyncIOScheduler:
    """
    Create and configure the APScheduler with all jobs.
    Returns the scheduler (not yet started — call scheduler.start() separately).
    """
    tz        = pytz.timezone(TIMEZONE)
    scheduler = AsyncIOScheduler(timezone=tz)

    # Job 1: Daily lesson — runs at STUDY_TIME every day
    scheduler.add_job(
        func    = job_daily_lesson,
        trigger = CronTrigger(hour=_study_hour, minute=_study_minute, timezone=tz),
        id      = "daily_lesson",
        name    = "Daily EEE Lesson",
        replace_existing = True
    )
    logger.info("Scheduled daily lesson at %02d:%02d %s", _study_hour, _study_minute, TIMEZONE)

    # Job 2: Study reminder — 2 hours after the lesson
    reminder_hour   = (_study_hour + 2) % 24
    reminder_minute = _study_minute
    scheduler.add_job(
        func    = job_study_reminder,
        trigger = CronTrigger(hour=reminder_hour, minute=reminder_minute, timezone=tz),
        id      = "study_reminder",
        name    = "Study Reminder",
        replace_existing = True
    )
    logger.info("Scheduled study reminder at %02d:%02d %s", reminder_hour, reminder_minute, TIMEZONE)

    # Job 3: Weekly report — every Sunday at 9:00 AM
    scheduler.add_job(
        func    = job_weekly_report,
        trigger = CronTrigger(day_of_week="sun", hour=9, minute=0, timezone=tz),
        id      = "weekly_report",
        name    = "Weekly Progress Report",
        replace_existing = True
    )
    logger.info("Scheduled weekly report: every Sunday at 09:00 %s", TIMEZONE)

    # Job 4: RSS fetch — every Sunday at 7:00 AM (2 hours before the report)
    scheduler.add_job(
        func    = job_fetch_rss,
        trigger = CronTrigger(day_of_week="sun", hour=7, minute=0, timezone=tz),
        id      = "weekly_rss",
        name    = "Weekly RSS Article Fetch",
        replace_existing = True
    )
    logger.info("Scheduled weekly RSS fetch: every Sunday at 07:00 %s", TIMEZONE)

    # Job 5: PDF watcher — every 10 minutes
    scheduler.add_job(
        func    = job_watch_knowledge_folder,
        trigger = IntervalTrigger(minutes=10),
        id      = "pdf_watcher",
        name    = "Knowledge Folder Watcher",
        replace_existing = True,
        next_run_time = datetime.now(tz)   # Run immediately on startup too
    )
    logger.info("Scheduled knowledge folder watcher: every 10 minutes")

    return scheduler
