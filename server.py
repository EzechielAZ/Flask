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

# Configuration de la clé secrète
app.secret_key = 'b@L$}pX>#fW3&9JHqTzY*8M^v?6RdPzKsUnw5Bm4!CgNr$A'

# Configuration de la base de données
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql://root:Forlike10#!@localhost/beninestate'
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

# Point d'entrée principal pour lancer l'application
if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
