from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.dialects.postgresql import JSON

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'Users'
    user_id = db.Column(db.String, primary_key=True)
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    email = db.Column(db.String(100), unique=True, nullable=False)
    phone_number = db.Column(db.String(20))
    address = db.Column(db.Text)
    role = db.Column(db.Enum('admin', 'agent', 'buyer', 'seller'), nullable=False, default='buyer')
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    photo_url = db.Column(db.String(255))

    # Champs pour la gestion des tentatives de connexion échouées
    failed_login_attempts = db.Column(db.Integer, default=0)
    last_failed_login = db.Column(db.DateTime, nullable=True)
    lockout_until = db.Column(db.DateTime, nullable=True)

    # Nouveaux champs ajoutés
    avis = db.Column(db.JSON, default={})  # Stocke les avis sous format JSON
    rating = db.Column(db.Float, default=0)  # Note de l'utilisateur
    followers = db.Column(db.JSON, default=list)  # Liste des followers
    likes = db.Column(db.Integer, default=0)  # Nombre de likes reçus
    contact_info = db.Column(db.Text, nullable=True)  # Informations de contact
    secteurs = db.Column(db.Text, nullable=True)  # Secteurs d'activité ou d'intérêt

    # Relations
    agent = db.relationship('Agent', back_populates='user', uselist=False)
    properties = db.relationship('Property', backref='seller', lazy=True)
    transactions = db.relationship('Transaction', backref='buyer', lazy=True)
    reviews = db.relationship('PropertyReview', backref='user', lazy=True)
    favorites = db.relationship('UserFavorite', backref='user', lazy=True)


class Agent(db.Model):
    __tablename__ = 'Agents'
    agent_id = db.Column(db.String, primary_key=True, autoincrement=True)
    user_id = db.Column(db.String, db.ForeignKey('Users.user_id'))
    agency_name = db.Column(db.String(255))

    # Relations
    user = db.relationship('User', back_populates='agent')
    properties = db.relationship('Property', backref='agent', lazy=True)
    transactions = db.relationship('Transaction', backref='agent', lazy=True)

class Property(db.Model):
    __tablename__ = 'Properties'
    property_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    address = db.Column(db.Text, nullable=False)
    rue = db.Column(db.String, nullable= False)
    quartier = db.Column(db.String, nullable = True)
    price = db.Column(db.Numeric(20, 2), nullable=False)
    property_type = db.Column(db.Enum('house', 'apartment', 'land', 'commercial', 'office', 'rooms', 'salles_fetes', 'villa', 'duplex'), nullable=False)
    bedrooms = db.Column(db.Integer)
    bathrooms = db.Column(db.Integer)
    area = db.Column(db.Numeric(10, 2))
    agent_id = db.Column(db.String, db.ForeignKey('Agents.agent_id'))
    seller_id = db.Column(db.String, db.ForeignKey('Users.user_id'))
    latitude = db.Column(db.Numeric(9, 6))
    longitude = db.Column(db.Numeric(9, 6))
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    tags = db.Column(db.JSON)
    transaction_type = db.Column(db.Enum('rent', 'sale'))
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    amenities = db.Column(MutableDict.as_mutable(JSON), nullable=True)  # Définir un champ JSON

    # Relations
    photos = db.relationship('PropertyPhoto', backref='property', lazy=True)
    reviews = db.relationship('PropertyReview', backref='property', lazy=True)
    transactions = db.relationship('Transaction', backref='property', lazy=True)

    # Méthode pour convertir en dictionnaire
    def to_dict(self):
        return {
            'property_id': self.property_id,
            'title': self.title,
            'description': self.description,
            'address': self.address,
            'price': str(self.price),  # Conversion en chaîne de caractères pour éviter les erreurs de sérialisation
            'property_type': self.property_type,
            'bedrooms': self.bedrooms,
            'bathrooms': self.bathrooms,
            'area': str(self.area),  # Pareil pour le champ area
            'agent_id': self.agent_id,
            'seller_id': self.seller_id,
            'latitude': str(self.latitude) if self.latitude else None,  # Convertir les décimales en chaîne
            'longitude': str(self.longitude) if self.longitude else None,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'tags': self.tags,
            'amenities': self.amenities,
            'photos': [photo.to_dict() for photo in self.photos],  # Inclure les photos
            'reviews': [review.to_dict() for review in self.reviews],  # Inclure les avis
            'transactions': [transaction.to_dict() for transaction in self.transactions]  # Inclure les transactions
        }
        
class PropertyAlert(db.Model):
    __tablename__ = 'property_alerts'
    
    alert_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), db.ForeignKey('Users.user_id'), nullable=False)
    min_price = db.Column(db.Float)
    max_price = db.Column(db.Float)
    bedrooms = db.Column(db.Integer)
    bathrooms = db.Column(db.Integer)
    property_type = db.Column(db.String(50))
    location = db.Column(db.String(100))
    transaction_type = db.Column(db.String(50))
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref=db.backref('property_alerts', lazy=True))

class PropertyPhoto(db.Model):
    __tablename__ = 'PropertyPhotos'
    photo_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    property_id = db.Column(db.Integer, db.ForeignKey('Properties.property_id'))
    photo_url = db.Column(db.String(255), nullable=False)

class Transaction(db.Model):
    __tablename__ = 'Transactions'
    transaction_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    property_id = db.Column(db.Integer, db.ForeignKey('Properties.property_id'))
    buyer_id = db.Column(db.String, db.ForeignKey('Users.user_id'))
    agent_id = db.Column(db.String, db.ForeignKey('Agents.agent_id'))
    transaction_date = db.Column(db.DateTime, server_default=db.func.now())
    sale_price = db.Column(db.Numeric(10, 2))

class PropertyReview(db.Model):
    __tablename__ = 'PropertyReviews'
    review_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    property_id = db.Column(db.Integer, db.ForeignKey('Properties.property_id'))
    user_id = db.Column(db.String, db.ForeignKey('Users.user_id'))
    rating = db.Column(db.Integer, nullable=False)
    review_text = db.Column(db.Text)
    review_date = db.Column(db.DateTime, server_default=db.func.now())

class UserFavorite(db.Model):
    __tablename__ = 'UserFavorites'
    
    favorite_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    # Modification de la colonne user_id pour être une chaîne
    user_id = db.Column(db.String, db.ForeignKey('Users.user_id'))
    
    # Clés étrangères optionnelles
    property_id = db.Column(db.Integer, db.ForeignKey('Properties.property_id'), nullable=True)

    added_at = db.Column(db.DateTime, default=db.func.current_timestamp())

    
class CommercialProductReviews(db.Model):
    __tablename__ = 'commercial_reviews'
    id_review = db.Column(db.Integer, primary_key=True, autoincrement=True)
    id_user = db.Column(db.String, db.ForeignKey('Users.user_id'))
    id_product = db.Column(db.Integer, db.ForeignKey('commercialproducts.product_id'))
    date_posted = db.Column(db.DateTime, server_default=db.func.now())
    rating = db.Column(db.Integer, nullable=False)
    review_text = db.Column(db.Text)
    
class CommercialProduct(db.Model):
    __tablename__ = 'commercialproducts'
    product_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    seller_id = db.Column(db.String(255), nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    image_url = db.Column(db.String(255), nullable=True)
    poster = db.Column(db.String(255), nullable=True)
    stock = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    is_active = db.Column(db.Boolean, default=True)
    category = db.Column(db.String(255))
    tags = db.Column(MutableDict.as_mutable(JSON), nullable=True)

    def to_dict(self):
        return {
            'product_id': self.product_id,
            'name': self.name,
            'description': self.description,
            'seller_id': self.seller_id,
            'price': str(self.price),  # Pour éviter les problèmes de sérialisation des décimales
            'image_url': self.image_url,
            'poster': self.poster,
            'stock': self.stock,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'is_active': self.is_active,
            'category': self.category,
            'tags': self.tags  # Le champ JSON sera directement sérialisé
        }
        

class PropertyRequest(db.Model):
    __tablename__ = 'PropertyRequests'

    request_id = db.Column(db.String(36), primary_key=True)
    user_id = db.Column(db.String(36), db.ForeignKey('Users.user_id'), nullable=False)
    
    property_type = db.Column(db.String(50), nullable=False)
    bedrooms = db.Column(db.Integer)
    bathrooms = db.Column(db.Integer)
    surface_area = db.Column(db.Integer)
    location = db.Column(db.String(150), nullable=False)
    
    budget_amount = db.Column(db.Numeric(15, 2))
    budget_currency = db.Column(db.String(10), default='XOF')
    additional_fees_accepted = db.Column(db.Boolean, default=False)
    
    contract_type = db.Column(db.Enum('short_term', 'long_term', 'purchase', 'long terme'), 
                            default='long_term')
    start_date = db.Column(db.Date)
    
    amenities = db.Column(db.JSON)
    nearby_services = db.Column(db.JSON)
    
    user_verified = db.Column(db.Boolean, default=False)
    user_activity_history = db.Column(db.Text)
    
    occupation = db.Column(db.String(100))
    family_status = db.Column(db.String(50))
    request_reason = db.Column(db.Text)
    
    hide_contact_info = db.Column(db.Boolean, default=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    
class Category(db.Model):
    __tablename__ = 'categories'
    
    category_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    category_name = db.Column(db.String(100), nullable=False, unique=True)
    category_description = db.Column(db.Text)

    # Relation avec Shops
    shops = db.relationship('Shop', backref='category', lazy=True)

class Shop(db.Model):
    __tablename__ = 'shops'
    
    shop_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.String, db.ForeignKey('Users.user_id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.category_id'))
    shop_name = db.Column(db.String(100), nullable=False)
    shop_description = db.Column(db.Text)
    shop_address = db.Column(db.String(255))
    shop_city = db.Column(db.String(100))
    shop_country = db.Column(db.String(100))
    shop_phone = db.Column(db.String(20))
    shop_email = db.Column(db.String(100))
    logo = db.Column(db.String(255))  # Champ pour le logo
    cover_image = db.Column(db.String(255))  # Champ pour l'image de couverture
    subcategory = db.Column(db.String(100))  # Champ pour la sous-catégorie
    map_location = db.Column(db.JSON)  # Champ pour la localisation (JSON)
    website = db.Column(db.String(100))  # Champ pour le site web
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    updated_at = db.Column(db.DateTime, default=db.func.current_timestamp(), onupdate=db.func.current_timestamp())

    # Relation avec Users
    user = db.relationship('User', backref='shops', lazy=True)

    def to_dict(self):
        return {
            'shop_id': self.shop_id,
            'user_id': self.user_id,
            'category_id': self.category_id,
            'shop_name': self.shop_name,
            'shop_description': self.shop_description,
            'shop_address': self.shop_address,
            'shop_city': self.shop_city,
            'shop_country': self.shop_country,
            'shop_phone': self.shop_phone,
            'shop_email': self.shop_email,
            'logo': self.logo,
            'cover_image': self.cover_image,
            'subcategory': self.subcategory,
            'map_location': self.map_location,
            'website': self.website,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class CommercialProductPhoto(db.Model):
    __tablename__ = 'commercialproductphotos'
    photo_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    commercial_product_id = db.Column(db.Integer, db.ForeignKey('commercialproducts.product_id'), nullable=False)
    photo_url = db.Column(db.String(255), nullable=False)
    uploaded_at = db.Column(db.DateTime, server_default=db.func.now())

    # Relation
    commercial_product = db.relationship('CommercialProduct', backref='photos', lazy=True)
    
class Notification(db.Model):
    __tablename__ = 'notifications'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.String, db.ForeignKey('Users.user_id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    type = db.Column(db.Enum('info', 'warning', 'error', 'proposal','like_p','following','reviewing'), default='info')  # Type de notification
    is_read = db.Column(db.Boolean, default=False)  # Indique si la notification a été lue
    created_at = db.Column(db.DateTime, server_default=db.func.now())  # Date et heure de création
    property_cover_photo = db.Column(db.Text, nullable= True)
    
    # Relation
    user = db.relationship('User', back_populates='notifications')

# Ajoutez cette ligne à la classe User pour établir la relation
User.notifications = db.relationship('Notification', back_populates='user', lazy=True)

class VideoLike(db.Model):
    __tablename__ = 'video_likes'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    video_id = db.Column(db.Integer, db.ForeignKey('videos.id'), nullable=False)
    user_id = db.Column(db.String(255), db.ForeignKey('Users.user_id'), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    # Relations
    user = db.relationship('User', backref='liked_videos', lazy=True)
    video = db.relationship('Video', backref='video_likes', lazy=True)  # Renommé en 'video_likes'

class Message(db.Model):
    __tablename__ = 'Messages'

    # Identifiant unique pour chaque message (entier)
    message_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    
    # Identifiants des expéditeurs et destinataires sous forme de chaînes
    sender_id = db.Column(db.String(255), db.ForeignKey('Users.user_id'), nullable=False)
    receiver_id = db.Column(db.String(255), db.ForeignKey('Users.user_id'), nullable=False)
    
    # Identifiant de la conversation à laquelle le message appartient
    conversation_id = db.Column(db.Integer, db.ForeignKey('Conversations.conversation_id'), nullable=False)
    
    # Contenu du message
    message_content = db.Column(db.Text, nullable=True)  # Rendre le contenu du message facultatif pour les messages uniquement multimédias
    
    # URL du fichier multimédia (image, vidéo, etc.)
    media_url = db.Column(db.String(255), nullable=True)  # Ce champ stocke le lien du fichier
    
    # Type de fichier multimédia (image, vidéo, etc.)
    media_type = db.Column(db.Enum('image', 'video'), nullable=True)
    
    # Date d'envoi du message
    sent_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    
    # Date de lecture du message, initialement null
    read_at = db.Column(db.DateTime, nullable=True)
    
    # Statut du message (envoyé, livré, lu)
    status = db.Column(db.Enum('sent', 'delivered', 'read'), default='sent')
    
    # Réplique à un message spécifique (relation auto-référencée)
    reply_to_id = db.Column(db.Integer, db.ForeignKey('Messages.message_id'), nullable=True)
    reply_to = db.relationship('Message', remote_side=[message_id], backref='replies', lazy=True)

    # Relations
    sender = db.relationship('User', foreign_keys=[sender_id], backref='sent_messages', lazy=True)
    receiver = db.relationship('User', foreign_keys=[receiver_id], backref='received_messages', lazy=True)
    conversation = db.relationship('Conversation', backref='messages', lazy=True)


class Colocation(db.Model):
    __tablename__ = 'colocation_offer'
    
    # Identifiant unique pour chaque message (entier)
    colocation_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    
    # Identifiants des expéditeurs et destinataires sous forme de chaînes
    poster_id = db.Column(db.String(255), db.ForeignKey('Users.user_id'), nullable=False)
    
    # Identifiant de la conversation à laquelle le message appartient
    description = db.Column(db.Text, nullable=False)
    
    location = db.Column(db.Text, nullable=False)
    
    images_urls = db.Column(db.JSON, nullable=False)
    
    tags = db.Column(db.JSON, nullable=False)
    
    colocator_preferences = db.Column(db.Text, nullable = False)
    
    requirements = db.Column(db.JSON)
    
    boosted = db.Column(db.Boolean)
    
    status = db.Column(db.Boolean)
    
    post_tags = db.Column(db.JSON)
    



class Conversation(db.Model):
    __tablename__ = 'Conversations'  # Nom de la table

    conversation_id = db.Column(db.Integer, primary_key=True, autoincrement=True)  # Identifiant unique de la conversation
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())  # Date de création
    updated_at = db.Column(db.DateTime, default=db.func.current_timestamp(), onupdate=db.func.current_timestamp())  # Date de mise à jour

    def __repr__(self):
        return f'<Conversation {self.conversation_id}>'

class Video(db.Model):
    __tablename__ = 'videos'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.String(255), db.ForeignKey('Users.user_id'), nullable=False)
    video_url = db.Column(db.String(255), nullable=False)
    thumbnail_url = db.Column(db.String(255), nullable=True)
    caption = db.Column(db.Text)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    likes = db.Column(db.Integer, default=0)
    comments_count = db.Column(db.Integer, default=0)
    views_count = db.Column(db.Integer, default=0)
    product_id = db.Column(db.Integer, db.ForeignKey('commercialproducts.product_id'), nullable=True)
    price = db.Column(db.Numeric(10, 2))
    currency = db.Column(db.String(3))
    stock = db.Column(db.Integer, default=0)
    transaction_id = db.Column(db.Integer, db.ForeignKey('Transactions.transaction_id'), nullable=True)
    purchase_count = db.Column(db.Integer, default=0)

    # Relations
    user = db.relationship('User', backref='videos', lazy=True)
    product = db.relationship('CommercialProduct', backref='videos', lazy=True)
    transaction = db.relationship('Transaction', backref='video', lazy=True)


class Proposal(db.Model):
    __tablename__ = 'proposals'

    proposal_id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(db.Integer, db.ForeignKey('Properties.property_id', ondelete='SET NULL'), nullable=True)
    user_id = db.Column(db.String(50), db.ForeignKey('Users.user_id', ondelete='CASCADE'), nullable=False)
    request_id = db.Column(db.String(36), db.ForeignKey('PropertyRequests.request_id', ondelete='SET NULL'), nullable=True)
    price_offer = db.Column(db.Numeric(20, 2), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True) 
    location = db.Column(db.String(255), nullable=False)
    bedrooms = db.Column(db.Integer, default=0)
    bathrooms = db.Column(db.Integer, default=0)
    surface_area = db.Column(db.Numeric(10, 2), nullable=True)
    images = db.Column(db.JSON, nullable=True)
    status = db.Column(db.Enum('pending', 'accepted', 'rejected', name='proposal_status'), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Spécification explicite de la jointure
    property = db.relationship('Property', backref=db.backref('proposals', lazy=True),
                               primaryjoin="Proposal.property_id == Property.property_id")

    user = db.relationship('User', backref=db.backref('proposals', lazy=True), foreign_keys=[user_id])  # Assurez-vous de spécifier foreign_keys
    request = db.relationship('PropertyRequest', backref=db.backref('proposals', lazy=True))

    def __repr__(self):
        return f'<Proposal {self.proposal_id} - {self.title}>'
