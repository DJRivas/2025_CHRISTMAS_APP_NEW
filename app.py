import os, uuid, sqlite3, json
from flask import Flask, render_template, request, jsonify, g, make_response, redirect, url_for, session

DATABASE = os.environ.get("DATABASE_URL", "ratings.db")
SECRET_KEY = os.environ.get("SECRET_KEY", "santa-secret-key")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Julian")
DATA_FILE = os.environ.get("DATA_PATH", "bakers.json")

# Default Entrants
DEFAULT_ENTRANTS = ["Javier", "Lindsay", "Yesenia", "Bryan", "Daniella", "Rogelio", "Viviana", "Martha", "Bernie"]

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = SECRET_KEY

# --- Persistence for Baker Names ---
def load_entrants():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                return json.load(f)
        except: pass
    return DEFAULT_ENTRANTS

def save_entrants(names):
    with open(DATA_FILE, 'w') as f:
        json.dump(names, f)

# --- Database ---
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
            taste INTEGER NOT NULL,
            presentation INTEGER NOT NULL,
            spirit INTEGER NOT NULL,
            judge TEXT,
            device_id TEXT,
            one_word TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (entrant_index, device_id)
        )
    """)
    db.commit()

with app.app_context():
    init_db()

# --- Routes ---
@app.route("/")
def home():
    entrants = load_entrants()
    resp = make_response(render_template("index.html", entrants=entrants, title="2025 Holiday Baking"))
    if not request.cookies.get("device_id"):
        resp.set_cookie("device_id", str(uuid.uuid4()), max_age=60*60*24*365)
    return resp

@app.route("/words")
def words_page():
    return render_template("words.html", title="One Word Results")

@app.route("/api/rate", methods=["POST"])
def api_rate():
    data = request.get_json(silent=True) or {}
    try:
        entrant_index = int(data.get("entrant_index"))
        taste = int(data.get("taste"))
        presentation = int(data.get("presentation"))
        spirit = int(data.get("spirit"))
        judge = (data.get("judge") or "").strip()[:50]
        one_word = (data.get("one_word") or "").strip().split()[0][:20]
    except: return jsonify({"ok": False}), 400

    entrants = load_entrants()
    if not (0 <= entrant_index < len(entrants)): return jsonify({"ok": False}), 400

    db = get_db()
    db.execute(
        """INSERT INTO ratings (entrant_index, taste, presentation, spirit, judge, device_id, one_word)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(entrant_index, device_id) DO UPDATE SET
            taste=excluded.taste, presentation=excluded.presentation, spirit=excluded.spirit,
            judge=excluded.judge, one_word=excluded.one_word
        """,
        (entrant_index, taste, presentation, spirit, judge, request.cookies.get("device_id"), one_word)
    )
    db.commit()
    return jsonify({"ok": True})

@app.route("/api/leaderboard")
def api_leaderboard():
    entrants = load_entrants()
    db = get_db()
    rows = db.execute("""
        SELECT entrant_index, COUNT(*) as votes,
               AVG(taste) as t, AVG(presentation) as p, AVG(spirit) as s
        FROM ratings GROUP BY entrant_index
    """).fetchall()
    
    results = []
    for r in rows:
        idx = r["entrant_index"]
        if idx < len(entrants):
            avg_total = (r["t"] + r["p"] + r["s"]) / 3.0
            results.append({
                "name": entrants[idx],
                "votes": r["votes"],
                "avg_total": round(avg_total, 2)
            })
    
    results.sort(key=lambda x: x["avg_total"], reverse=True)
    return jsonify(results)

@app.route("/api/words")
def api_words():
    entrants = load_entrants()
    db = get_db()
    rows = db.execute("SELECT entrant_index, LOWER(one_word) as w, COUNT(*) as c FROM ratings WHERE one_word != '' GROUP BY entrant_index, LOWER(one_word) ORDER BY c DESC").fetchall()
    out = {}
    for r in rows:
        idx = r["entrant_index"]
        if idx < len(entrants):
            out.setdefault(entrants[idx], []).append({"word": r["w"], "count": r["c"]})
    return jsonify(out)

# --- Admin ---
@app.route("/admin", methods=["GET", "POST"])
def admin():
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["is_admin"] = True
            return redirect(url_for("admin"))
        return render_template("admin_login.html", error="Incorrect Password")

    if not session.get("is_admin"):
        return render_template("admin_login.html")

    entrants = load_entrants()
    return render_template("admin_dashboard.html", entrants=entrants)

@app.route("/admin/update_names", methods=["POST"])
def update_names():
    if not session.get("is_admin"): return redirect(url_for("admin"))
    new_names = request.form.getlist("names")
    save_entrants(new_names)
    return redirect(url_for("admin"))

@app.route("/admin/reset", methods=["POST"])
def reset_game():
    if not session.get("is_admin"): return redirect(url_for("admin"))
    db = get_db()
    db.execute("DELETE FROM ratings")
    db.commit()
    return redirect(url_for("admin"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
