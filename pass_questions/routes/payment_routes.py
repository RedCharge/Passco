from flask import Blueprint, render_template, redirect, url_for, flash, session, request, jsonify
from pass_questions.models import db, User
from firebase_admin import auth as firebase_auth
from functools import wraps

payment_bp = Blueprint("payment", __name__)

# ---------------- LOGIN REQUIRED DECORATOR ----------------
def require_login_route(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        user = session.get("user")
        if not user:
            flash("Please log in to continue.", "error")
            return redirect(url_for("auth.login"))
        return func(*args, **kwargs)
    return wrapper


# ---------------- PAYMENT PAGE ----------------
@payment_bp.route("/", methods=["GET"])
@require_login_route
def payment_page():
    user = session.get("user")

    # ✅ Skip payment if admin
    if user.get("role") == "admin":
        flash("Welcome admin — skipping payment.", "info")
        return redirect(url_for("admin.dashboard"))

    # ✅ If already paid, go to user dashboard
    if user.get("paid"):
        return redirect(url_for("main.dashboard"))

    return render_template("payment.html", user=user)


# ---------------- MOCK PAYMENT HANDLER ----------------
@payment_bp.route("/mock", methods=["POST"])
@require_login_route
def mock_payment():
    user = session.get("user")

    if not user:
        return jsonify({"status": "error", "message": "User not logged in"}), 401

    # ✅ Skip payment if admin
    if user.get("role") == "admin":
        return jsonify({"status": "success", "message": "Admin — no payment needed"})

    try:
        # 1. Update local DB
        db_user = User.query.filter_by(email=user["email"]).first()
        if db_user:
            db_user.has_paid = True
            db.session.commit()

        # 2. Update Firebase custom claims
        f_user = firebase_auth.get_user_by_email(user["email"])
        claims = f_user.custom_claims or {}
        claims["paid"] = True
        firebase_auth.set_custom_user_claims(f_user.uid, claims)

        # 3. Update session
        user["paid"] = True
        session["user"] = user

        return jsonify({"status": "success", "message": "Payment marked as successful"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


# ---------------- SUCCESS PAGE ----------------
@payment_bp.route("/success")
@require_login_route
def payment_success():
    user = session.get("user")

    # ✅ If admin, go to admin dashboard
    if user.get("role") == "admin":
        return redirect(url_for("admin.dashboard"))

    return render_template("success.html", user=user)
