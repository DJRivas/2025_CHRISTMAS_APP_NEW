import os, uuid, sqlite3
from flask import Flask, render_template, request, jsonify, g, Response, make_response, redirect, url_for, session

DATABASE = os.environ.get("DATABASE_URL", "ratings.db")
SECRET_KEY = os.environ.get("SECRET_KEY", "santa-secret-key")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Julian")

# Participants
ENTRANTS = ["Javier", "Lindsay", "Yesenia", "Bryan", "Daniella", "Rogelio", "Viviana", "Martha", "Bernie"]

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = SECRET_KEY

def get_db():
    db = getattr(g, "_db", None)
    if db is None:
        db = g._db = sqlite3.connect(DATABASE, check_same_thread=False)
        db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    db.execute("""
        CREATE TABLE IF NOT EXISTS ratings(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entrant_index INTEGER NOT NULL,
            taste INTEGER NOT NULL CHECK(taste BETWEEN 1 AND 5),
            presentation INTEGER NOT NULL CHECK(presentation BETWEEN 1 AND 5),
            spirit INTEGER NOT NULL CHECK(spirit BETWEEN 1 AND 5),
            judge TEXT,
            device_id TEXT,
            one_word TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (entrant_index, device_id)
        )
    """)
    db.commit()

@app.teardown_appcontext
def close_db(exception):
    db = getattr(g, "_db", None)
    if db is not None:
        db.close()

with app.app_context():
    init_db()

def device_id_from_request():
    return request.cookies.get("device_id") or "anon"

@app.route("/")
def home():
    resp = make_response(render_template("index.html", entrants=ENTRANTS, title="2025 Holiday Baking Competition"))
    if not request.cookies.get("device_id"):
        resp.set_cookie("device_id", str(uuid.uuid4()), max_age=60*60*24*365, samesite="Lax")
    return resp

@app.route("/words")
def words_page():
    return render_template("words.html", entrants=ENTRANTS, title="One Word Results")

@app.route("/api/rate", methods=["POST"])
def api_rate():
    data = request.get_json(silent=True) or {}
    try:
        entrant_index = int(data.get("entrant_index"))
        taste = int(data.get("taste"))
        presentation = int(data.get("presentation"))
        spirit = int(data.get("spirit"))
        judge = (data.get("judge") or "").strip()[:50] or None
        one_word = (data.get("one_word") or "").strip().split()[0][:20] if data.get("one_word") else None
    except Exception:
        return jsonify({"ok": False, "error": "Invalid payload"}), 400

    if not (0 <= entrant_index < len(ENTRANTS)):
        return jsonify({"ok": False, "error": "Invalid entrant"}), 400

    device_id = device_id_from_request()
    db = get_db()
    db.execute(
        """
        INSERT INTO ratings (entrant_index, taste, presentation, spirit, judge, device_id, one_word)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(entrant_index, device_id) DO UPDATE SET
            taste=excluded.taste,
            presentation=excluded.presentation,
            spirit=excluded.spirit,
            judge=excluded.judge,
            one_word=excluded.one_word
        """,
        (entrant_index, taste, presentation, spirit, judge, device_id, one_word),
    )
    db.commit()
    return jsonify({"ok": True})

@app.route("/api/my-rating")
def api_my_rating():
    try: entrant_index = int(request.args.get("entrant_index", "-1"))
    except: return jsonify({"ok": False}), 400
    
    if not (0 <= entrant_index < len(ENTRANTS)): return jsonify({"ok": True, "rating": None})

    db = get_db()
    row = db.execute("SELECT taste, presentation, spirit, judge, one_word FROM ratings WHERE entrant_index=? AND device_id=?", 
                     (entrant_index, device_id_from_request())).fetchone()
    return jsonify({"ok": True, "rating": dict(row) if row else None})

@app.route("/api/leaderboard")
def api_leaderboard():
    db = get_db()
    rows = db.execute("""
        SELECT entrant_index, COUNT(*) AS votes,
               AVG(taste) AS avg_taste, AVG(presentation) AS avg_presentation, AVG(spirit) AS avg_spirit,
               AVG(taste + presentation + spirit) AS avg_total
        FROM ratings GROUP BY entrant_index ORDER BY avg_total DESC
    """).fetchall()
    out = [{
        "name": ENTRANTS[r["entrant_index"]],
        "votes": r["votes"],
        "avg_taste": round(r["avg_taste"] or 0, 1),
        "avg_presentation": round(r["avg_presentation"] or 0, 1),
        "avg_spirit": round(r["avg_spirit"] or 0, 1),
        "avg_total": round(r["avg_total"] or 0, 2),
    } for r in rows]
    return jsonify(out)

@app.route("/api/words")
def api_words():
    db = get_db()
    rows = db.execute("SELECT entrant_index, LOWER(TRIM(one_word)) AS w, COUNT(*) AS c FROM ratings WHERE one_word IS NOT NULL AND TRIM(one_word) != '' GROUP BY entrant_index, LOWER(TRIM(one_word)) ORDER BY c DESC").fetchall()
    out = {}
    for r in rows:
        out.setdefault(ENTRANTS[r["entrant_index"]], []).append({"word": r["w"], "count": r["c"]})
    return jsonify(out)

@app.route("/admin", methods=["GET", "POST"])
def admin():
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["is_admin"] = True
            return redirect(url_for("admin"))
        return render_template("admin_login.html", error="Incorrect password")
    if not session.get("is_admin"):
        return render_template("admin_login.html")

    db = get_db()
    rows = db.execute("SELECT * FROM ratings ORDER BY created_at DESC").fetchall()
    detailed = [{
        "entrant": ENTRANTS[r["entrant_index"]],
        "taste": r["taste"], "presentation": r["presentation"], "spirit": r["spirit"],
        "total": r["taste"] + r["presentation"] + r["spirit"],
        "judge": r["judge"], "one_word": r["one_word"]
    } for r in rows]
    
    return render_template("admin_results.html", detailed=detailed, title="Admin Results")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
