import csv
import os
import glob
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, Response
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import mysql.connector
from starlette.middleware.sessions import SessionMiddleware
from datetime import datetime
import time
import shutil
from uw_llm import *

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="verysecretkey")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

DB_CONFIG = {
    'user': 'mstachow',
    'password': 'mitadp560',
    'host': 'localhost',
    'database': 'assignmentsdb',
}

grade_mode = "offline"

def get_db():
    conn = mysql.connector.connect(**DB_CONFIG)
    return conn

def load_users():
    users = {}
    with open("users.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            users[row["username"]] = row["password"]
    return users


def autograde(answer: str, question_path: str, rubric_path: str, username: str, assignment: str, question_id: str):
    # Load question and rubric text
    question = ""
    rubric = ""
    if os.path.exists(question_path):
        with open(question_path) as f:
            question = f.read()
    if os.path.exists(rubric_path):
        with open(rubric_path) as f:
            rubric = f.read()

    if grade_mode != "offline":
        prompt = f"""
            You are a helpful teaching assistant. You are providing feedback to students. The question they were asked is: {question}.
            
            The rubric is: {rubric}
            
            The student answer is: {answer}
            
            Use the rubric to provide feedback on the student work. First, you must output the exact string "meets expectations" or "does not meet expectations", then provide brief feedback to the student.
        """
        response = generate(prompt)
        grade = 1 if "meets expectations" in response.lower() else 0
        return grade, response
    else:
        # Generate markdown input for offline grader
        filename = f"{username}_{assignment}_{question_id}.txt"
        final_path = os.path.join("to_grade", filename)
        if os.path.exists(final_path):
            return None, None, True  # Already queued
        temp_path = os.path.join("/tmp", filename)
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(f"# username\n{username}\n")
            f.write(f"# assignment\n{assignment}\n")
            f.write(f"# question\n{question_id}\n")
            f.write(f"# question_text\n{question}\n")
            f.write(f"# rubric\n{rubric}\n")
            f.write(f"# answer\n{answer}\n")
        shutil.move(temp_path, final_path)
        return None, None, False  # Successfully queued



@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    if request.session.get("user"):
        return RedirectResponse(url="/assignments")
    return RedirectResponse(url="/login")

@app.get("/login", response_class=HTMLResponse)
def login_get(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": ""})

@app.post("/login", response_class=HTMLResponse)
def login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    users = load_users()
    if users.get(username) == password:
        request.session["user"] = username
        return RedirectResponse(url="/assignments", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid credentials"})

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login")

@app.get("/assignments", response_class=HTMLResponse)
def assignments(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/login")
    assignment_dirs = [d for d in os.listdir("assignments") if os.path.isdir(os.path.join("assignments", d))]
    return templates.TemplateResponse("assignments.html", {"request": request, "assignments": assignment_dirs})

@app.get("/assignment/{assignment}", response_class=HTMLResponse)
def assignment_page(request: Request, assignment: str):
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/login")
    path = f"assignments/{assignment}/"
    questions = []
    for f in sorted(glob.glob(os.path.join(path, "*.txt"))):
        base = os.path.basename(f)
        if not base.startswith("q") or not base.endswith(".txt"):
            continue
        with open(f) as qf:
            text = qf.read()
            q_id = os.path.splitext(base)[0]
            if text.startswith("## Question:"):
                qtext = text.split("## Question:")[1].strip()
                question_path = f
                rubric_path = os.path.join(path, f"rubric_{q_id}.txt")
                questions.append({
                    "id": q_id,
                    "text": qtext,
                    "question_path": question_path,
                    "rubric_path": rubric_path
                })

    # Load saved answers, grades, feedback
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    answers = {}
    for q in questions:
        cursor.execute(
            "SELECT answer, grade, feedback FROM answers WHERE username=%s AND assignment=%s AND question=%s ORDER BY timestamp DESC LIMIT 1",
            (user, assignment, q["id"])
        )
        row = cursor.fetchone()
        if row:
            answers[q["id"]] = {"answer": row["answer"], "grade": row["grade"], "feedback": row["feedback"]}
    cursor.close()
    conn.close()
    return templates.TemplateResponse("assignment.html", {
        "request": request,
        "assignment": assignment,
        "questions": questions,
        "answers": answers,
        "user": user
    })

@app.post("/submit")
async def submit(request: Request, assignment: str = Form(...), question: str = Form(...), answer: str = Form(...)):
    user = request.session.get("user")
    if not user:
        return JSONResponse({"error": "Not logged in"}, status_code=401)
    path = f"assignments/{assignment}/"
    question_path = os.path.join(path, f"{question}.txt")
    rubric_path = os.path.join(path, f"rubric_{question}.txt")

    if grade_mode != "offline":
        grade, feedback, _ = autograde(answer, question_path, rubric_path, user, assignment, question)
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO answers (username, assignment, question, answer, grade, feedback) VALUES (%s,%s,%s,%s,%s,%s)",
            (user, assignment, question, answer, grade, feedback)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return JSONResponse({"feedback": feedback, "grade": grade})
    else:
        grade, feedback, already_queued = autograde(answer, question_path, rubric_path, user, assignment, question)
        if already_queued:
            msg = "Your question is already in the queue. Please wait for the email response before attempting to submit again."
            return JSONResponse({"message": msg})
        else:
            msg = "Your request has been submitted and is in the queue. Check your email for feedback. You may safely continue working on this assignment."
            return JSONResponse({"message": msg})
