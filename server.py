import os
from flask import Flask
from flask_mail import Mail
from flask_migrate import Migrate
from flask_cors import CORS
from app.models import db
from app.routes import init_routes, socketio
from app.config import Config
from app import mail  # Importer mail

# Créer une application Flask
app = Flask(__name__)

# Charger la configuration depuis la classe Config
app.config.from_object(Config)

# Initialiser mail avec l'application
mail.init_app(app)

# 🔒 Sécuriser la clé secrète
app.secret_key = os.environ.get('SECRET_KEY')
if not app.secret_key:
    raise ValueError("SECRET_KEY est obligatoire. Définissez-le dans vos variables d'environnement.")

# 🔥 Utiliser la base de données fournie par Render
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
if not app.config['SQLALCHEMY_DATABASE_URI']:
    raise ValueError("DATABASE_URL est obligatoire. Ajoutez-la dans vos variables d'environnement.")

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialiser la base de données
db.init_app(app)

# Initialiser Flask-Migrate
migrate = Migrate(app, db)

# Configurer CORS
CORS(app, resources={r"/*": {"origins": "*"}})

# Initialiser SocketIO avec l'application
socketio.init_app(app)

# Initialiser les routes
init_routes(app)

# Déterminer le mode debug
debug_mode = os.environ.get("FLASK_DEBUG", "False").lower() in ("true", "1")

# Point d'entrée principal pour lancer l'application
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))  # 🔥 Récupérer le port fourni par Render
    socketio.run(app, host='0.0.0.0', port=port, debug=debug_mode)
