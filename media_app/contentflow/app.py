from flask import Blueprint

contentflow_bp = Blueprint('contentflow', __name__)

@contentflow_bp.route('/contentflow')
def home():
    return "Welcome to ContentFlow!" 