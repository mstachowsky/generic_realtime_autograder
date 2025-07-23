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

def autograde(answer: str, question_path: str, rubric_path: str):
    # Example: load both files
    
    question = ""
    rubric = ""
    if os.path.exists(question_path):
        with open(question_path) as f:
            question = f.read()
    if os.path.exists(rubric_path):
        with open(rubric_path) as f:
            rubric = f.read()
    
    prompt = f"""
        You are a helpful teaching assistant. You are providing feedback to students. The question they were asked is: {question}.
        
        The rubric is: {rubric}
        
        The student answer is: {answer}
        
        Use the rubric to provide feedback on the student work. First, you must output the exact string "meets expectations" or "does not meet expectations", then provide brief feedback to the student.
    """
    
    response = generate(prompt)
    grade = 0
    if "meets expectations" in response.lower():
        grade = 1
    
    # Example: feedback includes both
    return grade, response



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
        # AJAX: send error JSON, not redirect
        return JSONResponse({"error": "Not logged in"}, status_code=401)
    path = f"assignments/{assignment}/"
    question_path = os.path.join(path, f"{question}.txt")
    rubric_path = os.path.join(path, f"rubric_{question}.txt")
    grade, feedback = autograde(answer, question_path, rubric_path)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO answers (username, assignment, question, answer, grade, feedback) VALUES (%s,%s,%s,%s,%s,%s)",
        (user, assignment, question, answer, grade, feedback)
    )
    conn.commit()
    cursor.close()
    conn.close()
    # AJAX: return JSON for the frontend JS
    return JSONResponse({"feedback": feedback, "grade": grade})
