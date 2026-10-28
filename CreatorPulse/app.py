import json
import os
import random
import re
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template, request, session

app = Flask(__name__, template_folder=".")
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
)

BASE_DIR = Path(__file__).resolve().parent
USERS_FILE = BASE_DIR / "users.json"
ACTIVITY_FILE = BASE_DIR / "activity.json"
DATA_LOCK = threading.RLock()

DEMO_USERS = {
    "demo_creator": {
        "points": 100,
        "video_id": "dQw4w9WgXcQ",
        "keyword": "Python Basics",
        "handle": "@demo_creator",
    },
    "tech_studio": {
        "points": 100,
        "video_id": "M7lc1UVf-VE",
        "keyword": "Web Development Tutorial",
        "handle": "@tech_studio",
    },
    "learn_coding": {
        "points": 100,
        "video_id": "kqtD5dpn9C8",
        "keyword": "Learn Python Programming",
        "handle": "@learn_coding",
    },
}


def initialize_json_file(path, initial_data):
    if not path.exists():
        temporary_path = path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(initial_data, indent=2),
            encoding="utf-8",
        )
        try:
            temporary_path.replace(path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()


def load_users():
    initialize_json_file(USERS_FILE, DEMO_USERS)
    with USERS_FILE.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError("users.json must contain a JSON object.")
    return data


def save_users(users):
    temporary_path = USERS_FILE.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(users, indent=2),
        encoding="utf-8",
    )
    temporary_path.replace(USERS_FILE)


def load_activity():
    initialize_json_file(ACTIVITY_FILE, [])
    with ACTIVITY_FILE.open("r", encoding="utf-8") as file:
        data = json.load(file)
    return data if isinstance(data, list) else []


def log_activity(message, kind="info"):
    with DATA_LOCK:
        activity = load_activity()
        activity.insert(
            0,
            {
                "message": str(message)[:240],
                "kind": kind,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
        activity = activity[:100]
        temporary_path = ACTIVITY_FILE.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(activity, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(ACTIVITY_FILE)


def public_user(username, user):
    return {
        "username": username,
        "handle": user.get("handle", f"@{username}"),
        "points": int(user.get("points", 0)),
        "keyword": user.get("keyword", "Creator channel audit"),
        "video_id": user.get("video_id", ""),
    }


def validate_audit(worker, creator, proof):
    """Validate a creator-channel audit submission.

    This starter validator checks required audit evidence and identity.
    It does not claim to verify YouTube views, watch time, or screenshots.
    A production deployment should replace this with authenticated,
    human-reviewed audit evidence or a trusted verification integration.
    """
    if not isinstance(proof, str):
        return False, "Provide written audit evidence."

    evidence = proof.strip()
    if len(evidence) < 20:
        return False, "Describe your audit findings in at least 20 characters."

    if worker == creator:
        return False, "You cannot audit your own account."

    return True, "Audit evidence accepted for this demo."


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/register")
def register():
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username", "")).strip().lower()
    handle = str(payload.get("handle", "")).strip()

    if not re.fullmatch(r"[a-z0-9_]{3,24}", username):
        return jsonify(
            error="Username must be 3–24 characters using letters, numbers, or underscores."
        ), 400

    if not re.fullmatch(r"@[A-Za-z0-9_.-]{1,50}", handle):
        return jsonify(
            error="Enter a valid YouTube handle, such as @yourchannel."
        ), 400

    with DATA_LOCK:
        users = load_users()
        if username in users:
            return jsonify(error="That username already exists."), 409

        users[username] = {
            "points": 10,
            "video_id": "",
            "keyword": "Creator channel audit",
            "handle": handle,
        }
        save_users(users)

    session.clear()
    session["username"] = username
    log_activity(f"{handle} joined CreatorPulse Engine.", "success")

    return jsonify(
        message="Account created successfully.",
        user=public_user(username, users[username]),
    ), 201


@app.get("/api/me")
def me():
    username = session.get("username")
    if not username:
        return jsonify(user=None)

    with DATA_LOCK:
        users = load_users()
        user = users.get(username)
        if user is None:
            session.clear()
            return jsonify(user=None)

        return jsonify(user=public_user(username, user))


@app.post("/api/demo-login")
def demo_login():
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username", "")).strip().lower()

    with DATA_LOCK:
        users = load_users()
        if username not in users:
            return jsonify(error="Demo account not found."), 404

        session.clear()
        session["username"] = username
        return jsonify(
            message="Demo session started.",
            user=public_user(username, users[username]),
        )


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(message="Signed out.")


@app.get("/api/get-task")
def get_task():
    current_username = session.get("username")

    with DATA_LOCK:
        users = load_users()
        candidates = [
            (username, user)
            for username, user in users.items()
            if username != current_username
            and user.get("handle")
        ]

        if not candidates:
            return jsonify(error="No other creators are available yet."), 404

        creator, user = random.choice(candidates)
        handle = user.get("handle", f"@{creator}")
        video_id = user.get("video_id", "")

        return jsonify(
            task={
                "creator": creator,
                "handle": handle,
                "keyword": user.get("keyword", "Creator channel audit"),
                "thumbnail_hint": (
                    f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
                    if video_id
                    else None
                ),
                "video_url": (
                    f"https://www.youtube.com/watch?v={video_id}"
                    if video_id
                    else None
                ),
                "instructions": (
                    "Open the public channel, review its visible title and "
                    "description, and submit a concise written audit. "
                    "Do not exchange views or watch time for points."
                ),
            }
        )


@app.post("/api/verify-task")
def verify_task():
    payload = request.get_json(silent=True) or {}
    worker = str(payload.get("worker", "")).strip().lower()
    creator = str(payload.get("creator", "")).strip().lower()
    proof = payload.get("proof", "")

    logged_in_user = session.get("username")
    if not logged_in_user:
        return jsonify(error="Sign in before submitting an audit."), 401

    if worker != logged_in_user:
        return jsonify(error="Worker must match your signed-in account."), 403

    valid, reason = validate_audit(worker, creator, proof)
    if not valid:
        return jsonify(error=reason), 400

    with DATA_LOCK:
        users = load_users()

        if worker not in users or creator not in users:
            return jsonify(error="Worker or creator account was not found."), 404

        if worker == creator:
            return jsonify(error="Self-audits are not permitted."), 400

        if int(users[creator].get("points", 0)) < 5:
            return jsonify(error="The creator does not have enough points."), 400

        users[worker]["points"] = int(users[worker].get("points", 0)) + 5
        users[creator]["points"] = int(users[creator].get("points", 0)) - 5
        save_users(users)

        worker_points = users[worker]["points"]
        creator_points = users[creator]["points"]

    log_activity(
        f"Creator audit accepted: {worker} reviewed {creator}. "
        "5 points transferred.",
        "success",
    )

    return jsonify(
        message="Audit accepted. Five points were transferred.",
        worker_points=worker_points,
        creator_points=creator_points,
    )


@app.get("/api/activity")
def get_activity():
    with DATA_LOCK:
        return jsonify(activity=load_activity()[:30])


@app.get("/api/stats")
def stats():
    with DATA_LOCK:
        users = load_users()
        activity = load_activity()
        return jsonify(
            total_creators=len(users),
            audits_logged=sum(
                1 for item in activity
                if "Creator audit accepted:" in item.get("message", "")
            ),
            recent_events=len(activity),
        )


initialize_json_file(USERS_FILE, DEMO_USERS)
initialize_json_file(ACTIVITY_FILE, [])

if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "5000")),
        debug=False,
    )