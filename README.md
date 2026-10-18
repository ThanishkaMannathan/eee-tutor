# 🎓 Daily EEE Tutor

> A fully automated, AI-powered study companion for Electrical & Electronics Engineering students.
> Powered by **Claude AI** (Anthropic) + **Telegram** + **ChromaDB RAG**.

---

## ✨ Features

| Feature | What it does |
|---------|-------------|
| 📖 Daily Lesson | Sends a 10-minute AI-generated lesson every day at your chosen time |
| 📝 Daily Quiz | 20-question quiz (15 MCQ + 5 short answer), automatically graded with explanations |
| ❓ Doubt Solver | Ask any EEE question anytime — get step-by-step answers |
| 🧠 Spaced Repetition | Weak topics come back sooner; strong topics get longer breaks |
| 📚 Knowledge Base | Drop your PDFs/notes into `/knowledge` — they're auto-indexed and used in lessons |
| 📡 Weekly Articles | Fetches fresh EEE articles from IEEE, Electronics Tutorials, etc. every Sunday |
| 📊 Progress Reports | Weekly report: scores, weak areas, topics covered |
| ⏰ Reminders | Gentle nudge if you haven't taken your quiz after 2 hours |

---

## 📁 Project Structure

```
eee-tutor/
├── bot.py           ← Main file — run this to start the bot
├── tutor.py         ← Claude AI engine (lessons, quizzes, grading)
├── memory.py        ← SQLite database + spaced repetition
├── knowledge.py     ← ChromaDB RAG (PDF indexing, RSS fetching)
├── scheduler.py     ← APScheduler (daily lesson, reminders, weekly report)
├── syllabus.json    ← Your EEE topics (edit to customize)
├── requirements.txt ← Python packages to install
├── .env.example     ← Template for your secret keys
├── .env             ← YOUR secrets (never share this!)
├── knowledge/       ← Drop your PDFs and notes here!
├── data/            ← SQLite database (auto-created)
├── chroma_db/       ← Vector database (auto-created)
└── logs/            ← Log files (auto-created)
```

---

## 🚀 Step-by-Step Setup

### Step 1 — Install Python 3.11+

Download from [python.org](https://www.python.org/downloads/).

On **Windows**: during installation, ✅ check **"Add Python to PATH"**.

Verify installation:
```bash
python --version
# Should show: Python 3.11.x or higher
```

---

### Step 2 — Create a Telegram Bot with BotFather

1. Open Telegram and search for **@BotFather**
2. Send: `/newbot`
3. Choose a name, e.g. `My EEE Tutor`
4. Choose a username, e.g. `my_eee_tutor_bot` *(must end in `bot`)*
5. BotFather will give you a **token** that looks like:
   ```
   1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ
   ```
6. Copy and save this token — you'll need it for the `.env` file

**Get your personal Chat ID:**
1. Start a conversation with your new bot (send `/start`)
2. Visit this URL in your browser (replace `TOKEN` with yours):
   ```
   https://api.telegram.org/botTOKEN/getUpdates
   ```
3. Look for `"chat":{"id":` — the number after it is your **Chat ID**

---

### Step 3 — Get a Claude API Key

1. Go to [console.anthropic.com](https://console.anthropic.com/)
2. Sign up / log in
3. Go to **API Keys** → **Create Key**
4. Copy the key (it starts with `sk-ant-...`)
5. ⚠️ Store it safely — you can only view it once!

---

### Step 4 — Configure Your .env File

```bash
# In your project folder:
copy .env.example .env
```

Open `.env` in any text editor (Notepad, VS Code, etc.) and fill in:

```env
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ
CLAUDE_API_KEY=sk-ant-your_key_here
YOUR_TELEGRAM_CHAT_ID=987654321
STUDY_TIME=08:00
STUDENT_YEAR=2
STUDENT_LEVEL=beginner
TIMEZONE=Asia/Kolkata
```

> **Timezones**: Use values like `Asia/Kolkata`, `Asia/Dubai`, `America/New_York`, `Europe/London`.
> Full list: [Wikipedia timezone list](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)

---

### Step 5 — Install Dependencies

```bash
# Navigate to your project folder
cd "C:\Users\Thanishka M S\OneDrive\Documents\EEE assistent"

# Install all packages
pip install -r requirements.txt
```

> ⏳ First install takes 3-5 minutes (it downloads the AI embedding model ~90 MB).

---

### Step 6 — Run the Bot!

```bash
python bot.py
```

You should see in the terminal:
```
=== EEE TUTOR BOT STARTING ===
Database initialized at: data/tutor.db
Loaded 140 new topics from syllabus into database.
Indexing knowledge folder on startup...
Scheduler started with 5 jobs.
=== BOT READY! Listening for messages... ===
```

Now open Telegram, send `/start` to your bot, and you're off! 🎉

---

## 📖 How to Use

| Command | What it does |
|---------|-------------|
| `/start` | Welcome message and overview |
| `/lesson` | Get today's lesson immediately (don't wait for scheduled time) |
| `/quiz` | Start the 20-question quiz on the last lesson topic |
| `/ask How does a BJT work?` | Get a step-by-step answer to any EEE question |
| `/progress` | See this week's scores and weak areas |
| `/report` | Full all-time stats + AI-generated progress summary |
| `/settings` | View your current settings |

**Tip:** You can also just type any question without a command — the bot will answer it!

---

## 📚 Adding Your Notes and Textbooks

1. Copy your PDFs, scanned notes, or text files into the **`knowledge/`** folder
2. The bot checks for new files every **10 minutes** automatically
3. When new files are found, they're chunked, embedded, and stored in ChromaDB
4. Future lessons will reference your notes and cite the source!

**Supported formats:** `.pdf`, `.txt`, `.md`

---

## 🔧 Customizing the Syllabus

Edit `syllabus.json` to change topics:
- Add new subjects by copying an existing subject block
- Reorder topics within a subject
- Add or remove individual topic strings

After editing, restart the bot — new topics are loaded automatically.

---

## 🌐 Running 24/7 (Deployment Guide)

### Option A — Windows (Keep your PC on)

Use **Task Scheduler** to run the bot automatically at startup:
1. Open **Task Scheduler** → Create Basic Task
2. Trigger: **At log on** or **At startup**
3. Action: Start a program → `python` → Arguments: `bot.py`
4. Set the working directory to your project folder

Or use **NSSM** (Non-Sucking Service Manager) to run it as a Windows Service:
```cmd
nssm install EEETutor python bot.py
nssm set EEETutor AppDirectory "C:\Users\Thanishka M S\OneDrive\Documents\EEE assistent"
nssm start EEETutor
```

---

### Option B — Free Cloud (Recommended for reliability)

#### Railway.app (Easiest, free tier available)
1. Create account at [railway.app](https://railway.app)
2. Install Railway CLI: `npm install -g @railway/cli`
3. In your project folder:
   ```bash
   railway login
   railway init
   railway up
   ```
4. Add environment variables in Railway dashboard (same as your .env)

#### Render.com (Free tier, sleeps after 15 min idle)
1. Create account at [render.com](https://render.com)
2. New → Background Worker
3. Connect your GitHub repo (push your code there first)
4. Build command: `pip install -r requirements.txt`
5. Start command: `python bot.py`
6. Add environment variables in the dashboard

---

### Option C — Raspberry Pi (Best for always-on at home)

```bash
# 1. Copy files to your Pi (via USB or SSH)
# 2. Install dependencies
pip3 install -r requirements.txt

# 3. Create a systemd service for auto-restart
sudo nano /etc/systemd/system/eeetutor.service
```

Paste this into the file:
```ini
[Unit]
Description=EEE Tutor Bot
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/eee-tutor
ExecStart=/usr/bin/python3 /home/pi/eee-tutor/bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then enable it:
```bash
sudo systemctl daemon-reload
sudo systemctl enable eeetutor
sudo systemctl start eeetutor

# Check if it's running:
sudo systemctl status eeetutor
```

---

### Option D — Oracle Cloud Always Free

Oracle Cloud offers a **forever-free** ARM VM (4 CPU, 24 GB RAM):
1. Sign up at [cloud.oracle.com](https://cloud.oracle.com) → Always Free
2. Create an Ubuntu ARM instance
3. SSH in, clone your project, run as a systemd service (same as Raspberry Pi)

---

## 🐛 Troubleshooting

| Problem | Solution |
|---------|----------|
| `TELEGRAM_BOT_TOKEN not set` | Check your `.env` file exists and has the token |
| `AuthenticationError` | Your Claude API key is wrong or expired |
| Bot doesn't respond | Make sure `YOUR_TELEGRAM_CHAT_ID` matches your Telegram ID |
| `ModuleNotFoundError` | Run `pip install -r requirements.txt` again |
| Slow first start | Normal! The embedding model downloads on first run (~90 MB) |
| Quiz questions look wrong | Claude API issue — check logs/tutor.log for details |

**Viewing logs:**
```bash
# Windows
type logs\tutor.log

# Linux/Mac
tail -f logs/tutor.log
```

---

## 💰 Running Costs

| Service | Cost |
|---------|------|
| Claude API | ~$0.01-0.05 per lesson+quiz (very cheap!) |
| Telegram Bot | Free forever |
| ChromaDB | Free (runs locally) |
| Railway.app | Free tier: 500 hours/month |
| Raspberry Pi | One-time hardware cost, electricity ~$2/month |

---

## 🙏 Credits

Built with:
- [Anthropic Claude](https://www.anthropic.com/) — AI engine
- [python-telegram-bot](https://python-telegram-bot.org/) — Telegram integration
- [ChromaDB](https://www.trychroma.com/) — Vector database
- [sentence-transformers](https://www.sbert.net/) — Free local embeddings
- [APScheduler](https://apscheduler.readthedocs.io/) — Job scheduling
- [PyMuPDF](https://pymupdf.readthedocs.io/) — PDF parsing

---

*Happy studying! Remember: consistency beats intensity. Even 10 minutes a day adds up to mastery over time. 🎓*
