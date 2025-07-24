import os
import time
import re
import mysql.connector
import smtplib
import os

# --- CONFIGURATION ---

FOLDER = "to_grade"
DB_CONFIG = {
    'user': 'mstachow',
    'password': 'mitadp560',
    'host': 'localhost',
    'database': 'assignmentsdb',
}

from uw_llm import generate


def _to_ascii(s):
    # Remove or replace non-ascii characters
    # Here, replace with '?' (could also use '' to just drop them)
    return s.encode('ascii', errors='ignore').decode('ascii')

def send_email(username, subject, feedback):
    PASSWORD = os.environ["UWATERLOO_EMAIL_PASS"]
    FROM = "mstachow@uwaterloo.ca"
    TO = [f"{username}@uwaterloo.ca"]

    # Clean subject and feedback
    subject_clean = _to_ascii(subject)
    feedback_clean = _to_ascii(feedback)

    message = f"To: {', '.join(TO)}\nSubject: {subject_clean}\n\n{feedback_clean}"

    server = smtplib.SMTP('smtp.uwaterloo.ca', 587)
    server.ehlo()
    server.starttls()
    server.login(FROM, PASSWORD)
    server.sendmail(FROM, TO, message)
    server.quit()

def autograde(answer: str, question: str, rubric: str):
    prompt = f"""
        You are a helpful teaching assistant. You are providing feedback to students. The question they were asked is: {question}.
        
        The rubric is: {rubric}
        
        The student answer is: {answer}
        
        Use the rubric to provide feedback on the student work. First, you must output the exact string "meets expectations" or "does not meet expectations". If the answer does not meet expectations, then provide brief feedback to the student. Your feedback must never reveal any specific things about the assessment criteria. Instead, you must ask 1-2 probing questions and guide the student to revise and deepen their work. If the answer does meet expectations, simply provide some positive feedback on what you liked about the answer.
    """
    response = generate(prompt,reasoning=True)
    grade = 1 if "meets expectations" in response.lower() else 0
    return grade, response

def get_db():
    return mysql.connector.connect(**DB_CONFIG)

FIELD_NAMES = ["username", "assignment", "question", "question_text","rubric", "answer"]

def parse_markdown_fields(text):
    pattern = r'^# (\w+)\s*$([\s\S]*?)(?=^# |\Z)'
    fields = {}
    for match in re.finditer(pattern, text, flags=re.MULTILINE):
        key = match.group(1).strip().lower()
        value = match.group(2).strip()
        fields[key] = value
    missing = [f for f in FIELD_NAMES if f not in fields]
    if missing:
        raise ValueError(f"Missing fields: {missing}")
    return [fields[name] for name in FIELD_NAMES]

def process_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        username, assignment, question, question_text, rubric, answer = parse_markdown_fields(content)
        grade, feedback = autograde(answer, question_text, rubric)
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO answers (username, assignment, question, answer, grade, feedback) VALUES (%s,%s,%s,%s,%s,%s)",
            (username, assignment, question, answer, grade, feedback)
        )
        conn.commit()
        cursor.close()
        conn.close()
        
        # Now send the email
        subject = f"Your feedback for {assignment}, {question}"
        body = f"Your grade for this question is {grade}. Your feedback is: {feedback}"
        send_email(username,subject,body)
        
        print(f"Processed {os.path.basename(path)}: {grade}, {feedback[:60]}...")
    except Exception as e:
        print(f"Error processing {path}: {e}")
    finally:
        os.remove(path)

def main():
    if not os.path.isdir(FOLDER):
        os.makedirs(FOLDER)
    print(f"Monitoring folder: {FOLDER}")
    while True:
        files = [f for f in os.listdir(FOLDER) if f.endswith(".txt")]
        if files:
            for filename in files:
                path = os.path.join(FOLDER, filename)
                process_file(path)
        else:
            time.sleep(5)

if __name__ == "__main__":
    main()
