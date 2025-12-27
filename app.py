import os, uuid, sqlite3, json
from flask import Flask, render_template, request, jsonify, g, make_response, redirect, url_for, session

# We use a new table name to avoid conflicts with the old 1-5 constraint
TABLE_NAME = "ratings_v2"
DATABASE = os.environ.get("DATABASE_URL", "ratings.db")
SECRET_KEY = os.environ.get("SECRET_KEY", "santa-secret-key")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Julian")
DATA_FILE = os.environ.get("DATA_PATH", "bakers.json")

DEFAULT_ENTRANTS = ["Javier", "Lindsay", "Yesenia", "Bryan", "Daniella", "Rogelio", "Viviana", "Martha", "Bernie"]

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = SECRET_KEY

def load_entrants():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                return json.load(f)
        except: pass
    return DEFAULT_ENTRANTS

def save_entrants(names):
    # Filter out empty lines
    clean_names = [n.strip() for n in names if n.strip()]
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(clean_names, f)
    except Exception as e:
        print(f"Error saving entrants: {e}")

def get_db():
    db = getattr(g, "_db", None)
    if db is None:
        db = g._db = sqlite3.connect(DATABASE, check_same_thread=False, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL;')
    return db

def init_db():
    with app.app_context():
        db = get_db()
        # Create new table with 1-10 constraint
        db.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_NAME}(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entrant_index INTEGER NOT NULL,
                taste INTEGER NOT NULL CHECK(taste BETWEEN 1 AND 10),
                presentation INTEGER NOT NULL CHECK(presentation BETWEEN 1 AND 10),
                spirit INTEGER NOT NULL CHECK(spirit BETWEEN 1 AND 10),
                judge TEXT,
                device_id TEXT,
                one_word TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (entrant_index, device_id)
            )
        """)
        db.commit()

init_db()

@app.route("/")
def home():
    resp = make_response(render_template("index.html", entrants=load_entrants(), title="2025 Holiday Baking"))
    if not request.cookies.get("device_id"):
        resp.set_cookie("device_id", str(uuid.uuid4()), max_age=60*60*24*365)
    return resp

@app.route("/words")
def words_page():
    return render_template("words.html", title="Word Cloud")

@app.route("/api/rate", methods=["POST"])
def api_rate():
    data = request.get_json(silent=True) or {}
    try:
        idx = int(data.get("entrant_index"))
        t = int(data.get("taste"))
        p = int(data.get("presentation"))
        s = int(data.get("spirit"))
        judge = (data.get("judge") or "").strip()[:50]
        one_word = (data.get("one_word") or "").strip().split()[0][:20]
        device_id = request.cookies.get("device_id")
        
        # Validation
        if not (1 <= t <= 10 and 1 <= p <= 10 and 1 <= s <= 10):
            return jsonify({"ok": False, "error": "Ratings must be 1-10"}), 400
    except Exception as e: 
        return jsonify({"ok": False, "error": "Bad data"}), 400

    if not (0 <= idx < len(load_entrants())): return jsonify({"ok": False}), 400

    try:
        db = get_db()
        db.execute(
            f"""INSERT INTO {TABLE_NAME} (entrant_index, taste, presentation, spirit, judge, device_id, one_word)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(entrant_index, device_id) DO UPDATE SET
                taste=excluded.taste, presentation=excluded.presentation, spirit=excluded.spirit,
                judge=excluded.judge, one_word=excluded.one_word
            """,
            (idx, t, p, s, judge, device_id, one_word)
        )
        db.commit()
        return jsonify({"ok": True})
    except Exception as e:
        print(f"DB Error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/leaderboard")
def api_leaderboard():
    try:
        entrants = load_entrants()
        db = get_db()
        rows = db.execute(f"""
            SELECT entrant_index, COUNT(*) as votes,
                   AVG(taste*1.0) as t, AVG(presentation*1.0) as p, AVG(spirit*1.0) as s
            FROM {TABLE_NAME} GROUP BY entrant_index
        """).fetchall()
        
        results = []
        for r in rows:
            idx = r["entrant_index"]
            if idx < len(entrants):
                avg_total = (r["t"] + r["p"] + r["s"]) / 3.0
                results.append({
                    "name": entrants[idx],
                    "votes": r["votes"],
                    "avg_t": round(r["t"], 1),
                    "avg_p": round(r["p"], 1),
                    "avg_s": round(r["s"], 1),
                    "avg_total": round(avg_total, 2)
                })
        
        results.sort(key=lambda x: x["avg_total"], reverse=True)
        return jsonify(results)
    except: return jsonify([])

@app.route("/api/words")
def api_words():
    entrants = load_entrants()
    db = get_db()
    rows = db.execute(f"SELECT entrant_index, LOWER(one_word) as w, COUNT(*) as c FROM {TABLE_NAME} WHERE one_word != '' GROUP BY entrant_index, LOWER(one_word) ORDER BY c DESC").fetchall()
    out = {}
    for r in rows:
        idx = r["entrant_index"]
        if idx < len(entrants):
            out.setdefault(entrants[idx], []).append({"word": r["w"], "count": r["c"]})
    return jsonify(out)

@app.route("/admin", methods=["GET", "POST"])
def admin():
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["is_admin"] = True
            return redirect(url_for("admin"))
        return render_template("admin_login.html", error="Bad Password")
    if not session.get("is_admin"): return render_template("admin_login.html")
    
    # Pass entrants as a string for the textarea
    entrants_str = "\n".join(load_entrants())
    return render_template("admin_dashboard.html", entrants_str=entrants_str)

@app.route("/admin/update_names", methods=["POST"])
def update_names():
    if not session.get("is_admin"): return redirect(url_for("admin"))
    # Split textarea by lines
    raw_text = request.form.get("names_block", "")
    new_names = raw_text.splitlines()
    save_entrants(new_names)
    return redirect(url_for("admin"))

@app.route("/admin/reset", methods=["POST"])
def reset_game():
    if not session.get("is_admin"): return redirect(url_for("admin"))
    db = get_db()
    db.execute(f"DELETE FROM {TABLE_NAME}")
    db.commit()
    return redirect(url_for("admin"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
