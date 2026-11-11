import os, sqlite3
from datetime import date, timedelta
from flask import Flask, g, jsonify, request, send_from_directory
try:
    from flask_cors import CORS
except ImportError:
    CORS = lambda app: None
from yield_client import predict_yield, check_inputs
from risk import assess_risk

app = Flask(__name__, static_folder="static")
CORS(app)
DB_PATH = os.environ.get("DB_PATH", "fpo.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS farmers(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, village TEXT,
  phone TEXT, reliability_score REAL DEFAULT 0.8);
CREATE TABLE IF NOT EXISTS crops(
  id INTEGER PRIMARY KEY AUTOINCREMENT, farmer_id INTEGER, crop_type TEXT NOT NULL,
  area_acres REAL NOT NULL, soil TEXT DEFAULT 'loamy', irrigation TEXT DEFAULT 'canal',
  sowing_date TEXT NOT NULL, expected_harvest_date TEXT, status TEXT DEFAULT 'growing');
CREATE TABLE IF NOT EXISTS harvests(
  id INTEGER PRIMARY KEY AUTOINCREMENT, crop_id INTEGER, actual_date TEXT,
  quantity_kg REAL, quality_grade TEXT);
CREATE TABLE IF NOT EXISTS buyer_orders(
  id INTEGER PRIMARY KEY AUTOINCREMENT, buyer_name TEXT NOT NULL, crop_type TEXT NOT NULL,
  quantity_kg REAL NOT NULL, due_date TEXT NOT NULL, min_quality TEXT DEFAULT 'B',
  status TEXT DEFAULT 'open', buyer_phone TEXT, delivery_location TEXT);
CREATE TABLE IF NOT EXISTS predictions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, crop_id INTEGER, predicted_yield_kg REAL,
  predicted_harvest_date TEXT, harvest_days INTEGER, risk_score REAL,
  recommendation TEXT, source TEXT, created_at TEXT DEFAULT (datetime('now')));
"""

TABLES = {  # url name -> (table, allowed columns)
    "farmers": ("farmers", ["name", "village", "phone", "reliability_score"]),
    "crops": ("crops", ["farmer_id", "crop_type", "area_acres", "soil", "irrigation",
                        "sowing_date", "expected_harvest_date", "status"]),
    "harvests": ("harvests", ["crop_id", "actual_date", "quantity_kg", "quality_grade"]),
    "orders": ("buyer_orders", ["buyer_name", "crop_type", "quantity_kg", "due_date",
                                "min_quality", "status", "buyer_phone", "delivery_location"]),
}


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d:
        d.close()


def init_db():
    c = sqlite3.connect(DB_PATH)
    c.executescript(SCHEMA)
    c.commit(); c.close()


def rows(sql, args=()):
    return [dict(r) for r in db().execute(sql, args).fetchall()]


@app.get("/")
def home():
    if os.path.exists(os.path.join(app.root_path, "static", "index.html")):
        return send_from_directory("static", "index.html")
    return jsonify(message="HarvestSync backend is running", health="/api/health")


@app.get("/api/health")
def health():
    return jsonify(status="ok")


# ---------- generic CRUD ----------
@app.get("/api/<name>")
def list_items(name):
    if name not in TABLES:
        return jsonify(error="unknown resource"), 404
    return jsonify(rows(f"SELECT * FROM {TABLES[name][0]} ORDER BY id DESC"))


@app.post("/api/<name>")
def create_item(name):
    if name not in TABLES:
        return jsonify(error="unknown resource"), 404
    table, cols = TABLES[name]
    data = request.get_json(silent=True) or {}
    use = {k: data[k] for k in cols if k in data}
    if not use:
        return jsonify(error="no valid fields", allowed=cols), 400
    if name == "crops":
        err = check_inputs(use.get("crop_type", ""), use.get("soil", "Loamy"), use.get("irrigation", "Canal"))
        if err:
            return jsonify(error=err), 400
    try:
        cur = db().execute(
            f"INSERT INTO {table} ({','.join(use)}) VALUES ({','.join('?' * len(use))})",
            list(use.values()))
        db().commit()
    except sqlite3.IntegrityError as e:
        return jsonify(error=str(e)), 400
    return jsonify(id=cur.lastrowid, **use), 201


@app.delete("/api/<name>/<int:item_id>")
def delete_item(name, item_id):
    if name not in TABLES:
        return jsonify(error="unknown resource"), 404
    db().execute(f"DELETE FROM {TABLES[name][0]} WHERE id=?", (item_id,))
    db().commit()
    return jsonify(deleted=item_id)


# ---------- prediction ----------
def _weather(body):
    return {"rainfall": body.get("rainfall", 800), "temperature": body.get("temperature", 28)}


@app.post("/api/predict")
def predict_direct():
    """Stateless test endpoint: same fields as Member 1's API. Nothing is saved."""
    b = request.get_json(silent=True) or {}
    need = ["crop", "area", "sowing_date"]
    miss = [k for k in need if k not in b]
    if miss:
        return jsonify(error=f"missing fields: {miss}"), 400
    err = check_inputs(b["crop"], b.get("soil", "Loamy"), b.get("irrigation", "Canal"))
    if err:
        return jsonify(error=err), 400
    w = _weather(b)
    y = predict_yield(b["crop"], b["area"], b.get("soil", "loamy"), w["rainfall"],
                      w["temperature"], b.get("irrigation", "canal"), b["sowing_date"])
    r = assess_risk({"irrigation": b.get("irrigation")}, w, y)
    return jsonify({**y, **r})


@app.post("/api/predict/<int:crop_id>")
def predict_crop(crop_id):
    crop = db().execute("SELECT * FROM crops WHERE id=?", (crop_id,)).fetchone()
    if not crop:
        return jsonify(error="crop not found"), 404
    crop = dict(crop)
    err = check_inputs(crop["crop_type"], crop["soil"], crop["irrigation"])
    if err:
        return jsonify(error=err), 400
    farmer = db().execute("SELECT reliability_score FROM farmers WHERE id=?",
                          (crop["farmer_id"],)).fetchone()
    rel = farmer["reliability_score"] if farmer else 0.8
    w = _weather(request.get_json(silent=True) or {})
    y = predict_yield(crop["crop_type"], crop["area_acres"], crop["soil"], w["rainfall"],
                      w["temperature"], crop["irrigation"], crop["sowing_date"])
    r = assess_risk(crop, w, y, rel)
    db().execute(
        """INSERT INTO predictions (crop_id, predicted_yield_kg, predicted_harvest_date,
           harvest_days, risk_score, recommendation, source) VALUES (?,?,?,?,?,?,?)""",
        (crop_id, y["yield_kg"], y["harvest_date"], y["harvest_days"],
         r["risk_score"], r["recommendation"], y["source"]))
    if not crop["expected_harvest_date"]:
        db().execute("UPDATE crops SET expected_harvest_date=? WHERE id=?",
                     (y["harvest_date"], crop_id))
    db().commit()
    return jsonify({"crop_id": crop_id, **y, **r})


@app.get("/api/predictions")
def list_predictions():
    return jsonify(rows("SELECT * FROM predictions ORDER BY id DESC"))


# ---------- supply gap ----------
@app.get("/api/supply-gap")
def supply_gap():
    preds = rows("""
        SELECT c.id crop_id, c.crop_type, f.name farmer, p.predicted_yield_kg,
               p.predicted_harvest_date, p.risk_score
        FROM crops c
        JOIN predictions p ON p.id = (SELECT MAX(id) FROM predictions WHERE crop_id=c.id)
        LEFT JOIN farmers f ON f.id = c.farmer_id
        WHERE c.status != 'harvested'""")
    out = []
    for o in rows("SELECT * FROM buyer_orders WHERE status='open' ORDER BY due_date"):
        match = [p for p in preds if p["crop_type"].lower() == o["crop_type"].lower()]
        on_time = [p for p in match if p["predicted_harvest_date"] <= o["due_date"]]
        late = [p for p in match if p["predicted_harvest_date"] > o["due_date"]]
        # risk-adjusted: each crop's yield is discounted by half its risk score
        supply = sum(p["predicted_yield_kg"] * (1 - 0.5 * (p["risk_score"] or 0)) for p in on_time)
        gap = o["quantity_kg"] - supply
        out.append({
            "order_id": o["id"], "buyer": o["buyer_name"], "crop_type": o["crop_type"],
            "due_date": o["due_date"], "ordered_kg": o["quantity_kg"],
            "expected_supply_kg": round(supply, 1), "gap_kg": round(max(gap, 0), 1),
            "status": "OK" if gap <= 0 else "SHORTFALL",
            "crops_on_time": [p["crop_id"] for p in on_time],
            "crops_late": [p["crop_id"] for p in late]})
    return jsonify(out)


# ---------- demo data ----------
@app.post("/api/seed")
def seed():
    if rows("SELECT id FROM farmers LIMIT 1"):
        return jsonify(message="already has data"), 200
    d = db()
    for n, v, rel in [("Ramesh", "Doddaballapur", 0.9), ("Lakshmi", "Hoskote", 0.75),
                      ("Suresh", "Magadi", 0.5)]:
        d.execute("INSERT INTO farmers(name,village,reliability_score) VALUES(?,?,?)", (n, v, rel))
    t = date.today()
    for fid, crop, area, soil, irr, off in [
            (1, "tomato", 3, "loamy", "drip", -30), (2, "tomato", 2, "red", "canal", -40),
            (3, "tomato", 4, "alluvial", "rainfed", -20), (1, "potato", 2, "loamy", "canal", -50)]:
        d.execute("""INSERT INTO crops(farmer_id,crop_type,area_acres,soil,irrigation,sowing_date)
                     VALUES(?,?,?,?,?,?)""", (fid, crop, area, soil, irr, (t + timedelta(days=off)).isoformat()))
    d.execute("INSERT INTO buyer_orders(buyer_name,crop_type,quantity_kg,due_date) VALUES(?,?,?,?)",
              ("FreshFoods Pvt Ltd", "tomato", 6000, (t + timedelta(days=75)).isoformat()))
    d.execute("INSERT INTO buyer_orders(buyer_name,crop_type,quantity_kg,due_date) VALUES(?,?,?,?)",
              ("ChipCo", "potato", 2000, (t + timedelta(days=70)).isoformat()))
    d.commit()
    return jsonify(message="demo data loaded"), 201


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
