import os
from flask import Flask, send_from_directory, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
import firebase_admin
from firebase_admin import credentials

# ------------------- GLOBAL OBJECTS -------------------
db = SQLAlchemy()
login_manager = LoginManager()

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

    from pass_questions.models import User  # import here to avoid circular imports

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # ------------------- FIREBASE -------------------
    cred_path = os.path.join(BASE_DIR, "serviceAccountKey.json")
    if not firebase_admin._apps:  # prevent double init
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)

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
        # Some browsers look for this
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
    
    

    # ------------------- CREATE TABLES -------------------
    with app.app_context():
        db.create_all()

    return app