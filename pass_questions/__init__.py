import os
from flask import Flask, send_from_directory, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timedelta

# ------------------- GLOBAL OBJECTS -------------------
db = SQLAlchemy()
login_manager = LoginManager()

# ------------------- FIREBASE USER CLASS -------------------
class FirebaseUser(UserMixin):
    def __init__(self, uid, email, username, role, paid, session_id):
        self.id = uid
        self.uid = uid
        self.email = email
        self.username = username
        self.role = role
        self.paid = paid
        self.session_id = session_id
        
    def get_id(self):
        return self.id
        
    @property
    def is_authenticated(self):
        # Check if session is still valid
        user_session = session.get("user")
        if not user_session:
            return False
        
        # Check if session ID matches
        return user_session.get("session_id") == self.session_id
        
    @property
    def is_active(self):
        return True
        
    @property
    def is_anonymous(self):
        return False

# ------------------- CREATE APP -------------------
def create_app():
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    TEMPLATE_FOLDER = os.path.join(BASE_DIR, "templates")
    STATIC_FOLDER = os.path.join(BASE_DIR, "static")

    app = Flask(
        __name__,
        template_folder=TEMPLATE_FOLDER,
        static_folder=STATIC_FOLDER
    )

    # ------------------- CONFIG -------------------
    app.config['SECRET_KEY'] = 'supersecretkey'
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///passquestion.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # ------------------- DATABASE -------------------
    db.init_app(app)

    # ------------------- FLASK-LOGIN -------------------
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'

    # ------------------- FIREBASE -------------------
    cred_path = os.path.join(BASE_DIR, "serviceAccountKey.json")
    if not firebase_admin._apps:  # prevent double init
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
    
    # Initialize Firestore
    firestore_db = firestore.client()

    # ------------------- USER LOADER -------------------
    @login_manager.user_loader
    def load_user(user_id):
        try:
            # Get user from Flask session first
            user_session = session.get("user")
            
            if not user_session:
                return None
            
            # Verify session ID matches
            if user_session.get("uid") != user_id:
                return None
            
            # Get user from Firestore for latest data
            user_doc = firestore_db.collection("users").document(user_id).get()
            
            if not user_doc.exists:
                return None
            
            user_data = user_doc.to_dict()
            
            # Check if session is still valid
            active_session_id = user_data.get("active_session_id")
            session_created = user_data.get("session_created")
            
            if not active_session_id or active_session_id != user_session.get("session_id"):
                return None
            
            # Check session expiration (24 hours)
            if session_created:
                if hasattr(session_created, 'timestamp'):
                    session_time = session_created.replace(tzinfo=None)
                else:
                    session_time = session_created
                
                if datetime.now() - session_time > timedelta(hours=24):
                    return None
            
            return FirebaseUser(
                uid=user_id,
                email=user_data.get("email", ""),
                username=user_data.get("username", ""),
                role=user_data.get("role", "user"),
                paid=user_data.get("paid", False),
                session_id=active_session_id
            )
                
        except Exception as e:
            app.logger.error(f"Error loading user {user_id}: {str(e)}")
            return None

    # ------------------- PWA ROUTES -------------------
    @app.route('/manifest.json')
    def serve_manifest():
        return send_from_directory(
            STATIC_FOLDER,
            'manifest.json',
            mimetype='application/manifest+json'
        )

    @app.route('/favicon.ico')
    def favicon():
        return send_from_directory(
            STATIC_FOLDER,
            'favicon.ico',
            mimetype='image/vnd.microsoft.icon'
        )

    @app.route('/apple-touch-icon.png')
    def apple_touch_icon():
        return send_from_directory(
            STATIC_FOLDER,
            'apple-touch-icon.png',
            mimetype='image/png'
        )

    @app.route('/apple-touch-icon-precomposed.png')
    def apple_touch_icon_precomposed():
        return send_from_directory(
            STATIC_FOLDER,
            'apple-touch-icon.png',
            mimetype='image/png'
        )

    @app.route('/android-chrome-<int:size>.png')
    def android_chrome_icon(size):
        filename = f'android-chrome-{size}x{size}.png'
        return send_from_directory(
            STATIC_FOLDER,
            filename,
            mimetype='image/png'
        )

    @app.route('/favicon-<int:size>.png')
    def favicon_png(size):
        filename = f'favicon-{size}x{size}.png'
        return send_from_directory(
            STATIC_FOLDER,
            filename,
            mimetype='image/png'
        )

    # ------------------- BLUEPRINTS -------------------
    from pass_questions.routes.auth_routes import auth_bp
    from pass_questions.routes.payment_routes import payment_bp
    from pass_questions.routes.admin_routes import admin_bp
    from pass_questions.routes.main_routes import main_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(payment_bp, url_prefix='/payment')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(main_bp, url_prefix='/')

    # ------------------- CREATE TABLES (for non-user data) -------------------
    with app.app_context():
        db.create_all()

    return app