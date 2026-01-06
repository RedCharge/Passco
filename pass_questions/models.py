# pass_questions/models.py
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from pass_questions import db

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)   # new
    password = db.Column(db.String(150), nullable=True)
    is_admin = db.Column(db.Boolean, default=False)
    is_verified = db.Column(db.Boolean, default=False)               
    has_paid = db.Column(db.Boolean, default=False)                  
    verification_token = db.Column(db.String(100), nullable=True)    

class PDF(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(300), nullable=False)
    program = db.Column(db.String(100), nullable=False)
    course = db.Column(db.String(100), nullable=False)
    year = db.Column(db.String(50), nullable=False)
