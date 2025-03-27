from flask import Blueprint, request, jsonify, send_from_directory, session,abort,send_file
from app.models import db, User, Agent, Property, PropertyPhoto, Transaction,Proposal, PropertyReview, UserFavorite, CommercialProduct, CommercialProductPhoto,CommercialProductReviews ,Video,VideoLike,Message as MessageModel,Conversation,Shop,Category,PropertyAlert,Colocation,PropertyRequest,Notification
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from app import mail  # Importez mail depuis le module principal
from fuzzywuzzy import fuzz
from flask_mail import Message
import io
import os
import math
import qrcode
from PIL import Image, ImageDraw, ImageFilter
import hashlib
import uuid
import requests 
from datetime import datetime, timedelta
from sqlalchemy import or_ , func, and_
import logging
import difflib 
from decimal import Decimal
from flask_socketio import SocketIO, emit, join_room, leave_room

# Dictionnaire pour stocker les associations entre les IDs de socket et les IDs utilisateur
user_socket_map = {}

bp = Blueprint('routes', __name__)

# Initialisez Flask-SocketIO
socketio = SocketIO()

# Configurer le dossier des images
PROPERTY_IMAGE_FOLDER = os.path.join(os.getcwd(), 'property_images')
PRODUCT_IMAGE_FOLDER = os.path.join(os.getcwd(), 'products_images')
PROFILE_IMAGE_FOLDER = os.path.join(os.getcwd(), 'profile_images')
SHOP_IMAGES_FOLDER = os.path.join(os.getcwd(), 'shop_images')
VIDEO_FOLDER = os.path.join(os.getcwd(), 'videos')

# Création des dossiers s'ils n'existent pas
if not os.path.exists(PROPERTY_IMAGE_FOLDER):
    os.makedirs(PROPERTY_IMAGE_FOLDER)

if not os.path.exists(PRODUCT_IMAGE_FOLDER):
    os.makedirs(PRODUCT_IMAGE_FOLDER)
    
if not os.path.exists(PROFILE_IMAGE_FOLDER):
    os.makedirs(PROFILE_IMAGE_FOLDER)
    
if not os.path.exists(SHOP_IMAGES_FOLDER):
    os.makedirs(SHOP_IMAGES_FOLDER)


def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@bp.route('/register', methods=['POST'])
def register_user():
    data = request.get_json()
    new_user = User(
        user_id = data['id'],
        email=data['email'],
    )
    db.session.add(new_user)
    db.session.commit()
    return jsonify({"message": "User registered successfully"}), 201

@bp.route('/update-user', methods=['PUT'])
def update_user():
    data = request.get_json()
    
    # Vérifiez que les données nécessaires sont présentes
    firebase_uid = data.get('firebase_uid')
    first_name = data.get('first_name')

    if not firebase_uid or not first_name:
        return jsonify({"message": "firebase_uid et first_name requis."}), 400

    # Trouver l'utilisateur dans la base de données
    user = User.query.filter_by(user_id=firebase_uid).first()
    
    if user:
        user.first_name = first_name
        db.session.commit()
        return jsonify({"message": "Nom mis à jour avec succès."}), 200
    else:
        return jsonify({"message": "Utilisateur non trouvé."}), 404

@bp.route('/login', methods=['POST'])
def login_user():
    data = request.get_json()

    # Recherche de l'utilisateur par email
    user = User.query.filter_by(email=data['email']).first()

    if not user:
        return jsonify({"message": "Invalid credentials"}), 401

    # Vérifier si l'utilisateur est verrouillé
    if user.lockout_until and user.lockout_until > datetime.now():
        minutes_left = (user.lockout_until - datetime.now()).total_seconds() // 60
        return jsonify({"message": f"Account locked. Try again in {int(minutes_left)} minutes."}), 403

    # Vérification du mot de passe avec check_password_hash
    if check_password_hash(user.password_hash, data['password']):
        # Réinitialiser les tentatives après un succès
        user.failed_login_attempts = 0
        user.lockout_until = None
        db.session.commit()

        # Stocker les informations de l'utilisateur dans la session
        session['user_id'] = user.user_id
        session['user_email'] = user.email
        session['user_role'] = user.role

        # Renvoi des données utilisateur dans la réponse
        return jsonify({
            "message": "Login successful",
            "user": {
                "id": user.user_id,
                "email": user.email,
                "role": user.role
            }
        }), 200
    else:
        # Gestion des tentatives échouées
        now = datetime.now()

        if user.last_failed_login and now - user.last_failed_login > timedelta(minutes=12):
            user.failed_login_attempts = 0

        user.failed_login_attempts += 1
        user.last_failed_login = now

        if user.failed_login_attempts >= 8:
            user.lockout_until = now + timedelta(minutes=30)
            user.failed_login_attempts = 0
            db.session.commit()
            return jsonify({"message": "Too many attempts. Try again in 30 minutes."}), 403

        db.session.commit()
        return jsonify({"message": "Invalid credentials"}), 401


@bp.route('/popular-locations', methods=['GET'])
def get_popular_locations():
    results = db.session.query(
        Property.address,
        func.count(Property.address).label('count')
    ).group_by(Property.address).order_by(func.count(Property.address).desc()).limit(4)
    return jsonify([
        {"location": address, "count": count} for address, count in results
    ])
    
@bp.route('/properties/<string:user_id>', methods=['GET'])
def get_properties(user_id):
    # Récupérer les paramètres 
    location = request.args.get('location')
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 10))
    
    # Récupérer les préférences de l'utilisateur
    user_favorites = UserFavorite.query.filter_by(user_id=user_id).all()
    user_alerts = PropertyAlert.query.filter_by(user_id=user_id, active=True).first()
    
    # Base query
    base_query = Property.query

    if location:
        base_query = base_query.filter(
            or_(
                Property.address.ilike(f'%{location}%'),
                Property.address.contains(location),
                Property.quartier.ilike(f'%{location}%'),
                Property.rue.ilike(f'%{location}%')
            )
        )

    # Personnalisation basée sur les alertes utilisateur
    if user_alerts:
        base_query = base_query.filter(
            and_(
                Property.price >= user_alerts.min_price if user_alerts.min_price else True,
                Property.price <= user_alerts.max_price if user_alerts.max_price else True,
                Property.bedrooms >= user_alerts.bedrooms if user_alerts.bedrooms else True,
                Property.bathrooms >= user_alerts.bathrooms if user_alerts.bathrooms else True,
                Property.property_type == user_alerts.property_type if user_alerts.property_type else True
            )
        )

    # Get all properties first to calculate scores
    properties = base_query.all()

    # Récupérer les propriétés similaires aux favoris
    favorite_property_types = []
    favorite_quartiers = []
    favorite_price_ranges = []
    
    for fav in user_favorites:
        if fav.property_id:
            fav_property = Property.query.get(fav.property_id)
            if fav_property:
                favorite_property_types.append(fav_property.property_type)
                favorite_quartiers.append(fav_property.quartier)
                favorite_price_ranges.append(fav_property.price)

    # Calculer les scores
    scored_properties = []
    
    for prop in properties:
        score = 0
        
        # Score basé sur la nouveauté
        days_old = (datetime.utcnow() - prop.created_at).days
        if days_old <= 7:  # Propriétés de moins d'une semaine
            score += 10
        elif days_old <= 30:  # Propriétés de moins d'un mois
            score += 5
            
        # Score basé sur les préférences
        if prop.property_type in favorite_property_types:
            score += 5
        if prop.quartier in favorite_quartiers:
            score += 5
            
        # Score basé sur la gamme de prix
        if favorite_price_ranges:
            avg_fav_price = sum(favorite_price_ranges) / len(favorite_price_ranges)
            if abs(prop.price - avg_fav_price) <= float(avg_fav_price) * 0.2:  # Dans une marge de 20%
                score += 5

                
        # Score basé sur les photos
        photo_count = PropertyPhoto.query.filter_by(property_id=prop.property_id).count()
        if photo_count >= 5:
            score += 3
            
        # Score basé sur les avis
        avg_rating = db.session.query(func.avg(PropertyReview.rating)).filter_by(property_id=prop.property_id).scalar()
        if avg_rating and avg_rating >= 4:
            score += 4
            
        scored_properties.append((prop, score))

    # Trier par score décroissant
    scored_properties.sort(key=lambda x: x[1], reverse=True)
    
    # Pagination manuelle
    total_properties = len(scored_properties)
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    
    # Prendre la portion de la liste pour la page actuelle
    paginated_properties = scored_properties[start_idx:end_idx]

    result = []
    for prop, score in paginated_properties:
        photos = PropertyPhoto.query.filter_by(property_id=prop.property_id).all()
        agent = User.query.filter_by(user_id = prop.agent_id).first()
        photo_list = [photo.photo_url for photo in photos]
        cover_photo = photo_list[0] if photo_list else None
        loved = UserFavorite.query.filter_by(user_id=user_id, property_id=prop.property_id).first()
        
        property_dict = {
            "property_id": prop.property_id,
            "title": prop.title,
            "description": prop.description,
            "address": prop.address,
            "price": prop.price,
            "property_type": prop.property_type,
            "bedrooms": prop.bedrooms,
            "bathrooms": prop.bathrooms,
            "area": prop.area,
            "agent": {
            "agent_id": agent.user_id,
            "profile_photo": agent.photo_url,
            "displayName": agent.first_name,
            },
            "seller_id": prop.seller_id,
            "latitude": prop.latitude,
            "longitude": prop.longitude,
            "tags": prop.tags,
            "cover_photo": cover_photo,
            "photos": photo_list,
            "timePosted": prop.created_at,
            "rue": prop.rue,
            "quartier": prop.quartier,
            "transaction_type": prop.transaction_type,
            "relevance_score": score,
            "hasLiked": True if loved else False
        }
        
        result.append(property_dict)

    response = {
        "properties": result,
        "total": total_properties,
        "pages": math.ceil(total_properties / per_page),
        "current_page": page
    }

    return jsonify(response), 200


 
@bp.route('/postprop', methods=['POST'])
def add_property():
    data = request.get_json()

    # Créer une nouvelle propriété
    new_property = Property(
        title=data['title'],
        description=data['description'],
        address=data['address'],
        price=data['price'],
        property_type=data['property_type'],
        bedrooms=data['bedrooms'],
        bathrooms=data['bathrooms'],
        area=data['area'],
        amenities=data['amenities'],
        agent_id=data.get('agent_id'),
        seller_id=data.get('seller_id'),
        latitude=data.get('latitude'),
        longitude=data.get('longitude'),
        transaction_type=data.get('selectedOption'),
        rue = data.get('rue'),
        quartier = data.get('quartier')
    )

    # Ajouter la nouvelle propriété à la base de données
    db.session.add(new_property)
    db.session.commit()

    # Appeler la fonction pour vérifier les alertes et notifier les utilisateurs
    check_alerts_and_notify(new_property)

    return jsonify({"message": "Property added successfully", "property_id": new_property.property_id}), 201



@bp.route('/property/<int:property_id>', methods=['GET'])
def get_property(property_id):
    user_id = request.args.get('user_id')
    property = Property.query.get_or_404(property_id)
    photos = PropertyPhoto.query.filter_by(property_id=property.property_id).all()
    photo_list = [f'{p.photo_url}' for p in photos]
    cover_photo = photo_list[0] if photo_list else None
    if user_id:
        loved = UserFavorite.query.filter_by(user_id=user_id, property_id=property_id).first()
    else:
        loved = False
    return jsonify({
        "property_id": property.property_id,
        "title": property.title,
        "description": property.description,
        "address": property.address,
        "price": property.price,
        "property_type": property.property_type,
        "bedrooms": property.bedrooms,
        "bathrooms": property.bathrooms,
        "area": property.area,
        "agent_id": property.agent_id,
        "seller_id": property.seller_id,
        "latitude": property.latitude,
        "longitude": property.longitude,
        "photos": photo_list,
        "cover_photo": cover_photo,
        "tags": property.tags,
        "transaction_type": property.transaction_type,
        "hasLiked": True if loved else False,
        "quartier": property.quartier,
        "rue": property.rue,
    }), 200

@bp.route('/property/<int:property_id>/photos', methods=['GET'])
def get_property_photos(property_id):
    photos = PropertyPhoto.query.filter_by(property_id=property_id).all()
    if not photos:
        return jsonify({"message": "No photos found for this property"}), 404

    # Obtenir la première photo comme couverture
    cover_photo = photos[0].photo_url if photos else None
    photo_list = [p.photo_url for p in photos]

    return jsonify({
        "cover_photo": f'/images/{cover_photo}',  # Assurez-vous que l'URL est correcte pour la couverture
        "photos": [f'/images/{photo_url}' for photo_url in photo_list]
    }), 200
    
#CREATE COMMERCIAL REVIEW
@bp.route('/add_commercial_review', methods=['POST'])
def add_review():
    data = request.get_json()

    # Extraction des données
    product_id = data.get('productID')
    user_id = data.get('userID')
    rating = data.get('rating')
    review_text = data.get('reviewText')

    # Vérification du produit
    product = CommercialProduct.query.get(product_id)
    if not product:
        return jsonify({"message": "No such product found"}), 404
    
    # Vérification de l'utilisateur
    user = User.query.get(user_id)
    if not user:
        return jsonify({"message": "User not found"}), 404
    
    # Création de la nouvelle revue
    new_review = CommercialProductReviews(
        id_user=user_id,
        id_product=product_id,
        rating=rating,
        review_text=review_text
    )
    
    # Ajout de la revue à la base de données
    db.session.add(new_review)
    db.session.commit()

    # Retourner une réponse valide après la création de la revue
    return jsonify({"message": "Review added successfully"}), 201

    
    
#READ COMMERCIAL REVIEWS

@bp.route('/commercial_reviews/<int:product_id>', methods=['GET'])
def get_reviews(product_id):
    product = CommercialProduct.query.get(product_id)
    if not product:
        return jsonify({"message": "Product not found"}), 404

    reviews = CommercialProductReviews.query.filter_by(id_product=product_id).all()
    if not reviews:
        return jsonify({"message": "No reviews found"}), 404

    # Créer une liste de dictionnaires pour chaque review
    reviews_data = []
    for review in reviews:
        reviews_data.append({
            "review_id": review.id_review,
            "product_id": review.id_product,
            "rating": review.rating,
            "reviewText": review.review_text,
            "user_id": review.id_user,
            "date": review.date_posted
        })

    return jsonify(reviews_data), 200

    
     
    
    
    

@bp.route('/transactions', methods=['POST'])
def create_transaction():
    data = request.get_json()
    new_transaction = Transaction(
        property_id=data['property_id'],
        buyer_id=data['buyer_id'],
        agent_id=data['agent_id'],
        sale_price=data['sale_price']
    )
    db.session.add(new_transaction)
    db.session.commit()
    return jsonify({"message": "Transaction created successfully"}), 201

@bp.route('/transactions/<int:transaction_id>', methods=['GET'])
def get_transaction(transaction_id):
    transaction = Transaction.query.get_or_404(transaction_id)
    return jsonify({
        "transaction_id": transaction.transaction_id,
        "property_id": transaction.property_id,
        "buyer_id": transaction.buyer_id,
        "agent_id": transaction.agent_id,
        "transaction_date": transaction.transaction_date,
        "sale_price": transaction.sale_price
    }), 200

@bp.route('/agents', methods=['GET'])
def get_agents():
    agents = Agent.query.all()
    return jsonify([{
        "agent_id": a.agent_id,
        "user_id": a.user_id,
        "agency_name": a.agency_name
    } for a in agents]), 200
    
@bp.route('/users/email/<string:email>', methods=['GET'])
def get_user_by_email(email):
    user = User.query.filter_by(email=email).first()  # Recherche l'utilisateur par e-mail
    if user is None:
        return jsonify({"message": "User not found"}), 404

    return jsonify({
        "user_id": user.user_id,
        "first_name": user.first_name,
        "phone_number": user.phone_number,
        "address": user.address,
        "role": user.role,
        "email": user.email,
        "profile_photo": user.photo_url
    }), 200
    
    
# Route pour obtenir les informations d'un utilisateur
@bp.route('/user/<string:user_id>/stats', methods=['GET'])
def get_user_stats(user_id):
    user = User.query.filter_by(user_id=user_id).first()

    if not user:
        return jsonify({'message': 'User not found'}), 404

    # Récupérer le nombre d'avis
    number_of_reviews = len(user.avis) if user.avis else 0
    # Récupérer le rating
    rating = user.rating
    # Récupérer le nombre de likes
    number_of_likes = user.likes
    # Récupérer le nombre de followers
    number_of_followers = len(user.followers) if user.followers else 0

    return jsonify({
        'user_id': user.user_id,
        'number_of_reviews': number_of_reviews,
        'rating': rating,
        'number_of_likes': number_of_likes,
        'number_of_followers': number_of_followers
    })


@bp.route('/users/<string:user_id>', methods=['GET'])
def get_user(user_id):
    user = User.query.get_or_404(user_id)
    return jsonify({
        "user_id": user.user_id,
        "first_name": user.first_name,
        "phone_number": user.phone_number,
        "address": user.address,
        "role": user.role,
        "email": user.email,
        "profile_photo": user.photo_url
    }), 200
    
@bp.route('/add_favorite', methods=['POST'])
def add_favorite():
    data = request.get_json()
    user_id = data['user_id'] 
    property_id = data.get('property_id')
    favorite_type = data['type']
    property_cover_photo = data['cover_photo']
    
    # Validation des données
    if not property_id:
        return jsonify({"message": "Property_id must be provided."}), 400

    if favorite_type == 'property':
        # Vérifier si déjà en favori
        existing_favorite = UserFavorite.query.filter_by(
            user_id=user_id,
            property_id=property_id
        ).first()

        if existing_favorite:
            return jsonify({"message": "Property already in favorites"}), 400

        # Créer le nouveau favori
        new_favorite = UserFavorite(user_id=user_id, property_id=property_id)
        new_notification = Notification(user_id= user_id, message='La propriété à été bien ajoutée à votre liste de favoris.', type='info', property_cover_photo = property_cover_photo)
        user_name = User.query.filter_by(user_id = user_id).first().first_name
        property_dict = Property.query.filter_by(property_id = property_id).first()
        property_location = property_dict.address
        property_title = property_dict.title
        property_poster = property_dict.agent_id
        second_notification = Notification(user_id= property_poster, message=f"<b>{user_name}</b> a aimé votre annonce à <b>{property_location}</b> : <i>{property_title}<i>", type='like_p', property_cover_photo = property_cover_photo)
        try:
            # Sauvegarder le favori
            db.session.add(new_favorite)
            db.session.add(new_notification)
            db.session.add(second_notification)
            db.session.commit()
            # Enregistrer la notification dans la BDD
            
            # Créer et envoyer la notification via SocketIO
            socketio.emit('notification_created', {
                'user_id': user_id,
                'message': f'La propriété a été ajoutée à vos favoris',
                'type': 'success'  
            })
            

            return jsonify({
                "message": f"{favorite_type.capitalize()} added to favorites"
            }), 201

        except Exception as e:
            db.session.rollback()
            return jsonify({
                "message": "Error adding to favorites",
                "error": str(e)
            }), 500
            
    else:
        return jsonify({
            "message": "Invalid type. Use 'property' or 'product'."
        }), 400



@bp.route('/images/<filename>', methods=['GET'])
def get_image(filename):
    return send_from_directory(PROPERTY_IMAGE_FOLDER, filename)

@bp.route('/shop_images/<filename>', methods=['GET'])
def get_shop__image(filename):
    return send_from_directory(SHOP_IMAGES_FOLDER, filename)

@bp.route('/products_images/<filename>', methods=['GET'])
def get_product_image(filename): 
    return send_from_directory(PRODUCT_IMAGE_FOLDER, filename)

@bp.route('/profiles_images/<filename>', methods=['GET'])
def get_profile_pic(filename):
    return send_from_directory(PROFILE_IMAGE_FOLDER, filename)

@bp.route('/videos/<filename>', methods=['GET'])
def get_video(filename):
    try:
        return send_from_directory(VIDEO_FOLDER, filename)
    except FileNotFoundError:
        return {'error': 'Video not found'}, 404

@bp.route('/favorites/<string:user_id>', methods=['GET'])
def get_favorites(user_id):
    favorites = UserFavorite.query.filter_by(user_id=user_id).all()
    favorite_property_ids = [f.property_id for f in favorites]
    return jsonify({"favorite_property_ids": favorite_property_ids}), 200

@bp.route('/logout', methods=['POST'])
def logout_user():
    session.clear()  # Supprime toutes les données de la session
    return jsonify({"message": "Logged out successfully"}), 200

@bp.route('/agent/<string:agent_id>/properties', methods=['GET'])
def get_properties_by_agent(agent_id):
    # Récupérer les propriétés pour l'agent spécifique
    properties = Property.query.filter_by(agent_id=agent_id).order_by(Property.created_at.desc()).limit(5)
    
    if not properties:
        return jsonify({"message": "No properties found for this agent"}), 404
    
    result = []
    for p in properties:
        # Obtenir les photos pour chaque propriété
        photos = PropertyPhoto.query.filter_by(property_id=p.property_id).all()
        photo_list = [f'{p.photo_url}' for p in photos]
        cover_photo = photo_list[0] if photo_list else None
        
        result.append({
            "property_id": p.property_id,
            "title": p.title,
            "description": p.description,
            "address": p.address,
            "price": p.price,
            "property_type": p.property_type,
            "bedrooms": p.bedrooms,
            "bathrooms": p.bathrooms,
            "area": p.area,
            "agent_id": p.agent_id,
            "seller_id": p.seller_id,
            "latitude": p.latitude,
            "longitude": p.longitude,
            "cover_photo": cover_photo,
            "photos": photo_list
        })
    
    return jsonify(result), 200

@bp.route('/property/<int:property_id>/add_photos', methods=['POST'])
def add_property_photos(property_id):
    if 'image_0' not in request.files:
        return jsonify({"message": "No images provided"}), 400

    # Récupérer toutes les images
    images = request.files
    filenames = []

    for key in images:
        file = images[key]
        if file and allowed_file(file.filename):  # Vérifiez si le type de fichier est autorisé
            # Générer un nom de fichier unique avec UUID
            unique_filename = f"{uuid.uuid4()}{os.path.splitext(file.filename)[1]}"
            image_path = os.path.join(PROPERTY_IMAGE_FOLDER, unique_filename)

            # Enregistrez l'image dans le répertoire
            file.save(image_path)

            # Ajoutez la photo à la base de données
            new_photo = PropertyPhoto(
                property_id=property_id,
                photo_url=unique_filename  # Enregistrez le nom unique dans la base de données
            )
            db.session.add(new_photo)
            filenames.append(unique_filename)

    db.session.commit()
    return jsonify({"message": "Photos added successfully", "filenames": filenames}), 201

@bp.route('/search_properties', methods=['POST'])
def search_properties():
    # Récupérer les paramètres de recherche du corps de la requête JSON
    data = request.json
    price_min = float(data.get('price_min')) if data.get('price_min') is not None else None
    price_max = float(data.get('price_max')) if data.get('price_max') is not None else None
    bedrooms = int(data.get('bedrooms')) if data.get('bedrooms') is not None else None
    bathrooms = int(data.get('bathrooms')) if data.get('bathrooms') is not None else None
    property_type = data.get('property_type')
    location = data.get('location')
    transaction_type = data.get('transaction_type')

    # Construire la requête de base avec jointures optimisées
    query = db.session.query(Property)\
        .outerjoin(Agent, Property.agent_id == Agent.agent_id)\
        .outerjoin(User, Agent.user_id == User.user_id)\
        .outerjoin(PropertyPhoto, Property.property_id == PropertyPhoto.property_id)

    # Filtres de base améliorés
    if price_min is not None:
        query = query.filter(Property.price >= price_min)
    if price_max is not None:
        query = query.filter(Property.price <= price_max)
    if bedrooms is not None:
        # Recherche inclusive pour les chambres (±1)
        query = query.filter(Property.bedrooms.between(bedrooms-1, bedrooms+1))
    if bathrooms is not None:
        # Recherche inclusive pour les salles de bain (±1)
        query = query.filter(Property.bathrooms.between(bathrooms-1, bathrooms+1))
    if property_type:
        query = query.filter(Property.property_type == property_type)
    if transaction_type:
        query = query.filter(Property.transaction_type == transaction_type)

    # Recherche avancée sur la localisation
    if location:
        location_search = f"%{location}%"
        location_filters = or_(
            Property.address.ilike(location_search),
            Property.rue.ilike(location_search),
            Property.quartier.ilike(location_search),
            # Recherche par mots-clés séparés
            *[Property.address.ilike(f"%{word}%") 
              for word in location.split() if len(word) > 2]
        )
        query = query.filter(location_filters)

    # Optimisation des performances
    query = query.options(
        db.joinedload(Property.agent),
        db.joinedload(Property.photos),
        db.joinedload(Property.agent).joinedload(Agent.user)
    )

    # Exécuter la requête
    properties = query.distinct().order_by(Property.created_at.desc()).limit(10).all()

    result = []
    for p in properties:
        # Obtenir les photos avec gestion des erreurs
        try:
            print('😁😁😁😁😁😁😁😁😁', p)
            photos = PropertyPhoto.query.filter_by(property_id=p.property_id).all()
            photo_list = [f'{photo.photo_url}' for photo in photos if photo and photo.photo_url]
            cover_photo = photo_list[0] if photo_list else None
        except Exception:
            photo_list = []
            cover_photo = None

        # Obtenir les informations de l'agent avec gestion des erreurs
        try:
            agent = p.agent_id
            print(agent)
            agent_user = User.query.filter_by(user_id=agent).first() if agent else None
            print(agent_user)
            
            agent_info = {
                "agent_id": agent,
                "agent_name": agent_user.first_name if agent_user else None,
                "agent_photo": agent_user.photo_url if agent_user else None,
                "agent_phone": agent_user.phone_number if agent_user else None,
                "agent_email": agent_user.email if agent_user else None,
            }  if agent_user else None
            print(agent_info)
        except Exception as e:
            agent_info = None
            print('Something happened', {str(e)})

        # Construire l'objet de réponse
        try:
            property_data = {
                "property_id": p.property_id,
                "title": p.title,
                "description": p.description,
                "address": p.address,
                "quartier": p.quartier,
                "price": float(p.price) if p.price else None,
                "property_type": p.property_type,
                "bedrooms": p.bedrooms,
                "bathrooms": p.bathrooms,
                "area": float(p.area) if p.area else None,
                "agent": agent_info,
                "seller_id": p.seller_id,
                "latitude": float(p.latitude) if p.latitude else None,
                "longitude": float(p.longitude) if p.longitude else None,
                "cover_photo": cover_photo,
                "photos": photo_list,
                "transaction_type": p.transaction_type,
                "timePosted": p.created_at
            }
            result.append(property_data)
        except Exception as e:
            continue  # Skip problematic properties but continue processing others

    # Trier les résultats par pertinence si une recherche par location est effectuée
    if location:
        result.sort(key=lambda x: fuzz.ratio(location.lower(), x['address'].lower()), reverse=True)
    print(result)
    return jsonify(result), 200



@bp.route('/filters', methods=['GET'])
def get_filters():
    # Récupérer les types de propriétés
    property_types = db.session.query(Property.property_type).distinct().all()
    property_types = [pt[0] for pt in property_types]  # Transformer en liste simple

    # Récupérer les plages de prix (vous pouvez adapter cela selon vos besoins)
    min_price = db.session.query(db.func.min(Property.price)).scalar()
    max_price = db.session.query(db.func.max(Property.price)).scalar()

    # Récupérer les nombres distincts de chambres et salles de bains
    bedrooms = db.session.query(Property.bedrooms).distinct().all()
    bedrooms = sorted([b[0] for b in bedrooms])  # Liste triée
    bathrooms = db.session.query(Property.bathrooms).distinct().all()
    bathrooms = sorted([b[0] for b in bathrooms])  # Liste triée

    filters = {
        "property_types": property_types,
        "min_price": min_price,
        "max_price": max_price,
        "bedrooms": bedrooms,
        "bathrooms": bathrooms
    }

    return jsonify(filters), 200

########   RECHERCHE DES PRODUITS COMMERCIAUX #########


# Route pour rechercher des produits
@bp.route('/api/products/search', methods=['GET'])
def search_products_api():
    query = request.args.get('q', '')
    filters = {
        'min_price': float(request.args.get('min_price', 0)),
        'max_price': float(request.args.get('max_price', 1000000)),
        'category': request.args.get('category'),
        'seller_id': request.args.get('seller_id'),
        'tags': request.args.getlist('tags'),
        'sort_by': request.args.get('sort_by', 'created_at'),
        'sort_order': request.args.get('sort_order', 'desc')
    }
    
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 20))
    
    # On récupère la query sans l'exécuter avec .all()
    products_query = search_products(query, filters)
    
    # Calcul du total et des pages
    total = products_query.count()
    pages = (total + per_page - 1) // per_page
    
    # Application de la pagination manuellement
    products = products_query.offset((page - 1) * per_page).limit(per_page).all()
    
    # Création du résultat avec les photos
    results = []
    for product in products:
        photos = CommercialProductPhoto.query.filter_by(commercial_product_id=product.product_id).all()
        photo_list = [p.photo_url for p in photos if p.photo_url]
        
        results.append({
            "product_id": product.product_id,
            "name": product.name,
            "description": product.description,
            "price": product.price,
            "category": product.category,
            "photos": photo_list,
            "is_active": product.is_active,
            "stock": product.stock,
        })
    
    response_data = {
        'products': results,
        'total': total,
        'pages': pages,
        'current_page': page
    }
    
    return jsonify(response_data), 200

def search_products(query, filters=None):
    """
    Fonction de recherche de produits avec filtres
    """
    # Base de la requête
    search = CommercialProduct.query.filter(CommercialProduct.is_active == True)
    
    # Recherche textuelle
    if query:
        search = search.filter(
            or_(
                CommercialProduct.name.ilike(f'%{query}%'),
                CommercialProduct.description.ilike(f'%{query}%'),
                CommercialProduct.category.ilike(f'%{query}%')
            )
        )

    # Application des filtres
    if filters:
        if 'min_price' in filters:
            search = search.filter(CommercialProduct.price >= filters['min_price'])
            
        if 'max_price' in filters:
            search = search.filter(CommercialProduct.price <= filters['max_price'])
            
        if 'category' in filters and filters['category']:
            search = search.filter(CommercialProduct.category == filters['category'])
            
        if 'seller_id' in filters and filters['seller_id']:
            search = search.filter(CommercialProduct.seller_id == filters['seller_id'])
            
        if 'tags' in filters and filters['tags']:
            for tag in filters['tags']:
                search = search.filter(CommercialProduct.tags.contains(tag))

    # Tri
    sort_by = filters.get('sort_by', 'created_at') if filters else 'created_at'
    sort_order = filters.get('sort_order', 'desc') if filters else 'desc'
    
    if sort_order == 'desc':
        search = search.order_by(getattr(CommercialProduct, sort_by).desc())
    else:
        search = search.order_by(getattr(CommercialProduct, sort_by).asc())

    return search  # Retourne la query au lieu des résultats

########    ALERTES PROPRIETES ###########

@bp.route('/set_property_alerts', methods=['POST'])
def set_property_alerts():
    data = request.json
    user_id = data.get('user_id')
    property_criteria = data.get('criteria')

    # Vérifier l'existence de l'utilisateur
    user = User.query.get(user_id)
    if not user:
        return jsonify({"message": "User not found"}), 404

    # Enregistrer les critères d'alerte dans la base de données
    new_alert = PropertyAlert(
        user_id=user_id,
        min_price=property_criteria.get('price_min'),
        max_price=property_criteria.get('price_max'),
        bedrooms=property_criteria.get('bedrooms'),
        bathrooms=property_criteria.get('bathrooms'),
        property_type=property_criteria.get('property_type'),
        location=property_criteria.get('location'),
        transaction_type=property_criteria.get('transaction_type')
    )
    db.session.add(new_alert)
    db.session.commit()

    return jsonify({"message": "Alert preferences saved successfully"}), 201

@bp.route('/check_new_matching_properties', methods=['POST'])
def check_new_matching_properties():
    """
    Cette route vérifie les nouvelles propriétés correspondant aux critères des utilisateurs
    et envoie des alertes par email.
    """
    # Récupérer la nouvelle propriété
    new_property = request.json

    # Récupérer toutes les alertes actives
    alerts = PropertyAlert.query.filter_by(active=True).all()

    for alert in alerts:
        matches = True

        # Vérifier si la propriété correspond aux critères de l'alerte
        if alert.min_price and new_property['price'] < alert.min_price:
            matches = False
        if alert.max_price and new_property['price'] > alert.max_price:
            matches = False
        if alert.bedrooms and new_property['bedrooms'] != alert.bedrooms:
            matches = False
        if alert.bathrooms and new_property['bathrooms'] != alert.bathrooms:
            matches = False
        if alert.property_type and new_property['property_type'] != alert.property_type:
            matches = False
        if alert.location and alert.location.lower() not in new_property['address'].lower():
            matches = False
        if alert.transaction_type and new_property['transaction_type'] != alert.transaction_type:
            matches = False

        if matches:
            # Récupérer l'utilisateur
            user = User.query.get(alert.user_id)

            # Envoyer l'email d'alerte
            if user and user.email:
                try:
                    msg = Message(
                        'Nouvelle propriété exclusive correspondant à vos critères',
                        sender='services.logysma@gmail.com',
                        recipients=[user.email]
                    )
                    msg.html = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <meta charset="UTF-8">
                        <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    </head>
                    <body style="margin: 0; padding: 0; font-family: 'Arial', sans-serif; background-color: #f5f5f5;">
                        <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; padding: 20px;">
                            <div style="text-align: center; padding: 20px 0; border-bottom: 2px solid #f0f0f0;">
                                <img src="https://votre-site.com/logo.png" alt="Logysma Logo" style="max-width: 200px; height: auto;">
                            </div>
                            <div style="padding: 30px 20px;">
                                <h1 style="color: #2c3e50; font-size: 24px; margin-bottom: 20px; text-align: center;">
                                    ✨ Découvrez votre nouveau bien idéal ✨
                                </h1>
                                <p style="color: #666; font-size: 16px; line-height: 1.6; margin-bottom: 25px;">
                                    Cher(e) client(e),<br><br>
                                    Nous avons le plaisir de vous informer qu'une nouvelle propriété correspondant parfaitement à vos critères vient d'être mise en ligne.
                                </p>
                                <div style="background-color: #f8f9fa; border-radius: 10px; padding: 20px; margin-bottom: 25px;">
                                    <h2 style="color: #2c3e50; font-size: 20px; margin-bottom: 15px;">
                                        {new_property['title']}
                                    </h2>
                                    <div style="margin-bottom: 15px;">
                                        <p style="color: #e74c3c; font-size: 24px; font-weight: bold; margin: 0;">
                                            {new_property['price']:,.2f} €
                                        </p>
                                    </div>
                                    <div style="margin-bottom: 15px;">
                                        <p style="color: #7f8c8d; margin: 0;">
                                            📍 {new_property['address']}
                                        </p>
                                    </div>
                                    <div style="margin-bottom: 20px;">
                                        <p style="color: #666; line-height: 1.6; margin: 0;">
                                            {new_property['description']}
                                        </p>
                                    </div>
                                    <div style="text-align: center;">
                                        <a href="https://votre-site.com/properties/{new_property['property_id']}" 
                                           style="display: inline-block; padding: 12px 30px; background-color: #3498db; 
                                                  color: #ffffff; text-decoration: none; border-radius: 5px; 
                                                  font-weight: bold; transition: background-color 0.3s ease;">
                                            Voir la propriété
                                        </a>
                                    </div>
                                </div>
                                <p style="color: #666; font-size: 14px; line-height: 1.6;">
                                    Notre équipe reste à votre disposition pour organiser une visite ou répondre à vos questions.
                                </p>
                            </div>
                            <div style="text-align: center; padding-top: 30px; border-top: 2px solid #f0f0f0;">
                                <p style="color: #999; font-size: 12px;">
                                    © 2024 Logysma. Tous droits réservés.<br>
                                    123 Avenue des Champs-Élysées, 75008 Paris
                                </p>
                                <div style="margin-top: 15px;">
                                    <a href="https://facebook.com/logysma" style="text-decoration: none; margin: 0 10px;">
                                        <img src="https://votre-site.com/images/facebook-icon.png" alt="Facebook" style="width: 24px; height: 24px;">
                                    </a>
                                    <a href="https://instagram.com/logysma" style="text-decoration: none; margin: 0 10px;">
                                        <img src="https://votre-site.com/images/instagram-icon.png" alt="Instagram" style="width: 24px; height: 24px;">
                                    </a>
                                    <a href="https://linkedin.com/company/logysma" style="text-decoration: none; margin: 0 10px;">
                                        <img src="https://votre-site.com/images/linkedin-icon.png" alt="LinkedIn" style="width: 24px; height: 24px;">
                                    </a>
                                </div>
                                <p style="color: #999; font-size: 12px; margin-top: 15px;">
                                    Si vous ne souhaitez plus recevoir nos emails, <a href="https://votre-site.com/unsubscribe?email={user.email}" style="color: #3498db; text-decoration: none;">cliquez ici</a>
                                </p>
                            </div>
                        </div>
                    </body>
                    </html>
                    """
                    mail.send(msg)
                except Exception as e:
                    print(f"Erreur lors de l'envoi de l'email: {str(e)}")

    return jsonify({"message": "Alerts checked and notifications sent"}), 200

def check_alerts_and_notify(new_property):
    # Récupérer toutes les alertes actives
    alerts = PropertyAlert.query.filter_by(active=True).all()

    for alert in alerts:
        matches = True
        
        # Vérifier si la propriété correspond aux critères de l'alerte
        #if alert.min_price and new_property.price < alert.min_price:
        #    matches = False
        #if alert.max_price and new_property.price > alert.max_price:
        #   matches = False
        #if alert.bedrooms and new_property.bedrooms != alert.bedrooms:
        #    matches = False
        #if alert.bathrooms and new_property.bathrooms != alert.bathrooms:
        #    matches = False
        #if alert.property_type and new_property.property_type != alert.property_type:
        #    #matches = False
        #if alert.location and alert.location.lower() not in new_property.address.lower():
        #    #matches = False
        #if alert.transaction_type and new_property.transaction_type != alert.transaction_type:
        #    matches = False

        if matches:
            # Récupérer l'utilisateur
            user = User.query.get(alert.user_id)
            
            if user :
                # Envoyer l'email d'alerte#user.email:
                try:
                    msg = Message(
                        'Nouvelle propriété correspondant à vos critères',
                        sender='services.logysma@gmail.com',
                        recipients=['azonezechiel7@gmail.com']
                    )
                    msg.html = f"""
                    <h2>Une nouvelle propriété correspond à vos critères !</h2>
                    <p><strong>Titre:</strong> {new_property.title}</p>
                    <p><strong>Prix:</strong> {new_property.price}€</p>
                    <p><strong>Adresse:</strong> {new_property.address}</p>
                    <p><strong>Description:</strong> {new_property.description}</p>
                    <p><a href="votre-site.com/properties/{new_property.property_id}">
                        Voir la propriété
                    </a></p>
                    """
                    mail.send(msg)
                except Exception as e:
                    print(f"Erreur lors de l'envoi de l'email: {str(e)}")

    return jsonify({"message": "Alerts checked and notifications sent"}), 200


@bp.route('/add_commercial_product', methods=['POST'])
def add_commercial_product():
    data = request.get_json()

    # Vérification de la présence des données essentielles
    if not data.get('name') or not data.get('price') or not data.get('category'):
        return jsonify({"message": "Name, price, and category are required"}), 400

    # Création du nouveau produit commercial
    new_product = CommercialProduct(
        name=data['name'],
        description=data.get('description'),
        price=data['price'],
        category=data['category'],
        stock=data.get('stock_quantity', 0),
        seller_id=data.get('seller_id')  # Optionnel, selon la structure de vos utilisateurs
    )

    # Enregistrement dans la base de données
    db.session.add(new_product)
    db.session.commit()

    return jsonify({"message": "Commercial product added successfully", "product_id": new_product.product_id}), 201




@bp.route('/commercial_products', methods=['GET'])
def get_commercial_products():
    try:
        # Récupérer les produits commerciaux, classés par ID décroissant (du plus récent au plus ancien)
        commercial_products = CommercialProduct.query.order_by(CommercialProduct.product_id.desc()).limit(20).all()
        logging.info(f'Commercial products retrieved: {commercial_products}')
        
        result = []
        for product in commercial_products:
            # Obtenir les photos pour chaque produit commercial
            photos = CommercialProductPhoto.query.filter_by(commercial_product_id=product.product_id).all()
            photo_list = [p.photo_url for p in photos if p.photo_url]  # Vérifiez que photo_url est valide
            
            result.append({
                "product_id": product.product_id,  # Utilisez 'product_id' ici
                "name": product.name,
                "description": product.description,
                "price": product.price,
                "category": product.category,
                "photos": photo_list  # Liste des URLs des photos
            })

        logging.info(f'Resulting product data: {result}')
        return jsonify(result), 200

    except Exception as e:
        logging.error(f'Error retrieving commercial products: {str(e)}')
        return jsonify({'error': 'Erreur lors de la récupération des produits'}), 500

@bp.route('/upload_product_images', methods=['POST'])
def upload_product_images():
    if 'product_id' not in request.form:
        return jsonify({'error': 'product_id is required'}), 400

    product_id = request.form['product_id']

    # Vérifier si des fichiers ont été envoyés
    if 'images' not in request.files:
        return jsonify({'error': 'No images provided'}), 400

    image_files = request.files.getlist('images')
    image_urls = []

    # Sauvegarde des images et création de leurs liens
    for file in image_files:
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = os.path.join(PRODUCT_IMAGE_FOLDER, filename)
            file.save(file_path)
            
            # Créer un lien relatif ou chemin d'accès aux images
            image_url = f'/{filename}'  # Modifiez ceci selon votre configuration de routes
            image_urls.append(image_url)

            # Sauvegarder l'URL de l'image dans la base de données
            new_image = CommercialProductPhoto(commercial_product_id=product_id, photo_url=image_url)
            db.session.add(new_image)

    # Commit des changements
    db.session.commit()

    return jsonify({'message': 'Images uploaded successfully!', 'image_urls': image_urls}), 201


@bp.route('/property/<int:property_id>/reviews', methods=['GET'])
def get_property_reviews(property_id):
    # Vérifier si la propriété existe
    property = Property.query.get(property_id)
    if not property:
        return jsonify({"message": "Property not found"}), 404

    # Récupérer tous les avis associés à cette propriété
    reviews = PropertyReview.query.filter_by(property_id=property_id).all()
    def get_reviewer_info(review):
        user_info = User.query.get(review.user_id)
        if user_info:
            user_dict = {
                "user_name": user_info.first_name,
                "user_email": user_info.email,
                "user_photo": user_info.photo_url,
                "role": user_info.role
            }  
        else:
            user_dict = None
        return user_dict 

    # Formater les avis en une liste de dictionnaires
    reviews_list = [{
        "user_id": review.user_id,
        "user_dict": get_reviewer_info(review),
        "rating": review.rating,
        "review_text": review.review_text,
        "date": review.review_date.strftime('%Y-%m-%d')  # Assurez-vous d'utiliser le format de date souhaité
    } for review in reviews]
    print(reviews_list)
    return jsonify({"reviews": reviews_list}), 200


@bp.route('/commercial_products/<int:commercial_product_id>/details', methods=['GET'])
def get_product_details(commercial_product_id):
    try:
        # Vérifier si le produit existe
        product = CommercialProduct.query.get_or_404(commercial_product_id)
        
        # Obtenir les photos associées au produit
        photos = CommercialProductPhoto.query.filter_by(commercial_product_id=product.product_id).all()
        photo_list = [p.photo_url for p in photos if p.photo_url]  # Vérifiez que photo_url est valide

        # Retourner les détails du produit, y compris les photos
        return jsonify({
            "productID": product.product_id,
            "name": product.name,
            "category": product.category,
            "description": product.description,
            "sellerID": product.seller_id,
            "price": product.price,
            "stock": product.stock,
            "is_active": product.is_active,
            "tags": product.tags,
            "photos": photo_list,  # Liste des URLs des photos
            "rating": 2
        }), 200

    except Exception as e:
        logging.error(f'Error retrieving product details: {str(e)}')
        return jsonify({'error': 'Erreur lors de la récupération des détails du produit'}), 500

@bp.route('/videos', methods=['GET'])
def get_videos():
    # Récupérer les paramètres pour la pagination
    page = request.args.get('page', 1, type=int)  # Numéro de la page, par défaut 1
    per_page = request.args.get('n', 10, type=int)  # Nombre de vidéos à récupérer par page, par défaut 10
    user_id = request.args.get('user_id', None)  # Récupérer l'ID de l'utilisateur, si disponible

    # Récupérer les vidéos avec pagination
    videos_paginated = Video.query.paginate(page=page, per_page=per_page, error_out=False)

    # Liste de vidéos à retourner
    videos = []
    for video in videos_paginated.items:
        # Vérifier si l'utilisateur a liké la vidéo
        if user_id:
            liked = VideoLike.query.filter_by(user_id=user_id, video_id=video.id).first() is not None
        else:
            liked = False

        videos.append({
            'id': video.id,
            'user_id': video.user_id,
            'video_url': video.video_url,
            'thumbnail_url': video.thumbnail_url,
            'caption': video.caption,
            'created_at': video.created_at,
            'updated_at': video.updated_at,
            'likes': video.likes,
            'comments_count': video.comments_count,
            'views_count': video.views_count,
            'product_id': video.product_id,
            'price': str(video.price),  # Conversion en chaîne de caractères pour JSON
            'currency': video.currency,
            'stock': video.stock,
            'transaction_id': video.transaction_id,
            'purchase_count': video.purchase_count,
            'liked': liked  # Ajouter le statut "liked" pour cette vidéo
        })

    # Retourner les données avec le statut de la pagination
    return jsonify({
        'videos': videos,
        'total_pages': videos_paginated.pages,
        'current_page': videos_paginated.page,
        'total_items': videos_paginated.total
    })
    
    


@bp.route('/videos/<int:video_id>/like', methods=['POST'])
def like_video(video_id):
    user_id = request.json.get('user_id')
    action = request.json.get('action', 'like')  # 'like' or 'unlike'

    # Vérifier si la vidéo existe
    video = Video.query.get(video_id)
    if not video:
        return jsonify({'error': 'Video not found'}), 404

    # Vérifier si l'utilisateur existe
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Vérifier l'action à effectuer : 'like' ou 'unlike'
    if action == 'like':
        # Vérifier si l'utilisateur a déjà liké cette vidéo
        existing_like = VideoLike.query.filter_by(user_id=user_id, video_id=video_id).first()
        if existing_like:
            return jsonify({'message': 'You have already liked this video'}), 400
        
        # Ajouter le like
        new_like = VideoLike(user_id=user_id, video_id=video_id)
        db.session.add(new_like)
        video.likes += 1  # Incrémenter le compteur de likes
        db.session.commit()

        return jsonify({'message': 'Video liked successfully', 'likes': video.likes}), 200
    
    elif action == 'unlike':
        # Vérifier si l'utilisateur a liké cette vidéo
        existing_like = VideoLike.query.filter_by(user_id=user_id, video_id=video_id).first()
        if not existing_like:
            return jsonify({'message': 'You have not liked this video yet'}), 400

        # Supprimer le like
        db.session.delete(existing_like)
        video.likes -= 1  # Décrémenter le compteur de likes
        db.session.commit()

        return jsonify({'message': 'Video unliked successfully', 'likes': video.likes}), 200
    
    else:
        return jsonify({'error': 'Invalid action'}), 400

@bp.route('/property/<int:property_id>/average_rating', methods=['GET'])
def get_property_average_rating(property_id):
    # Vérifier si la propriété existe
    property = Property.query.get(property_id)
    if not property:
        return jsonify({"message": "Property not found"}), 404

    # Récupérer tous les avis associés à cette propriété
    reviews = PropertyReview.query.filter_by(property_id=property_id).all()

    # Compter le nombre d'avis
    number_of_reviews = len(reviews)

    if number_of_reviews == 0:
        return jsonify({"average_rating": 0.0, "number_of_reviews": 0}), 200

    # Calculer la moyenne des ratings
    total_ratings = sum(review.rating for review in reviews)
    average_rating = total_ratings / number_of_reviews

    return jsonify({
        "average_rating": round(average_rating, 2),
        "number_of_reviews": number_of_reviews
    }), 200






@bp.route('/upload_pfimage', methods=['POST']) 
def upload_file():
    if 'image' not in request.files:
        return jsonify({'error': 'image is required'}), 400
    
    file = request.files['image']
    user_id = request.form.get('user_id')  # Récupérer user_id de manière sûre

    if file.filename == '':
        return 'No selected file', 400

    if isinstance(file, str):
        return 'Invalid file format', 400

    if file:
        # Générer un nom de fichier unique avec UUID
        unique_filename = f"{uuid.uuid4()}{os.path.splitext(file.filename)[1]}"
        file_path = os.path.join(PROFILE_IMAGE_FOLDER, unique_filename)

        try:
            file.save(file_path) 
        except Exception as e: 
            return jsonify({'error': f"Error saving file: {str(e)}"}), 500

        # Mettre à jour l'utilisateur avec l'URL de l'image
        user = User.query.filter_by(user_id=user_id).first()
        if user:
            user.photo_url = unique_filename  # Mettre à jour le champ pfimage
            db.session.commit()

            return jsonify({'message': 'File successfully uploaded and database updated'}), 200
        else:
            return jsonify({'error': 'User not found'}), 404

    return jsonify({'error': 'File upload failed'}), 400


@bp.route('/property/<int:property_id>/add_review', methods=['POST'])
def add_property_review(property_id):
    data = request.get_json()

    # Vérifier si la propriété existe
    property = Property.query.get(property_id)
    if not property:
        return jsonify({"message": "Property not found"}), 404

    # Vérifier si l'utilisateur existe
    user_id = data.get('user_id')
    user_name = User.query.filter_by(user_id = user_id).first().first_name
    property_location = Property.query.filter_by(property_id = property_id).first().address
    property_photos = PropertyPhoto.query.filter_by(property_id=property_id).all()
    photo_list = [f'{photo.photo_url}' for photo in property_photos if photo and photo.photo_url]
    property_cover_photo = photo_list[0] if photo_list else None
    print(property_cover_photo)
    # user = User.query.get(user_id)
    # if not user:
    #    return jsonify({"message": "User not found"}), 404
    
    poster_id = property.agent_id
 
    # Créer le nouvel avis
    new_review = PropertyReview(
        property_id=property_id,
        user_id=user_id,
        rating=data.get('rating'),
        review_text=data.get('review_text')
    )

    # Ajouter l'avis à la base de données
    send_notification = Notification(user_id= poster_id, message=f"<b>{user_name}</b> a évalué votre anonnce à {property_location} : <b><i>`{data.get('review_text')}`</i></b>", type='reviewing', property_cover_photo = property_cover_photo)
    db.session.add(new_review)
    db.session.add(send_notification)
    db.session.commit()

    return jsonify({"message": "Review added successfully", "review_id": new_review.review_id}), 201



@bp.route('/remove_favorite', methods=['POST'])
def remove_favorite():
    data = request.get_json()
    user_id = data.get('user_id')
    property_id = data.get('property_id')

    # Vérifier si le favori existe
    favorite = UserFavorite.query.filter_by(user_id=user_id, property_id=property_id).first()
    if not favorite:
        return jsonify({"message": "Favorite not found"}), 404

    # Supprimer le favori
    db.session.delete(favorite)
    db.session.commit()
    return jsonify({"message": "Property removed from favorites"}), 200


@bp.route('/create_store', methods=['POST'])
def create_store():
    data = request.form

    # Gérer les fichiers d'image (logo et cover_image)
    logo_file = request.files.get('logo')
    cover_image_file = request.files.get('coverImage')

    logo_filename = None
    cover_image_filename = None

    # Validation des fichiers
    if not logo_file and logo_file.filename:
        return jsonify({'error': 'Logo file is required'}), 400

    if cover_image_file and cover_image_file.filename == '':
        return jsonify({'error': 'Cover image file is required'}), 400

    # Sauvegarde du logo avec un UUID comme nom de fichier
    if logo_file:
        if isinstance(logo_file, str):  # Vérification si le fichier est valide
            return jsonify({'error': 'Invalid logo file format'}), 400

        logo_ext = os.path.splitext(logo_file.filename)[1]  # Obtenir l'extension du fichier
        logo_filename = f"{uuid.uuid4()}{logo_ext}"  # Générer un nom de fichier unique avec UUID
        try:
            logo_file.save(os.path.join(SHOP_IMAGES_FOLDER, secure_filename(logo_filename)))
        except Exception as e:
            return jsonify({'error': f"Error saving logo file: {str(e)}"}), 500

    # Sauvegarde de l'image de couverture avec un UUID comme nom de fichier
    if cover_image_file:
        if isinstance(cover_image_file, str):  # Vérification si le fichier est valide
            return jsonify({'error': 'Invalid cover image file format'}), 400

        cover_image_ext = os.path.splitext(cover_image_file.filename)[1]  # Obtenir l'extension du fichier
        cover_image_filename = f"{uuid.uuid4()}{cover_image_ext}"  # Générer un nom de fichier unique avec UUID
        try:
            cover_image_file.save(os.path.join(SHOP_IMAGES_FOLDER, secure_filename(cover_image_filename)))
        except Exception as e:
            return jsonify({'error': f"Error saving cover image file: {str(e)}"}), 500

    # Création d'une nouvelle instance de Shop avec les fichiers enregistrés
    new_store = Shop(
        user_id=data.get('user_id'),
        logo=logo_filename,  # Enregistrer le nom du fichier généré
        cover_image=cover_image_filename,  # Enregistrer le nom du fichier généré
        shop_name=data.get('name'),
        shop_description=data.get('description'),
        category_id=data.get('category'),
        subcategory=data.get('subcategory'),
        shop_address=data.get('address'),
        map_location=data.get('location'),  # Assuming location is a JSON object
        shop_phone=data.get('phone'),
        shop_email=data.get('email'),
        website=data.get('website')
    )

    try:
        db.session.add(new_store)
        db.session.commit()
        return jsonify({"message": "Store created successfully!", "store": new_store.to_dict(), "store_id": new_store.shop_id}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500



@bp.route('/get_shop/<int:shop_id>', methods=['GET'])
def get_shop(shop_id):
     shop = Shop.query.get(shop_id)
     if shop:
        return jsonify({
            'shop_id': shop.shop_id,
            'user_id': shop.user_id,
            'category_id': shop.category_id,
            'shop_name': shop.shop_name,
            'logoUrl': shop.logo,
            'shop_description': shop.shop_description,
            'shop_address': shop.shop_address,
            'shop_city': shop.shop_city,
            'shop_country': shop.shop_country,
            'shop_phone': shop.shop_phone,
            'shop_email': shop.shop_email,
            'created_at': shop.created_at,
            'updated_at': shop.updated_at,
            'cover_image': shop.cover_image
        })
     return {'message': 'Shop not found'}, 404


############### GESTION DES MESSAGES ####################

# Gestion de la connexion avec l'ID utilisateur envoyé par le front-end
@socketio.on('user_connected')
def handle_user_connected(data):
    user_id = data['user_id']
    if user_id:
        join_room(user_id)
        # Stocker l'association entre l'ID de socket et l'ID utilisateur
        socket_id = request.sid
        user_socket_map[socket_id] = user_id
        print(f"User {user_id} connected and joined private room {user_id}.")
    else:
        print("No user_id provided")
  

@socketio.on('disconnect')
def handle_disconnect():
    socket_id = request.sid
    if socket_id in user_socket_map:
        user_id = user_socket_map[socket_id]
        del user_socket_map[socket_id]
        print(f"User {user_id} disconnected")
    else:
        print("Unknown user disconnected")
  

@socketio.on('start_conversation')
def handle_start_conversation(data):
    user1_id = data['user1_id']
    user2_id = data['user2_id']
    conversation_id = f"{min(user1_id, user2_id)}_{max(user1_id, user2_id)}"
    
    join_room(conversation_id)
    emit('conversation_started', {'conversation_id': conversation_id}, room=conversation_id)
    print(f"Conversation {conversation_id} started between {user1_id} and {user2_id}")

@socketio.on('send_conversation_message')
def handle_send_conversation_message(data):
    sender_id = data['sender_id']
    conversation_id = data['conversation_id']
    message = data['message']
    receiver_id = data['receiver_id']

    # Vérifier si la conversation existe
    conversation = Conversation.query.get(conversation_id)

    # Si la conversation n'existe pas, la créer
    if not conversation:
        conversation = Conversation(conversation_id=conversation_id)
        db.session.add(conversation)
        db.session.commit()
        print(f"New conversation {conversation_id} created.")

    # Enregistrer le message dans la base de données
    new_message = MessageModel(
        sender_id=sender_id,
        receiver_id=receiver_id,
        conversation_id=conversation_id,
        message_content=message
    )
    db.session.add(new_message)
    db.session.commit()

    # Envoyer le message à la salle de conversation
    emit('receive_conversation_message', {
        'sender_id': sender_id,
        'message': message,
        'receiver_id': receiver_id,  # Ajoutez le receiver_id ici
        'timestamp': new_message.sent_at.strftime('%Y-%m-%d %H:%M:%S')
    }, room=conversation_id)

    print(f"Message sent in conversation {conversation_id} by {sender_id}")


# Gérer le départ d'une salle
@socketio.on('leave')
def on_leave(data):
    """
    Gérer le départ d'un utilisateur d'une salle.
    """
    room = data['room']
    leave_room(room)
    emit('status', {'msg': f'User has left the room: {room}'}, room=room)

@socketio.on('send_notification')
def handle_send_notification(data):
    user_id = data['user_id']
    notification = data['notification']
    if user_id:
        emit('receive_notification', {'notification': notification}, room=user_id)
        print(f"Notification envoyée à l'utilisateur {user_id}: {notification}")
    else: 
        print("Aucun user_id fourni pour l'envoi de la notification.")


######### GESTION DES NOTIFICATIONS ########


@socketio.on('create_notification')
def create_notification(data):
    """Créer une nouvelle notification"""
    try:
        # Extraire les données
        user_id = data.get('user_id')
        message = data.get('message')
        notification_type = data.get('type', 'info')
        
        # Émettre la notification au client
        room = f"user_{user_id}"
        emit('notification_created', {
            'type': notification_type,
        }, room=room)

        return True

    except Exception as e:
        print(f"Erreur lors de la création de la notification: {str(e)}")
        emit('notification_error', {'message': 'Erreur lors de la création'})
        return False



@socketio.on('count_unread')
def count_unread(data):
    """Compter les non lues"""
    try:
        user_id = data.get(('user_id'))
        unReadCount= Notification.query.filter_by(user_id=user_id,is_read= False).count()
        emit('unread_count', unReadCount)
        return True
    except Exception as e:
        print(f"Erreur lors de la lecture des notifications non lues: {str(e)}")
        emit('notification_error', {'message': 'Erreur lors de la lecture des non lues'})
        return False


@socketio.on('read_notifications')
def read_notifications(data):
    """Lire les notifications d'un utilisateur"""
    try:
        user_id = data.get('user_id')
        notifications = Notification.query.filter_by(user_id=user_id).order_by(Notification.created_at.desc()).limit(10)
        unReadCount= Notification.query.filter_by(user_id=user_id,is_read= False).count()
        
        notifications_list = [{
            'id': notif.id,
            'message': notif.message,
            'type': notif.type,
            'is_read': notif.is_read,
            'property_cover_photo': notif.property_cover_photo,
            'created_at': notif.created_at.isoformat()
        } for notif in notifications]

        emit('notifications_list', notifications_list)
        return True

    except Exception as e:
        print(f"Erreur lors de la lecture des notifications: {str(e)}")
        emit('notification_error', {'message': 'Erreur lors de la lecture'})
        return False

@socketio.on('update_notification')
def update_notification(data):
    """Mettre à jour une notification"""
    try:
        notification_id = data.get('notification_id')
        is_read = data.get('is_read', True)

        notification = Notification.query.get(notification_id)
        if notification:
            notification.is_read = is_read
            db.session.commit()

            room = f"user_{notification.user_id}"
            emit('notification_updated', {
                'id': notification.id,
                'is_read': notification.is_read
            }, room=room)
            return True
        return False

    except Exception as e:
        print(f"Erreur lors de la mise à jour de la notification: {str(e)}")
        emit('notification_error', {'message': 'Erreur lors de la mise à jour'})
        return False

@socketio.on('delete_notification')
def delete_notification(data):
    """Supprimer une notification"""
    try:
        notification_id = data.get('notification_id')
        notification = Notification.query.get(notification_id)
        
        if notification:
            user_id = notification.user_id
            db.session.delete(notification)
            db.session.commit()

            room = f"user_{user_id}"
            emit('notification_deleted', {
                'id': notification_id
            }, room=room)
            return True
        return False

    except Exception as e:
        print(f"Erreur lors de la suppression de la notification: {str(e)}")
        emit('notification_error', {'message': 'Erreur lors de la suppression'})
        return False

@bp.route('/get_conversation_messages/<conversation_id>', methods=['GET'])
def get_conversation_messages(conversation_id):
    messages = MessageModel.query.filter_by(conversation_id=conversation_id).order_by(MessageModel.sent_at).all()  # Assurez-vous d'utiliser le bon champ pour l'ordre
    message_list = [{
        'message_id': msg.message_id,  # Ajout de l'ID du message
        'sender_id': msg.sender_id,
        'message': msg.message_content,  # Assurez-vous d'utiliser le bon attribut pour le contenu
        'timestamp': msg.sent_at.strftime('%Y-%m-%d %H:%M:%S')
    } for msg in messages]

    return {'messages': message_list}, 200



@bp.route('/get_user_conversations/<user_id>', methods=['GET'])
def get_user_conversations(user_id):
    # Trouver les conversations où l'utilisateur est impliqué en tant qu'expéditeur ou recepteur
    conversations = db.session.query(MessageModel.conversation_id).filter(
        or_(MessageModel.sender_id == user_id, MessageModel.receiver_id == user_id)
    ).distinct().all()

    conversation_list = []

    for conv in conversations:
        conversation_id = conv[0]

        # Récupérer le dernier message de la conversation
        last_message = MessageModel.query.filter_by(conversation_id=conversation_id).order_by(MessageModel.sent_at.desc()).first()

        if last_message:
            # Identifier l'autre utilisateur
            other_user_id = db.session.query(MessageModel.sender_id).filter(
                MessageModel.conversation_id == conversation_id,
                MessageModel.sender_id != user_id
            ).distinct().first()

            # Vérifier si other_user_id est valide
            if not other_user_id:
                continue

            other_user_id = other_user_id[0]  # Extraire l'ID réel

            # Récupérer l'autre utilisateur
            other_user = User.query.filter_by(user_id=other_user_id).first()

            # Calculer les messages non lus
            unread_messages = MessageModel.query.filter_by(
                conversation_id=conversation_id,
                sender_id=other_user_id,
            ).filter(MessageModel.status != 'read').count()

            conversation_list.append({
                'id': conversation_id,
                'name': other_user.first_name if other_user else 'Unknown',  # Utilisateur inconnu si l'autre utilisateur n'existe pas
                'photo': other_user.photo_url if other_user else None,  # Photo de profil de l'autre utilisateur
                'lastMessage': last_message.message_content,
                'time': last_message.sent_at.strftime('%Y-%m-%d %H:%M:%S'),
                'unread': unread_messages,
                'otherUserId': other_user.user_id if other_user else None
            })

    return {'conversations': conversation_list}, 200




def init_routes(app):
    app.register_blueprint(bp)

####################  MANAGING SHOPS ############################

@bp.route('/categories', methods=['GET'])
def get_categories():
    categories = Category.query.all()
    return jsonify([{
        'category_id': category.category_id,
        'category_name': category.category_name,
        'category_description': category.category_description
    } for category in categories])

@bp.route('/categories/<int:category_id>', methods=['GET'])
def get_category(category_id):
    category = Category.query.get(category_id)
    if category:
        return jsonify({
            'category_id': category.category_id,
            'category_name': category.category_name,
            'category_description': category.category_description
        })
    return {'message': 'Category not found'}, 404

@bp.route('/categories', methods=['POST'])
def create_category():
    data = request.json
    new_category = Category(
        category_name=data['category_name'],
        category_description=data.get('category_description', '')
    )
    db.session.add(new_category)
    db.session.commit()
    return {'message': 'Category created', 'category_id': new_category.category_id}, 201

@bp.route('/categories/<int:category_id>', methods=['PUT'])
def update_category(category_id):
    data = request.json
    category = Category.query.get(category_id)
    if category:
        category.category_name = data['category_name']
        category.category_description = data.get('category_description', category.category_description)
        db.session.commit()
        return {'message': 'Category updated'}
    return {'message': 'Category not found'}, 404

@bp.route('/categories/<int:category_id>', methods=['DELETE'])
def delete_category(category_id):
    category = Category.query.get(category_id)
    if category:
        db.session.delete(category)
        db.session.commit()
        return {'message': 'Category deleted'}
    return {'message': 'Category not found'}, 404

@bp.route('/shops', methods=['GET'])
def get_shops():
    shops = Shop.query.all()
    return jsonify([{
        'shop_id': shop.shop_id,
        'user_id': shop.user_id,
        'logoUrl': shop.logo,
        'cover_image': shop.cover_image,
        'category_id': shop.category_id,
        'shop_name': shop.shop_name,
        'shop_description': shop.shop_description,
        'shop_address': shop.shop_address,
        'shop_city': shop.shop_city,
        'shop_country': shop.shop_country,
        'shop_phone': shop.shop_phone,
        'shop_email': shop.shop_email,
        'created_at': shop.created_at,
        'updated_at': shop.updated_at
    } for shop in shops])

@bp.route('/shops/<int:shop_id>', methods=['GET'])
def get_shop_i(shop_id):
    shop = Shop.query.get(shop_id)
    if shop:
        return jsonify({
            'shop_id': shop.shop_id,
            'user_id': shop.user_id,
            'category_id': shop.category_id,
            'shop_name': shop.shop_name,
            'logoUrl': shop.logo,
            'cover_image': shop.cover_image,
            'shop_description': shop.shop_description,
            'shop_address': shop.shop_address,
            'shop_city': shop.shop_city,
            'shop_country': shop.shop_country,
            'shop_phone': shop.shop_phone,
            'shop_email': shop.shop_email,
            'created_at': shop.created_at,
            'updated_at': shop.updated_at
        })
    return {'message': 'Shop not found'}, 404

@bp.route('/shops', methods=['POST'])
def create_shop():
    data = request.json
    new_shop = Shop(
        user_id=data['user_id'],
        category_id=data.get('category_id'),
        shop_name=data['shop_name'],
        shop_description=data.get('shop_description', ''),
        shop_address=data.get('shop_address', ''),
        shop_city=data.get('shop_city', ''),
        shop_country=data.get('shop_country', ''),
        shop_phone=data.get('shop_phone', ''),
        shop_email=data.get('shop_email', '')
    )
    db.session.add(new_shop)
    db.session.commit()
    return {'message': 'Shop created', 'shop_id': new_shop.shop_id}, 201

@bp.route('/shops/<int:shop_id>', methods=['PUT'])
def update_shop(shop_id):
    data = request.json
    shop = Shop.query.get(shop_id)
    if shop:
        shop.category_id = data.get('category_id', shop.category_id)
        shop.shop_name = data['shop_name']
        shop.shop_description = data.get('shop_description', shop.shop_description)
        shop.shop_address = data.get('shop_address', shop.shop_address)
        shop.shop_city = data.get('shop_city', shop.shop_city)
        shop.shop_country = data.get('shop_country', shop.shop_country)
        shop.shop_phone = data.get('shop_phone', shop.shop_phone)
        shop.shop_email = data.get('shop_email', shop.shop_email)
        db.session.commit()
        return {'message': 'Shop updated'}
    return {'message': 'Shop not found'}, 404

@bp.route('/shops/<int:shop_id>', methods=['DELETE'])
def delete_shop(shop_id):
    shop = Shop.query.get(shop_id)
    if shop:
        db.session.delete(shop)
        db.session.commit()
        return {'message': 'Shop deleted'}
    return {'message': 'Shop not found'}, 404

########### GESTION DE LA COLOCATION ###############

@bp.route('/colocation', methods=['POST'])
def create_colocation():
    try:
        data = request.get_json()
        new_colocation = Colocation(
            poster_id=data['poster_id'],
            description=data['description'],
            location=data['location'],
            images_urls=data['images_urls'],
            tags=data['tags'],
            colocator_preferences=data['colocator_preferences'],
            requirements=data.get('requirements', {}),
            boosted=data.get('boosted', False),
            status=data.get('status', True),
            post_tags=data.get('post_tags', {})
        )
        db.session.add(new_colocation)
        db.session.commit()
        return jsonify({
            "message": "Colocation offer created successfully",
            "colocation_id": new_colocation.colocation_id
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400

# READ - Get all colocation offers
@bp.route('/colocations', methods=['GET'])
def get_colocations():
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        query = Colocation.query
        if request.args.get('location'):
            query = query.filter(Colocation.location.ilike(f"%{request.args.get('location')}%"))
        if request.args.get('status'):
            status = request.args.get('status').lower() == 'true'
            query = query.filter(Colocation.status == status)
        if request.args.get('boosted'):
            boosted = request.args.get('boosted').lower() == 'true'
            query = query.filter(Colocation.boosted == boosted)
        paginated_colocations = query.paginate(page=page, per_page=per_page, error_out=False)
        colocations = [{
            "colocation_id": c.colocation_id,
            "poster_id": c.poster_id,
            "description": c.description,
            "location": c.location,
            "images_urls": c.images_urls,
            "tags": c.tags,
            "colocator_preferences": c.colocator_preferences,
            "requirements": c.requirements,
            "boosted": c.boosted,
            "status": c.status,
            "post_tags": c.post_tags
        } for c in paginated_colocations.items]
        return jsonify({
            "colocations": colocations,
            "total": paginated_colocations.total,
            "pages": paginated_colocations.pages,
            "current_page": page
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# READ - Get single colocation offer
@bp.route('/colocation/', methods=['GET'])
def get_colocation(colocation_id):
    try:
        colocation = Colocation.query.get_or_404(colocation_id)
        return jsonify({
            "colocation_id": colocation.colocation_id,
            "poster_id": colocation.poster_id,
            "description": colocation.description,
            "location": colocation.location,
            "images_urls": colocation.images_urls,
            "tags": colocation.tags,
            "colocator_preferences": colocation.colocator_preferences,
            "requirements": colocation.requirements,
            "boosted": colocation.boosted,
            "status": colocation.status,
            "post_tags": colocation.post_tags
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 404

# UPDATE - Update colocation offer
@bp.route('/colocation/', methods=['PUT'])
def update_colocation(colocation_id):
    try:
        colocation = Colocation.query.get_or_404(colocation_id)
        data = request.get_json()
        if 'description' in data:
            colocation.description = data['description']
        if 'location' in data:
            colocation.location = data['location']
        if 'images_urls' in data:
            colocation.images_urls = data['images_urls']
        if 'tags' in data:
            colocation.tags = data['tags']
        if 'colocator_preferences' in data:
            colocation.colocator_preferences = data['colocator_preferences']
        if 'requirements' in data:
            colocation.requirements = data['requirements']
        if 'boosted' in data:
            colocation.boosted = data['boosted']
        if 'status' in data:
            colocation.status = data['status']
        if 'post_tags' in data:
            colocation.post_tags = data['post_tags']
        db.session.commit()
        return jsonify({"message": "Colocation offer updated successfully"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400

# DELETE - Delete colocation offer
@bp.route('/colocation/', methods=['DELETE'])
def delete_colocation(colocation_id):
    try:
        colocation = Colocation.query.get_or_404(colocation_id)
        db.session.delete(colocation)
        db.session.commit()
        return jsonify({"message": "Colocation offer deleted successfully"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400

# Search colocations
@bp.route('/search_colocations', methods=['POST'])
def search_colocations():
    try:
        data = request.get_json()
        query = Colocation.query
        if data.get('location'):
            query = query.filter(Colocation.location.ilike(f"%{data['location']}%"))
        if data.get('tags'):
            for tag in data['tags']:
                query = query.filter(Colocation.tags.contains([tag]))
        if 'status' in data:
            query = query.filter(Colocation.status == data['status'])
        if data.get('preferences'):
            query = query.filter(Colocation.colocator_preferences.ilike(f"%{data['preferences']}%"))
        colocations = query.all()
        result = [{
            "colocation_id": c.colocation_id,
            "poster_id": c.poster_id,
            "description": c.description,
            "location": c.location,
            "images_urls": c.images_urls,
            "tags": c.tags,
            "colocator_preferences": c.colocator_preferences,
            "requirements": c.requirements,
            "boosted": c.boosted,
            "status": c.status,
            "post_tags": c.post_tags
        } for c in colocations]
        return jsonify({
            "results": result,
            "count": len(result)
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    
    ###############  DEMANDES DE PROPRIETES ##############
    
@bp.route('/property-requests', methods=['POST'])
def create_property_request():
    try:
        data = request.get_json()
        
        # Convert the start date string to a proper date object
        start_date = None
        if data.get('start_date'):
            start_date = datetime.strptime(data['start_date'].split('T')[0], '%Y-%m-%d')

        new_request = PropertyRequest(
            request_id=str(uuid.uuid4()),
            user_id=data.get('user_id'),
            property_type=data.get('property_type'),
            bedrooms=data.get('rooms'),  # Changed from bedrooms to rooms to match frontend
            bathrooms=data.get('bathrooms'),
            surface_area=data.get('surface_area'),
            location=data.get('location'),
            budget_amount=data.get('budget_amount'),
            budget_currency=data.get('budget_currency', 'XOF'),
            additional_fees_accepted=data.get('additional_fees_accepted', False),
            contract_type=data.get('contract_type', 'long_term'),
            start_date=start_date,
            amenities=data.get('amenities', []),  # Will be stored as JSON
            nearby_services=data.get('nearby_services', []),  # Will be stored as JSON
            user_verified=data.get('user_verified', False),
            user_activity_history=data.get('user_activity_history'),
            occupation=data.get('occupation', ''),
            family_status=data.get('family_status', ''),
            request_reason=data.get('request_reason', ''),
            hide_contact_info=data.get('hide_contact_info', False)
        )
        
        db.session.add(new_request)
        db.session.commit()
        
        return jsonify({
            "message": "Property request created successfully",
            "request_id": new_request.request_id
        }), 201
        
    except Exception as e:
        db.session.rollback()
        print(f"Error creating property request: {str(e)}")
        return jsonify({
            "error": "Failed to create property request",
            "details": str(e)
        }), 500
        
        
        
@bp.route('/property-requests', methods=['GET'])
def get_all_property_requests():
    requests = PropertyRequest.query.order_by(PropertyRequest.created_at.desc()).limit(12)
    result = []
    for req in requests:
        user = User.query.get_or_404(req.user_id)
        images = [
            proposal.images[0] if proposal.images else None
            for proposal in Proposal.query.filter_by(request_id = req.request_id).order_by(Proposal.created_at.desc()).limit(10).all()
        ]
        
        result.append({
            "request_id": req.request_id,
            "user_id": req.user_id,
            "property_type": req.property_type,
            "bedrooms": req.bedrooms,
            "bathrooms": req.bathrooms,
            "surface_area": req.surface_area,
            "location": req.location,
            "budget_amount": float(req.budget_amount) if req.budget_amount else None,
            "budget_currency": req.budget_currency,
            "additional_fees_accepted": req.additional_fees_accepted,
            "contract_type": req.contract_type,
            "start_date": req.start_date,
            "created_at": req.created_at,
            "updated_at": req.updated_at,
            "description": req.request_reason,
            "images": images,
            # Ajouter les informations de l'utilisateur
        "user": {
            "user_id": user.user_id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "photo_url": user.photo_url,
            "phone_number": user.phone_number,
            "address": user.address,
            "role": user.role,
            "created_at": user.created_at,
            "updated_at": user.updated_at
        }
        })
    return jsonify(result), 200


@bp.route('/property-requests/<string:request_id>', methods=['GET'])
def get_property_request(request_id):
    # Récupérer la demande de propriété avec les informations de l'utilisateur
    req = PropertyRequest.query.get_or_404(request_id)
    user = User.query.get_or_404(req.user_id)

    return jsonify({
        "request_id": req.request_id,
        "user_id": req.user_id,
        "property_type": req.property_type,
        "bedrooms": req.bedrooms,
        "bathrooms": req.bathrooms,
        "surface_area": req.surface_area,
        "location": req.location,
        "budget_amount": float(req.budget_amount) if req.budget_amount else None,
        "budget_currency": req.budget_currency,
        "additional_fees_accepted": req.additional_fees_accepted,
        "contract_type": req.contract_type,
        "start_date": req.start_date,
        "created_at": req.created_at,
        "updated_at": req.updated_at,
        # Ajouter les informations de l'utilisateur
        "user": {
            "user_id": user.user_id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "photo_url": user.photo_url,
            "phone_number": user.phone_number,
            "address": user.address,
            "role": user.role,
            "created_at": user.created_at,
            "updated_at": user.updated_at
        }
    }), 200
    

@bp.route('/api/users/qr/<string:user_id>', methods=['GET'])
def generate_user_qr(user_id):
    # Récupérer l'utilisateur depuis la base de données
    user = User.query.filter_by(user_id=user_id).first()
    if not user:
        return jsonify({"message": "User not found"}), 404

    # Créer l'URL vers le profil de l'utilisateur
    profile_url = f"http://yourapp.com/profile/{user_id}"  # Remplacez par l'URL réelle de votre profil

    # Générer le QR Code
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(profile_url)
    qr.make(fit=True)

    # Créer l'image du QR Code
    img_qr = qr.make_image(fill='black', back_color='white')

    # Ouvrir l'image du logo
    logo = Image.open("logo.png")

    # Convertir le logo en mode RGBA (si ce n'est pas déjà le cas)
    logo = logo.convert("RGBA")

    # Redimensionner le logo pour qu'il s'adapte au QR Code
    logo_size = int(img_qr.size[0] / 6)  # Le logo sera un cinquième de la taille du QR Code
    logo = logo.resize((logo_size, logo_size))

    # Ajouter un padding autour du logo avec un fond blanc
    padding = 10  # Taille du padding autour du logo (en pixels)
    background_size = (logo.size[0] + 2 * padding, logo.size[1] + 2 * padding)
    background = Image.new("RGBA", background_size, (255, 255, 255, 255))  # Fond blanc plus large
    background.paste(logo, (padding, padding), mask=logo)  # Coller le logo au centre avec du padding

    # Calculer la position pour placer le logo (avec padding) au centre du QR code
    pos = ((img_qr.size[0] - background.size[0]) // 2, (img_qr.size[1] - background.size[1]) // 2)

    # Ajouter le logo avec le fond blanc et padding sur le QR Code
    img_qr.paste(background, pos, mask=background)

    # Convertir l'image en un format qui peut être renvoyé dans la réponse HTTP
    img_io = io.BytesIO()
    img_qr.save(img_io, 'PNG')
    img_io.seek(0)

    # Retourner l'image comme une réponse HTTP
    return send_file(img_io, mimetype='image/png')


@bp.route('/create_proposal', methods=['POST'])
def create_proposal():
    # Récupérer les données textuelles du formulaire
    title = request.form.get('title')
    price_offer = request.form.get('price_offer')
    location = request.form.get('location')
    bedrooms = request.form.get('bedrooms')
    description = request.form.get('description')
    poster_id = request.form.get('poster_id')
    user_id = request.form.get('user_id')
    property_id = request.form.get('property_id')
    request_id = request.form.get('request_id')

    # Convertir 'null' ou une valeur vide en None pour éviter l'erreur
    if property_id == 'null' or not property_id:
        property_id = None
    else:
        # Assurez-vous que property_id est un entier valide si ce n'est pas None
        property_id = int(property_id)

    # Initialiser la liste des noms de fichiers pour les images
    filenames = []

    # Gestion des images : si des fichiers sont fournis
    if 'images' in request.files:
        images = request.files.getlist('images')
        for file in images:
            if file and allowed_file(file.filename):
                # Générer un nom unique pour chaque image
                unique_filename = f"{uuid.uuid4()}{os.path.splitext(file.filename)[1]}"
                image_path = os.path.join(PROPERTY_IMAGE_FOLDER, unique_filename)

                # Sauvegarder l'image dans le dossier
                file.save(image_path)

                # Ajouter le nom de fichier à la liste des images
                filenames.append(unique_filename)

    # Créer une nouvelle proposition avec les images stockées dans la colonne JSON
    new_proposal = Proposal(
        property_id=property_id,
        user_id=user_id,
        price_offer=price_offer,
        title=title,
        description=description,
        location=location,
        bedrooms=bedrooms,
        request_id=request_id,
        bathrooms=request.form.get('bathrooms'),
        surface_area=request.form.get('surface_area'),
        status='pending',  # Par défaut
        images=filenames  # Liste des noms des images
    )

    # Ajouter la proposition à la base de données
    db.session.add(new_proposal)
    db.session.commit()

    # Récupérer le nom de l'utilisateur qui a fait la proposition
    poster = User.query.filter_by(user_id=user_id).first()
    if poster:
        poster_name = f"{poster.first_name}"
    else:
        poster_name = "Utilisateur inconnu"  # Au cas où l'utilisateur ne serait pas trouvé

    # Créer la notification
    cover_photo = filenames[0] if filenames else None  # Utiliser la première image comme couverture
    new_notification = Notification(
        user_id=poster_id, 
        message=f"<b>{poster_name}</b> vous a fait une nouvelle proposition. Cliquez pour voir !",
        type='proposal', 
        property_cover_photo=cover_photo
    )

    # Créer et envoyer la notification via SocketIO
    socketio.emit('notification_created', {
        'user_id': poster_id,
        'message': f'Nouvelle proposition de logement',
        'type': 'success'
    })

    # Ajouter la notification à la base de données
    db.session.add(new_notification)
    db.session.commit()

    return jsonify({
        "message": "Proposal added successfully", 
        "proposal_id": new_proposal.proposal_id, 
        "filenames": filenames
    }), 201



# **READ** : Récupérer toutes les propositions ou une seule
@bp.route('/get_proposals', methods=['GET'])
def get_proposals():
    # Si un `proposal_id` est passé en paramètre, retourner cette proposition
    proposal_id = request.args.get('proposal_id')

    if proposal_id:
        proposal = Proposal.query.get(proposal_id)
        if proposal:
            user = User.query.get(proposal.user_id)
            return jsonify({
                "proposal_id": proposal.proposal_id,
                "property_id": proposal.property_id,
                "user_id": proposal.user_id,
                "user": {
                "user_id": user.user_id,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "email": user.email,
                "photo_url": user.photo_url,
                "phone_number": user.phone_number,
                "address": user.address,
                "role": user.role,
                "created_at": user.created_at,
                "updated_at": user.updated_at
                    },
                "request_id": proposal.request_id,
                "price_offer": float(proposal.price_offer),
                "title": proposal.title,
                "description": proposal.description,
                "location": proposal.location,
                "bedrooms": proposal.bedrooms,
                "bathrooms": proposal.bathrooms,
                "surface_area": float(proposal.surface_area) if proposal.surface_area else None,
                "images": proposal.images,
                "status": proposal.status,
                "created_at": proposal.created_at,
                "updated_at": proposal.updated_at
            }), 200
        else:
            return jsonify({"error": "Proposal not found"}), 404

    # Sinon, retourner toutes les propositions
    proposals = Proposal.query.all()
    result = []
    for proposal in proposals:
        result.append({
            "proposal_id": proposal.proposal_id,
            "property_id": proposal.property_id,
            "user_id": proposal.user_id,
            "request_id": proposal.request_id,
            "price_offer": float(proposal.price_offer),
            "title": proposal.title,
            "description": proposal.description,
            "location": proposal.location,
            "bedrooms": proposal.bedrooms,
            "bathrooms": proposal.bathrooms,
            "surface_area": float(proposal.surface_area) if proposal.surface_area else None,
            "images": proposal.images,
            "status": proposal.status,
            "created_at": proposal.created_at,
            "updated_at": proposal.updated_at
        })

    return jsonify(result), 200


# **READ** : Récupérer toutes les propositions ou une seule
@bp.route('/get_request_proposals', methods=['GET'])
def get_request_proposals():
    # Si un `proposal_id` est passé en paramètre, retourner cette proposition
    request_id = request.args.get('request_id')
    proposals_list = []

    if request_id:
        proposals = Proposal.query.filter_by(request_id = request_id).order_by(Proposal.created_at).all()      
        if proposals:
            for psl in proposals:
                proposals_list.append({
                'proposal_id' : psl.proposal_id,
                'property_id' : psl.property_id,
                'user_id' : psl.user_id,
                'request_id' : psl.request_id,
                'price_offer' : psl.price_offer,
                'title' : psl.title,
                'description' : psl.description, 
                'location' : psl.location,
                'bedrooms' : psl.bedrooms,
                'bathrooms' : psl.bathrooms,
                'surface_area' : psl.surface_area,
                'images' : psl.images,
                'status' : psl.status,
                'created_at' : psl.created_at,
             }) 
        else:
            print('Aucune proposition trouvée pour cette demande')
            return {'message': 'no proposal'}, 404
        
        return jsonify(proposals_list), 200
        
    else:
        return jsonify({"error": "No request"}), 404

# Route pour ajouter un avis à un utilisateur
@bp.route('/user/<string:user_id>/avis', methods=['POST'])
def add_avis(user_id):
    user = User.query.filter_by(user_id=user_id).first()
    if not user:
        return jsonify({'message': 'User not found'}), 404

    new_avis = request.json.get('avis')
    user.avis.append(new_avis)
    db.session.commit()

    return jsonify({'message': 'Avis ajouté avec succès', 'avis': user.avis})

# Route pour mettre à jour le rating d'un utilisateur
@bp.route('/user/<string:user_id>/rating', methods=['PUT'])
def update_rating(user_id):
    user = User.query.filter_by(user_id=user_id).first()
    if not user:
        return jsonify({'message': 'User not found'}), 404

    new_rating = request.json.get('rating')
    if new_rating is not None:
        user.rating = new_rating
        db.session.commit()
        return jsonify({'message': 'Rating mis à jour', 'rating': user.rating})
    return jsonify({'message': 'Rating invalide'}), 400

# Route pour mettre à jour les likes d'un utilisateur
@bp.route('/user/<string:user_id>/likes', methods=['PUT'])
def update_likes(user_id):
    user = User.query.filter_by(user_id=user_id).first()
    if not user:
        return jsonify({'message': 'User not found'}), 404

    new_likes = request.json.get('likes')
    if new_likes is not None:
        user.likes = new_likes
        db.session.commit()
        return jsonify({'message': 'Likes mis à jour', 'likes': user.likes})
    return jsonify({'message': 'Likes invalide'}), 400

# Route pour ajouter un follower à un utilisateur
@bp.route('/user/<string:user_id>/followers', methods=['POST'])
def add_follower(user_id):
    user = User.query.filter_by(user_id=user_id).first()
    if not user:
        return jsonify({'message': 'User not found'}), 404
    
    new_follower = request.json.get('follower')
    print(new_follower)
    if not new_follower:
        return jsonify({'message': 'No follower data provided'}), 400  # Code 400 pour mauvaise requête
    
    check = User.query.filter_by(user_id=new_follower).first()
    if not check:
        print('Follower not found')
        return jsonify({'message': 'Follower not found'}), 404
    
    # Vérification si le follower existe déjà dans la liste des followers
    if new_follower in user.followers:
        return jsonify({'message': 'Follower already exists'}), 400  # Code 400 si déjà follower
    
    print(user.followers)
    print(new_follower)
    user.followers += [new_follower]  # Ajouter l'ID du follower à la liste
    print(user.followers)
    user_name = User.query.filter_by(user_id = new_follower).first().first_name
    user_profil_pic = User.query.filter_by(user_id = new_follower).first().photo_url
    send_notification = Notification(user_id= user_id, message=f"<b>{user_name}</b> a suivi votre profil !", type='following', property_cover_photo = user_profil_pic)
    try:
        db.session.add(send_notification)
        db.session.commit()
        print(user.followers)
        print('Follower ajouté avec succès')
    
        # Retourner la liste des followers sous forme d'IDs
        return jsonify({'message': 'Follower ajouté', 'followers': user.followers}), 200
    
    except Exception as e:
        db.session.rollback()
        print(f"Error following user: {str(e)}")
        return jsonify({
            "error": "Failed to follow user",
            "details": str(e)
        }), 500
        



# Route pour supprimer un follower d'un utilisateur
@bp.route('/user/<string:user_id>/followers', methods=['DELETE'])
def remove_follower(user_id):
    user = User.query.filter_by(user_id=user_id).first()
    if not user:
        return jsonify({'message': 'User not found'}), 404

    follower_to_remove = request.json.get('follower')
    if follower_to_remove in user.followers:
        user.followers.remove(follower_to_remove)
        db.session.commit()
        return jsonify({'message': 'Follower supprimé', 'followers': user.followers})
    return jsonify({'message': 'Follower introuvable'}), 404