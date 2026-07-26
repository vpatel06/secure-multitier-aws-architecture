"""
Internship Application Tracker API
-----------------------------------
A minimal Flask + SQLAlchemy API for tracking internship applications.

Runs on SQLite locally (zero setup) and switches to Postgres (RDS) in
production just by setting the DATABASE_URL environment variable.
"""

import os
from datetime import datetime, date

from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)

# --- Database config -------------------------------------------------
# Local dev default: SQLite file in this folder.
# Production (EC2/RDS): set DATABASE_URL, e.g.
#   postgresql://user:password@<rds-endpoint>:5432/trackerdb
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///applications.db")
app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

VALID_STATUSES = {"applied", "oa", "interview", "offer", "rejected"}


# --- Model -------------------------------------------------------------
class Application(db.Model):
    __tablename__ = "applications"

    id = db.Column(db.Integer, primary_key=True)
    company = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(50), nullable=False, default="applied")
    date_applied = db.Column(db.Date, nullable=True)
    source = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "company": self.company,
            "role": self.role,
            "status": self.status,
            "date_applied": self.date_applied.isoformat() if self.date_applied else None,
            "source": self.source,
            "notes": self.notes,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
        }


# --- Routes --------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health():
    """
    Health check that also proves DB connectivity.
    In the AWS deployment, this is what you curl from inside the instance
    (via SSM) to confirm the app tier can actually reach the RDS tier.
    """
    try:
        db.session.execute(db.select(Application).limit(1))
        return jsonify({"status": "ok", "db": "connected"}), 200
    except Exception as e:
        return jsonify({"status": "error", "db": "unreachable", "detail": str(e)}), 500


@app.route("/applications", methods=["POST"])
def create_application():
    data = request.get_json(force=True, silent=True) or {}

    company = data.get("company")
    role = data.get("role")
    if not company or not role:
        return jsonify({"error": "company and role are required"}), 400

    status = data.get("status", "applied")
    if status not in VALID_STATUSES:
        return jsonify({"error": f"status must be one of {sorted(VALID_STATUSES)}"}), 400

    date_applied_raw = data.get("date_applied")
    date_applied = None
    if date_applied_raw:
        try:
            date_applied = datetime.strptime(date_applied_raw, "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"error": "date_applied must be YYYY-MM-DD"}), 400
    else:
        date_applied = date.today()

    app_row = Application(
        company=company,
        role=role,
        status=status,
        date_applied=date_applied,
        source=data.get("source"),
        notes=data.get("notes"),
    )
    db.session.add(app_row)
    db.session.commit()
    return jsonify(app_row.to_dict()), 201


@app.route("/applications", methods=["GET"])
def list_applications():
    status_filter = request.args.get("status")
    query = db.select(Application).order_by(Application.date_applied.desc())
    if status_filter:
        if status_filter not in VALID_STATUSES:
            return jsonify({"error": f"status must be one of {sorted(VALID_STATUSES)}"}), 400
        query = query.filter_by(status=status_filter)

    rows = db.session.execute(query).scalars().all()
    return jsonify([r.to_dict() for r in rows]), 200


@app.route("/applications/<int:app_id>", methods=["GET"])
def get_application(app_id):
    row = db.session.get(Application, app_id)
    if not row:
        return jsonify({"error": "not found"}), 404
    return jsonify(row.to_dict()), 200


@app.route("/applications/<int:app_id>", methods=["PATCH"])
def update_application(app_id):
    row = db.session.get(Application, app_id)
    if not row:
        return jsonify({"error": "not found"}), 404

    data = request.get_json(force=True, silent=True) or {}

    if "status" in data:
        if data["status"] not in VALID_STATUSES:
            return jsonify({"error": f"status must be one of {sorted(VALID_STATUSES)}"}), 400
        row.status = data["status"]
    if "notes" in data:
        row.notes = data["notes"]
    if "company" in data:
        row.company = data["company"]
    if "role" in data:
        row.role = data["role"]
    if "source" in data:
        row.source = data["source"]

    db.session.commit()
    return jsonify(row.to_dict()), 200


@app.route("/applications/<int:app_id>", methods=["DELETE"])
def delete_application(app_id):
    row = db.session.get(Application, app_id)
    if not row:
        return jsonify({"error": "not found"}), 404
    db.session.delete(row)
    db.session.commit()
    return jsonify({"deleted": app_id}), 200


@app.route("/applications/stats", methods=["GET"])
def stats():
    rows = db.session.execute(db.select(Application)).scalars().all()
    counts = {s: 0 for s in VALID_STATUSES}
    for r in rows:
        counts[r.status] = counts.get(r.status, 0) + 1
    counts["total"] = len(rows)
    return jsonify(counts), 200


@app.route("/applications/stale", methods=["GET"])
def stale():
    """
    Follow-up reminder: applications sitting in 'applied' status for 14+ days
    with no update.
    """
    days_threshold = int(request.args.get("days", 14))
    rows = db.session.execute(
        db.select(Application).filter_by(status="applied")
    ).scalars().all()

    stale_rows = []
    for r in rows:
        if r.date_applied:
            age = (date.today() - r.date_applied).days
            if age >= days_threshold:
                d = r.to_dict()
                d["days_since_applied"] = age
                stale_rows.append(d)

    return jsonify(stale_rows), 200


def init_db():
    with app.app_context():
        db.create_all()


if __name__ == "__main__":
    init_db()
    # 0.0.0.0 so it's reachable from other machines on the private network
    # once deployed to EC2; locally it just means localhost still works.
    app.run(host="0.0.0.0", port=5000, debug=True)
