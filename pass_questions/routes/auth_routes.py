import os
import time
import hashlib
import secrets
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify, flash
from firebase_admin import firestore

auth_bp = Blueprint("auth", __name__)
db_firestore = firestore.client()

# ---------- SESSION MANAGEMENT FUNCTIONS ----------
def generate_session_token():
    """Generate a unique session token"""
    return secrets.token_urlsafe(32)

def get_device_fingerprint(request):
    """Create a unique device fingerprint"""
    user_agent = request.headers.get('User-Agent', '')
    ip_address = request.remote_addr
    
    # Create a hash from user agent and IP
    fingerprint_str = f"{user_agent}:{ip_address}"
    return hashlib.sha256(fingerprint_str.encode()).hexdigest()

def validate_session(user_session):
    """Validate if the current session is still active"""
    try:
        if not user_session:
            return False, "No active session"
        
        uid = user_session.get("uid")
        session_id = user_session.get("session_id")
        
        if not uid or not session_id:
            return False, "Invalid session data"
        
        user_ref = db_firestore.collection("users").document(uid)
        doc = user_ref.get()
        
        if not doc.exists:
            return False, "User not found"
        
        user_data = doc.to_dict()
        active_session_id = user_data.get("active_session_id")
        
        # Check if session matches
        if active_session_id != session_id:
            return False, "Session invalidated by another login"
        
        # Check session expiration (24 hours)
        session_created = user_data.get("session_created")
        if session_created:
            if hasattr(session_created, 'timestamp'):
                session_time = session_created.replace(tzinfo=None)
            else:
                session_time = session_created
            
            if datetime.now() - session_time > timedelta(hours=24):
                # Clear expired session from database
                user_ref.update({
                    "active_session_id": None,
                    "session_created": None
                })
                return False, "Session expired"
        
        return True, "Session valid"
        
    except Exception as e:
        return False, f"Session validation error: {str(e)}"

# ---------- SESSION VALIDATION MIDDLEWARE ----------
@auth_bp.before_app_request
def check_session_globally():
    """Check session validity for all routes (except auth endpoints)"""
    # Skip session check for these endpoints
    excluded_endpoints = [
        'auth.signup',
        'auth.login', 
        'auth.login_complete',
        'auth.logout',
        'static',
        'payment.payment_page',
        'payment.handle_payment'
    ]
    
    # Get the endpoint name
    endpoint = request.endpoint
    
    # Skip if endpoint is in excluded list or doesn't exist
    if not endpoint or endpoint in excluded_endpoints:
        return
    
    user = session.get("user")
    
    # If no user session but trying to access protected pages, redirect to login
    if not user:
        if endpoint.startswith('admin.') or endpoint == 'auth.user_dashboard':
            flash("Please log in to continue", "warning")
            return redirect(url_for("auth.login"))
        return
    
    # Validate the session
    is_valid, message = validate_session(user)
    
    if not is_valid:
        # Clear invalid session
        session.pop("user", None)
        
        # If it was invalidated by another login, show specific message
        if "another login" in message:
            flash("You have been logged out because you logged in from another device", "warning")
        else:
            flash("Your session has expired. Please log in again.", "info")
        
        # Redirect to login page
        return redirect(url_for("auth.login"))

# ---------- SIGNUP PAGE ----------
@auth_bp.route("/signup", methods=["GET"])
def signup():
    return render_template("signup.html")

# ---------- LOGIN PAGE ----------
@auth_bp.route("/login", methods=["GET"])
def login():
    firebase_config = {
        "apiKey": os.environ.get("FIREBASE_API_KEY"),
        "authDomain": os.environ.get("FIREBASE_AUTH_DOMAIN"),
        "projectId": os.environ.get("FIREBASE_PROJECT_ID"),
        "storageBucket": os.environ.get("FIREBASE_STORAGE_BUCKET"),
        "messagingSenderId": os.environ.get("FIREBASE_MESSAGING_SENDER_ID"),
        "appId": os.environ.get("FIREBASE_APP_ID"),
        "measurementId": os.environ.get("FIREBASE_MEASUREMENT_ID"),
    }
    return render_template("login.html", firebase_config=firebase_config)

# ---------- HANDLE LOGIN (UPDATED FOR SINGLE DEVICE) ----------
@auth_bp.route("/login_complete", methods=["POST"])
def login_complete():
    try:
        data = request.get_json(force=True)
        uid = data.get("uid")
        email = data.get("email")
        username = data.get("username", "")

        if not uid or not email:
            return jsonify({"status": "error", "message": "Missing UID or email"}), 400

        user_ref = db_firestore.collection("users").document(uid)
        doc = user_ref.get()

        # Generate new session token
        session_token = generate_session_token()
        device_fingerprint = get_device_fingerprint(request)
        
        if doc.exists:
            user_data = doc.to_dict()
            role = user_data.get("role", "user")
            paid = user_data.get("paid", False)
            username = user_data.get("username", username)
            
            # Check if user already has an active session
            active_session_id = user_data.get("active_session_id")
            if active_session_id:
                # User is logging in from another device - invalidate old session
                print(f"User {email} logged in from new device, invalidating old session")
            
            # Update user with new session info
            user_ref.update({
                "active_session_id": session_token,
                "session_created": datetime.now(),
                "device_fingerprint": device_fingerprint,
                "last_login": datetime.now(),
                "login_count": (user_data.get("login_count", 0) + 1),
                "updated_at": datetime.now()
            })
        else:
            role = "user"
            paid = False
            # Create new user with session info
            user_ref.set({
                "email": email,
                "username": username,
                "role": role,
                "paid": paid,
                "active_session_id": session_token,
                "session_created": datetime.now(),
                "device_fingerprint": device_fingerprint,
                "last_login": datetime.now(),
                "login_count": 1,
                "created_at": datetime.now(),
                "updated_at": datetime.now()
            })

        # Clear old session and create new one with session token
        session.clear()
        session["user"] = {
            "uid": uid,
            "email": email,
            "username": username,
            "role": role,
            "paid": paid,
            "session_id": session_token,
            "device_fingerprint": device_fingerprint,
            "login_time": datetime.now().isoformat()
        }

        # ✅ Correct redirect after login:
        if role == "admin":
            redirect_url = url_for("auth.admin_dashboard")
        elif not paid:
            redirect_url = url_for("payment.payment_page")
        else:
            redirect_url = url_for("auth.user_dashboard")

        return jsonify({
            "status": "success",
            "redirect": redirect_url,
            "user": session["user"],
            "session_id": session_token  # For client-side storage
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ---------- ADMIN DASHBOARD ----------
@auth_bp.route("/admin/dashboard")
def admin_dashboard():
    user = session.get("user")
    if not user:
        return redirect(url_for("auth.login"))
    if user.get("role") != "admin":
        return redirect(url_for("auth.user_dashboard"))
    return render_template("dashboard_admin.html", user=user)

# ---------- USER DASHBOARD ----------
@auth_bp.route("/dashboard")
def user_dashboard():
    user = session.get("user")
    if not user:
        return redirect(url_for("auth.login"))

    # ✅ If not paid, force payment
    if not user.get("paid") and user.get("role") != "admin":
        return redirect(url_for("payment.payment_page"))

    return render_template("dashboard_user.html", user=user)

# ---------- LOGOUT (UPDATED TO CLEAR SESSION FROM DB) ----------
@auth_bp.route("/logout")
def logout():
    user = session.get("user")
    
    if user:
        uid = user.get("uid")
        
        # Clear session from database
        try:
            user_ref = db_firestore.collection("users").document(uid)
            user_ref.update({
                "active_session_id": None,
                "session_created": None,
                "device_fingerprint": None
            })
        except Exception as e:
            print(f"Error clearing session from database: {e}")
    
    # Clear Flask session
    session.pop("user", None)
    flash("Logged out successfully from all devices.", "info")
    return redirect(url_for("auth.login"))

# ---------- SESSION CHECK API ----------
@auth_bp.route("/api/session/check", methods=["GET"])
def check_session_api():
    """API endpoint for client-side session validation"""
    user = session.get("user")
    
    if not user:
        return jsonify({"valid": False, "message": "No active session"}), 401
    
    try:
        is_valid, message = validate_session(user)
        
        if not is_valid:
            # Clear invalid session
            session.pop("user", None)
            return jsonify({
                "valid": False, 
                "message": message,
                "redirect": url_for("auth.login")
            }), 401
        
        return jsonify({
            "valid": True,
            "user": {
                "email": user.get("email"),
                "username": user.get("username"),
                "role": user.get("role")
            }
        })
        
    except Exception as e:
        return jsonify({"valid": False, "message": str(e)}), 500

# ---------- SESSION DEBUG ----------
@auth_bp.route("/session_debug")
def session_debug():
    return jsonify(session.get("user", {"message": "No active session"}))

# ---------- FORCE LOGOUT FROM ALL DEVICES ----------
@auth_bp.route("/api/force_logout_all", methods=["POST"])
def force_logout_all():
    """Force logout from all devices (for testing or admin use)"""
    try:
        data = request.get_json()
        uid = data.get("uid")
        
        if not uid:
            return jsonify({"status": "error", "message": "UID required"}), 400
        
        user_ref = db_firestore.collection("users").document(uid)
        user_ref.update({
            "active_session_id": None,
            "session_created": None,
            "device_fingerprint": None
        })
        
        return jsonify({"status": "success", "message": "Logged out from all devices"})
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500