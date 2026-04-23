import os
import sys
from structlog import get_logger

# Add current directory to sys.path to allow importing from server
sys.path.append(os.getcwd())

from server.db import init_database, ShopTable, transactional
from server.settings import app_settings

logger = get_logger(__name__)

def update_stripe_keys():
    # Ensure database is initialized
    db = init_database(app_settings)
    
    stripe_public_key = os.getenv("STRIPE_TEST_PUBLIC_KEY")
    stripe_secret_key = os.getenv("STRIPE_TEST_SECRET_KEY")
    
    if not stripe_public_key or not stripe_secret_key:
        print("Error: STRIPE_TEST_PUBLIC_KEY or STRIPE_TEST_SECRET_KEY not found in environment.")
        sys.exit(1)
        
    print(f"Updating all shops with test Stripe keys...")
    
    with db.database_scope():
        with transactional(db, logger):
            session = db.session
            shops = session.query(ShopTable).all()
            for shop in shops:
                shop.stripe_public_key = stripe_public_key
                shop.stripe_secret_key = stripe_secret_key
                print(f"Updated shop: {shop.name} ({shop.id})")

if __name__ == "__main__":
    update_stripe_keys()
