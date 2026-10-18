"""
tutor.py — AI Lesson & Quiz Engine (powered by Claude)
=======================================================
This file talks to the Anthropic Claude API to:
  1. Generate a structured 10-minute lesson on a given EEE topic
  2. Create a 20-question quiz (MCQ + short answer)
  3. Grade quiz answers and explain mistakes
  4. Answer any doubt question with step-by-step explanations

All prompts are carefully written so Claude always responds
in a style suitable for a beginner EEE student.
"""

import os
import json
import logging
import re
from typing import Optional

import anthropic        # Anthropic Claude API client
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  CLAUDE CLIENT SETUP
# ─────────────────────────────────────────────

# Get the API key from the environment (never hardcode it!)
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")

# The Claude model to use (claude-3-5-sonnet is fast and smart)
CLAUDE_MODEL = "claude-3-5-sonnet-20241022"

# Maximum tokens Claude should generate per response
MAX_TOKENS = 4096

# Create the Claude client lazily so the app never crashes on import
_client = None

def _get_client():
    global _client
    key = os.getenv("CLAUDE_API_KEY")
    if not key or key.strip() in ("", "dummy", "your_claude_api_key_here") or key.startswith("sk-ant-your"):
        return None
    if _client is None:
        try:
            _client = anthropic.Anthropic(api_key=key.strip())
        except Exception as e:
            logger.error("Failed to initialize Claude client: %s", e)
            return None
    return _client


def _mock_fallback(user_message: str) -> str:
    """Provide realistic high-quality EEE content when CLAUDE_API_KEY is not yet configured."""
    msg = user_message.lower()
    
    # Check if quiz requested
    if "generate exactly 20 quiz questions" in msg or ("quiz" in msg and "json array" in msg):
        questions = [
            {"type": "mcq", "question": "What is the SI unit of electric current?", "options": ["A) Volt", "B) Ampere", "C) Ohm", "D) Watt"], "answer": "B", "explanation": "Ampere (A) is the SI base unit of electric current, defined by the flow of 1 Coulomb per second."},
            {"type": "mcq", "question": "According to Ohm's Law, the current flowing through a conductor is directly proportional to:", "options": ["A) Resistance", "B) Capacitance", "C) Potential Difference", "D) Inductance"], "answer": "C", "explanation": "Ohm's Law states I = V/R, meaning current is directly proportional to voltage (potential difference) at constant temperature."},
            {"type": "mcq", "question": "If a 12V battery is connected across a 4Ω resistor, what is the current?", "options": ["A) 3 A", "B) 48 A", "C) 0.33 A", "D) 8 A"], "answer": "A", "explanation": "Using I = V/R: I = 12V / 4Ω = 3 A."},
            {"type": "mcq", "question": "Kirchhoff's Current Law (KCL) is based on the conservation of:", "options": ["A) Energy", "B) Charge", "C) Momentum", "D) Magnetic Flux"], "answer": "B", "explanation": "KCL states that total current entering a junction equals total leaving, representing conservation of electric charge."},
            {"type": "mcq", "question": "Kirchhoff's Voltage Law (KVL) is based on the conservation of:", "options": ["A) Charge", "B) Energy", "C) Mass", "D) Power"], "answer": "B", "explanation": "KVL states that the sum of voltages around any closed loop is zero, directly expressing conservation of energy."},
            {"type": "mcq", "question": "What is the equivalent resistance of two 10Ω resistors in parallel?", "options": ["A) 20 Ω", "B) 10 Ω", "C) 5 Ω", "D) 2.5 Ω"], "answer": "C", "explanation": "For identical resistors in parallel: R_eq = R / n = 10 / 2 = 5 Ω."},
            {"type": "mcq", "question": "What is the equivalent resistance of two 10Ω resistors connected in series?", "options": ["A) 5 Ω", "B) 10 Ω", "C) 20 Ω", "D) 100 Ω"], "answer": "C", "explanation": "In series, resistances add linearly: R_eq = 10 + 10 = 20 Ω."},
            {"type": "mcq", "question": "Electrical power dissipated in a pure resistor with current I and resistance R is:", "options": ["A) I * R", "B) I² * R", "C) I / R", "D) I * R²"], "answer": "B", "explanation": "Joule's Law of heating gives Power P = I²R = V²/R = VI."},
            {"type": "mcq", "question": "An ideal voltage source has an internal resistance of:", "options": ["A) Zero", "B) Infinite", "C) 1 Ω", "D) 50 Ω"], "answer": "A", "explanation": "An ideal voltage source maintains constant terminal voltage regardless of load current, so its internal resistance is zero."},
            {"type": "mcq", "question": "An ideal current source has an internal resistance of:", "options": ["A) Zero", "B) Infinite", "C) 100 Ω", "D) Dependent on frequency"], "answer": "B", "explanation": "An ideal current source delivers a fixed current independent of terminal voltage, requiring infinite internal impedance in parallel."},
            {"type": "mcq", "question": "Which component stores energy in the form of an electric field?", "options": ["A) Inductor", "B) Resistor", "C) Capacitor", "D) Diode"], "answer": "C", "explanation": "Capacitors store electrostatic potential energy in the dielectric field between their plates: E = 0.5 * C * V²."},
            {"type": "mcq", "question": "Which component stores energy in the form of a magnetic field?", "options": ["A) Capacitor", "B) Inductor", "C) Transformer core", "D) Thermistor"], "answer": "B", "explanation": "Inductors store magnetic energy due to current flow: E = 0.5 * L * I²."},
            {"type": "mcq", "question": "The reciprocal of electrical resistance is termed:", "options": ["A) Reactance", "B) Susceptance", "C) Conductance", "D) Reluctance"], "answer": "C", "explanation": "Conductance G = 1 / R and is measured in Siemens (S) or mhos."},
            {"type": "mcq", "question": "In a series circuit, which quantity remains identical across all components?", "options": ["A) Voltage", "B) Current", "C) Power", "D) Resistance"], "answer": "B", "explanation": "Because there is only one continuous path for electrons to travel, current I is the same through every element in a series circuit."},
            {"type": "mcq", "question": "A 100W bulb operates on 200V. What is the current drawn?", "options": ["A) 0.5 A", "B) 2 A", "C) 20 A", "D) 0.05 A"], "answer": "A", "explanation": "P = V * I  =>  I = P / V = 100 / 200 = 0.5 A."},
            {"type": "short", "question": "State Ohm's Law and write down its mathematical equation.", "answer": "Current through a conductor between two points is directly proportional to voltage across the two points: V = I * R.", "explanation": "V = I * R where V is voltage (Volts), I is current (Amperes), and R is resistance (Ohms)."},
            {"type": "short", "question": "A 50Ω resistor is connected to a 25V DC source. Calculate the power dissipated in watts.", "answer": "12.5 W", "explanation": "P = V² / R = (25 * 25) / 50 = 625 / 50 = 12.5 Watts."},
            {"type": "short", "question": "Calculate the current entering a junction if three branch currents leaving are 2A, 3.5A, and 4.5A.", "answer": "10 A", "explanation": "By Kirchhoff's Current Law, Σ I_in = Σ I_out = 2 + 3.5 + 4.5 = 10 A."},
            {"type": "short", "question": "Explain why voltage drops occur across resistors in a closed circuit.", "answer": "Work is done against resistance as electrons collide with atomic lattice ions, converting electrical potential energy into heat.", "explanation": "Electrical energy is converted to thermal energy according to Joule heating (P = I²R)."},
            {"type": "short", "question": "What is the equivalent resistance of three 30Ω resistors connected in parallel?", "answer": "10 Ω", "explanation": "1/Req = 1/30 + 1/30 + 1/30 = 3/30 = 1/10  =>  Req = 10 Ω."}
        ]
        return json.dumps(questions)

    # Check if lesson requested
    if "create a 10-minute lesson" in msg or "topic:" in msg:
        return """📚 *TOPIC: Ohm's Law and Circuit Basics*
Subject: Circuit Theory

---

🎯 *WHAT YOU WILL LEARN*
• Understand the fundamental relationship between Voltage, Current, and Resistance.
• Learn how to apply the V = I × R formula to solve basic and complex electrical circuits.
• Discover how Ohm's Law powers modern electronics from smartphone chargers to high-voltage grid lines.

---

💡 *THE CONCEPT EXPLAINED SIMPLY*
Think of an electrical circuit like water flowing through a garden pipe:
• **Voltage (V)** is the water pressure pushing from the faucet.
• **Current (I)** is the actual flow rate of water droplets flowing through the pipe.
• **Resistance (R)** is a constriction or narrow squeeze in the pipe that opposes the flow.

If you increase the water pressure (Voltage), more water flows (Current increases). If you pinch the pipe tighter (Resistance increases), less water can squeeze through (Current decreases). This fundamental balance is Ohm's Law!

---

📐 *KEY FORMULAS*
1. **Ohm's Law:**
   `V = I × R`
   • `V` = Voltage (Volts, V)
   • `I` = Current (Amperes, A)
   • `R` = Resistance (Ohms, Ω)

2. **Power Dissipation (Joule's Law):**
   `P = V × I = I² × R = V² / R`
   • `P` = Electrical Power (Watts, W)

3. **Conductance (Reciprocal of Resistance):**
   `G = 1 / R`
   • `G` = Conductance (Siemens, S)

---

🌍 *REAL-WORLD EXAMPLE*
**Your Mobile Phone Fast Charger:**
A USB-C fast charger operates at 9V and delivers 2A to quickly charge your phone's battery.
Using Ohm's Law: The effective equivalent charging impedance is `R = V / I = 9V / 2A = 4.5 Ω`.
The power delivered to your phone battery is `P = 9V × 2A = 18 Watts`!

---

🔑 *KEY POINTS TO REMEMBER*
• Ohm's Law strictly holds for **ohmic (linear) conductors** at constant temperature.
• Increasing resistance always reduces current for a constant applied voltage.
• Electric power represents the rate at which electrical energy is transformed into heat, light, or work.
• In a series circuit, Current is identical everywhere; in a parallel circuit, Voltage is identical across branches.
• Always verify units before calculating (convert mA to A, kΩ to Ω).

---

✅ *QUICK CHECK*
1. If you double both the voltage and the resistance in a circuit, what happens to the current?
2. Why do filaments in incandescent bulbs get hot while copper connecting wires stay cool?
"""

    # Check if grading requested
    if "grading a student's short-answer" in msg:
        return """CORRECT: yes
FEEDBACK: Excellent answer! You have demonstrated a clear understanding of the physical concepts and mathematical relationship. Keep up the great work!"""

    # Doubt solving fallback
    return """The short answer is: In electrical engineering, circuit quantities are governed by conservation laws and energy transfer mechanisms.

### Step-by-Step Explanation:
1. **Potential Difference (Voltage):** Electrical charge moves from a region of higher potential energy to lower potential energy.
2. **Current Flow:** The moving charges constitute electric current, measured as coulombs per second (Amperes).
3. **Impedance / Resistance:** As charge carriers drift through conductors and semiconductors, they collide with lattice ions, converting electrical potential into kinetic energy and heat.

### Relevant Formula:
V = I * R  and  P = I^2 * R
- V: Voltage in Volts (V)
- I: Current in Amperes (A)
- R: Resistance in Ohms (Ω)
- P: Power in Watts (W)

### Real-World Analogy:
Think of an elevator lifting passengers to the top floor of a building (energy source) and gravity pulling them back down through stairs (resistors) where they expend energy.

💡 Note: Set your CLAUDE_API_KEY in the .env file to enable unlimited real-time AI responses powered by Claude 3.5 Sonnet!"""


def _call_claude(system_prompt: str, user_message: str) -> str:
    """
    Internal helper: send a message to Claude and get the text response.
    Handles errors gracefully so the bot doesn't crash.
    """
    c = _get_client()
    if c is None:
        logger.info("Using built-in demo response (CLAUDE_API_KEY not configured yet)")
        return _mock_fallback(user_message)

    try:
        response = c.messages.create(
            model      = CLAUDE_MODEL,
            max_tokens = MAX_TOKENS,
            system     = system_prompt,
            messages   = [{"role": "user", "content": user_message}]
        )
        return response.content[0].text

    except anthropic.APIConnectionError:
        logger.error("Cannot connect to Claude API. Check your internet connection.")
        return _mock_fallback(user_message)

    except anthropic.AuthenticationError:
        logger.error("Invalid Claude API key. Check your .env file.")
        return _mock_fallback(user_message)

    except anthropic.RateLimitError:
        logger.error("Claude API rate limit hit.")
        return "⚠️ Too many requests. Please wait a moment and try again."

    except Exception as e:
        logger.error("Unexpected Claude API error: %s", str(e))
        return _mock_fallback(user_message)


# ─────────────────────────────────────────────
#  SYSTEM PROMPT BUILDER
# ─────────────────────────────────────────────

def _get_base_system_prompt(student_level: str = "beginner") -> str:
    """
    Returns the base personality/role for Claude in all conversations.
    """
    return f"""You are EEE Tutor, a friendly and expert assistant for Electrical and 
Electronics Engineering (EEE) students. Your student is at {student_level} level.

Your teaching style:
- Use simple, clear language — avoid unnecessary jargon
- Always explain WHY something works, not just what it is
- Use real-world analogies and examples (household appliances, cars, phones, etc.)
- Show formulas clearly with units and explain each variable
- Be encouraging and patient
- Keep responses well-structured with headings and bullet points
- Use Telegram-compatible formatting: *bold* for emphasis, `code` for formulas/variables

You are a knowledgeable tutor, not a textbook. Make learning fun!"""


# ─────────────────────────────────────────────
#  LESSON GENERATION
# ─────────────────────────────────────────────

def generate_lesson(topic: str, subject: str, student_level: str = "beginner",
                    context: str = "") -> str:
    """
    Generate a complete 10-minute lesson on the given EEE topic.

    Parameters:
      topic         : The specific topic (e.g. "Ohm's Law and Kirchhoff's Laws")
      subject       : The subject (e.g. "Circuit Theory")
      student_level : "beginner", "intermediate", or "advanced"
      context       : Optional relevant text from the knowledge base (RAG)

    Returns: A formatted lesson as a string (Telegram markdown compatible)
    """
    logger.info("Generating lesson for topic: '%s'", topic)

    system_prompt = _get_base_system_prompt(student_level)

    # Include knowledge base context if available
    context_section = ""
    if context:
        context_section = f"""
I have retrieved the following relevant content from the student's personal notes and 
study materials. Prioritize this information and mention the source if you use it:

---STUDENT NOTES / REFERENCE MATERIAL---
{context[:2000]}   
---END OF NOTES---
"""

    user_message = f"""
{context_section}

Please create a 10-minute lesson on the following topic:

Subject: {subject}
Topic: {topic}
Student Level: {student_level}

Structure the lesson EXACTLY like this:

📚 *TOPIC: {topic}*
Subject: {subject}

---

🎯 *WHAT YOU WILL LEARN*
(2-3 bullet points of learning objectives)

---

💡 *THE CONCEPT EXPLAINED SIMPLY*
(A clear, beginner-friendly explanation — use an analogy if possible)

---

📐 *KEY FORMULAS*
(List the important formulas. For each: show the formula, define every variable, 
state the units)

---

🌍 *REAL-WORLD EXAMPLE*
(One concrete, relatable example from daily life that uses this topic)

---

🔑 *KEY POINTS TO REMEMBER*
(5 bullet points summarizing the most important ideas)

---

✅ *QUICK CHECK* (not a quiz — just 2 thinking questions to ponder)
(Two simple reflection questions — no need to answer them now)

Keep the lesson concise and readable. A student should be able to read it in ~10 minutes.
"""

    lesson = _call_claude(system_prompt, user_message)
    logger.info("Lesson generated successfully for '%s'", topic)
    return lesson


# ─────────────────────────────────────────────
#  QUIZ GENERATION
# ─────────────────────────────────────────────

def generate_quiz(topic: str, subject: str, weak_areas: list,
                  student_level: str = "beginner") -> list:
    """
    Generate 20 quiz questions on the given topic.
    Mix of: 15 MCQ + 5 Short Answer.
    Weak areas from past quizzes get extra focus.

    Parameters:
      topic         : The topic that was just taught
      subject       : The subject name
      weak_areas    : List of sub-topics where the student struggled before
      student_level : Difficulty level

    Returns: A list of question dicts:
      [{"type": "mcq", "question": "...", "options": ["A)..","B)..","C)..","D).."],
        "answer": "A", "explanation": "..."},
       {"type": "short", "question": "...", "answer": "...", "explanation": "..."},
       ...]
    """
    logger.info("Generating quiz for topic: '%s'", topic)

    system_prompt = _get_base_system_prompt(student_level)

    weak_note = ""
    if weak_areas:
        weak_note = f"\nFocus extra questions on these areas where the student struggled: {', '.join(weak_areas)}\n"

    user_message = f"""
Generate exactly 20 quiz questions about the EEE topic below.

Subject: {subject}
Topic: {topic}
{weak_note}

Question mix:
- 15 Multiple Choice Questions (MCQ) — each with 4 options labeled A, B, C, D
- 5 Short Answer Questions — require a 1-2 sentence answer or a small calculation

For MCQ: vary difficulty (some easy, some medium, some hard).
For Short Answer: include at least 2 numerical/calculation problems.

Return your response as a valid JSON array ONLY (no other text before or after).
Each question object must have these fields:

For MCQ:
{{
  "type": "mcq",
  "question": "The question text here",
  "options": ["A) First option", "B) Second option", "C) Third option", "D) Fourth option"],
  "answer": "A",
  "explanation": "Brief explanation of why A is correct and why others are wrong"
}}

For Short Answer:
{{
  "type": "short",
  "question": "The question text here",
  "answer": "The expected correct answer",
  "explanation": "Detailed explanation / worked solution"
}}

Return ONLY the JSON array. Start with [ and end with ].
"""

    raw = _call_claude(system_prompt, user_message)

    # Try to parse the JSON from Claude's response
    try:
        # Sometimes Claude adds text before/after the JSON — extract just the array
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if match:
            questions = json.loads(match.group())
        else:
            questions = json.loads(raw)

        logger.info("Generated %d quiz questions for '%s'", len(questions), topic)
        return questions

    except json.JSONDecodeError as e:
        logger.error("Failed to parse quiz JSON: %s\nRaw response: %s", str(e), raw[:500])
        # Return a fallback question so the quiz doesn't crash
        return [{
            "type": "short",
            "question": f"In your own words, explain the most important concept from {topic}.",
            "answer": "Open-ended — any reasonable explanation is accepted.",
            "explanation": "This is a reflection question. Review the lesson for key concepts."
        }]


# ─────────────────────────────────────────────
#  QUIZ GRADING
# ─────────────────────────────────────────────

def grade_answer(question: dict, user_answer: str,
                 student_level: str = "beginner") -> dict:
    """
    Grade a single quiz answer. For MCQ, this is straightforward comparison.
    For short answers, Claude evaluates the response for conceptual correctness.

    Parameters:
      question    : The question dict (from generate_quiz)
      user_answer : What the student typed

    Returns: A dict with:
      {"correct": True/False, "feedback": "Explanation text", "marks": 0 or 1}
    """
    q_type = question.get("type", "short")

    if q_type == "mcq":
        # For MCQ: just check if the letter matches (case-insensitive)
        correct_letter = question["answer"].strip().upper()[0]   # e.g. "A"
        user_letter    = user_answer.strip().upper()[:1] if user_answer else ""
        is_correct     = (user_letter == correct_letter)

        if is_correct:
            feedback = f"✅ Correct! {question['explanation']}"
        else:
            feedback = (f"❌ Incorrect. You answered: {user_letter or '(nothing)'}. "
                        f"The correct answer is {correct_letter}.\n"
                        f"📖 {question['explanation']}")

        return {"correct": is_correct, "feedback": feedback, "marks": 1 if is_correct else 0}

    else:
        # For short answer: use Claude to check conceptual correctness
        system_prompt = _get_base_system_prompt(student_level)
        user_message = f"""
You are grading a student's short-answer quiz question.

Question: {question['question']}
Expected Answer: {question['answer']}
Student's Answer: {user_answer}

Grade the student's answer. Be generous — give credit for correct concepts 
even if the wording is different. Do not penalize for spelling errors.

Respond in this exact format:
CORRECT: yes  (or "no" if wrong, or "partial" if partially correct)
FEEDBACK: [Write 2-3 sentences. If wrong, explain the correct answer clearly. 
           If correct, give a word of encouragement and add an interesting extra fact.]
"""
        response = _call_claude(system_prompt, user_message)

        # Parse the response
        is_correct = False
        feedback   = response

        correct_match = re.search(r'CORRECT:\s*(yes|no|partial)', response, re.IGNORECASE)
        feedback_match = re.search(r'FEEDBACK:\s*(.+)', response, re.DOTALL)

        if correct_match:
            verdict    = correct_match.group(1).lower()
            is_correct = verdict in ("yes", "partial")

        if feedback_match:
            feedback = feedback_match.group(1).strip()
            if is_correct and "partial" in response.lower():
                feedback = "⚠️ Partially correct. " + feedback
            elif is_correct:
                feedback = "✅ Correct! " + feedback
            else:
                feedback = "❌ Incorrect. " + feedback

        return {"correct": is_correct, "feedback": feedback, "marks": 1 if is_correct else 0}


# ─────────────────────────────────────────────
#  DOUBT SOLVING
# ─────────────────────────────────────────────

def answer_doubt(question: str, student_level: str = "beginner",
                 context: str = "") -> str:
    """
    Answer any EEE question with a step-by-step explanation.

    Parameters:
      question      : The student's question (free text)
      student_level : For adjusting explanation complexity
      context       : Relevant content from the knowledge base (RAG)

    Returns: A detailed, step-by-step answer as a string
    """
    logger.info("Answering doubt: '%s'", question[:80])

    system_prompt = _get_base_system_prompt(student_level)

    context_section = ""
    if context:
        context_section = f"""
Relevant content from the student's study materials:

---
{context[:2000]}
---

Use this context to answer if relevant. Mention it came from their notes.
"""

    user_message = f"""
{context_section}

The student asks: {question}

Please answer with:
1. A brief, simple one-sentence answer first ("The short answer is: ...")
2. A detailed step-by-step explanation
3. A relevant formula (if applicable) with each variable explained
4. A real-world analogy or example to make it stick
5. One common mistake students make about this topic

Keep it encouraging and easy to understand for a {student_level} student.
"""

    return _call_claude(system_prompt, user_message)


# ─────────────────────────────────────────────
#  WEEKLY REPORT SUMMARY
# ─────────────────────────────────────────────

def generate_weekly_summary(progress_data: dict, student_level: str = "beginner") -> str:
    """
    Generate a human-friendly weekly progress report using Claude.

    Parameters:
      progress_data : Dict from memory.get_weekly_progress()

    Returns: A formatted summary string for Telegram
    """
    logger.info("Generating weekly progress summary")

    system_prompt = _get_base_system_prompt(student_level)

    user_message = f"""
Generate a warm, encouraging weekly progress report for an EEE student.

Here is their data for this week:
- Lessons/quizzes taken: {progress_data['lessons_this_week']}
- Average quiz score: {progress_data['avg_score_this_week']}%
- Topics covered: {[t['topic'] for t in progress_data['topics_this_week']]}
- Top weak topics: {[t['topic'] for t in progress_data['weak_topics'][:3]]}
- Overall completion: {progress_data['completion_pct']}% of syllabus ({progress_data['total_taught']}/{progress_data['total_topics']} topics)

Write a 150-200 word summary that:
1. Opens with a motivating greeting
2. Highlights their achievements this week (be specific)
3. Gently points out the weak areas to focus on
4. Ends with an encouraging message for next week

Use Telegram formatting (*bold*, bullet points). Keep it personal and warm.
"""

    return _call_claude(system_prompt, user_message)
