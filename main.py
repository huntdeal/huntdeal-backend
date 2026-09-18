from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
from pathlib import Path


def calculate_deal_score(discount, rating, review_count, price, lowest_price, history_count):
    """
    Calculate HuntDeal Score out of 100.

    Score:
    - Discount: 35 points
    - Rating: 25 points
    - Reviews: 15 points
    - Price history: 25 points
    """

    discount = float(discount or 0)
    rating = float(rating or 0)
    review_count = int(review_count or 0)
    price = float(price or 0)
    lowest_price = float(lowest_price or 0)
    history_count = int(history_count or 0)

    # -----------------------------
    # Discount score: 35 points
    # -----------------------------
    discount_score = min(discount / 70 * 35, 35)

    # -----------------------------
    # Rating score: 25 points
    # -----------------------------
    rating_score = min(rating / 5 * 25, 25)

    # -----------------------------
    # Review confidence: 15 points
    # -----------------------------
    if review_count >= 10000:
        review_score = 15
    elif review_count >= 5000:
        review_score = 13
    elif review_count >= 1000:
        review_score = 11
    elif review_count >= 500:
        review_score = 9
    elif review_count >= 100:
        review_score = 7
    elif review_count >= 10:
        review_score = 4
    else:
        review_score = 1

    # -----------------------------
    # Price history: 25 points
    # -----------------------------
    if history_count >= 2 and lowest_price > 0 and price > 0:

        if price <= lowest_price:
            history_score = 25
        else:
            price_ratio = lowest_price / price
            history_score = max(0, min(price_ratio * 25, 25))

    else:
        # Not enough history yet
        history_score = 12.5

    total_score = round(
        discount_score
        + rating_score
        + review_score
        + history_score
    )

    return total_score

def get_deal_label(score):
    """
    Convert HuntDeal Score into a simple label.
    """

    if score >= 85:
        return "Excellent Deal"

    if score >= 70:
        return "Strong Deal"

    if score >= 55:
        return "Good Deal"

    if score >= 40:
        return "Fair Deal"

    return "Weak Deal"

def get_price_intelligence(price, lowest_price, previous_price, history_count):
    """
    Analyze current price against tracked price history.
    """

    price = float(price or 0)
    lowest_price = float(lowest_price or 0)
    previous_price = (
        float(previous_price)
        if previous_price is not None
        else None
    )
    history_count = int(history_count or 0)

    result = {
        "lowest_price": lowest_price,
        "previous_price": previous_price,
        "price_difference": 0,
        "percent_above_lowest": 0,
        "price_change_percent": 0,
        "is_lowest_price": False,
        "price_trend": "Unknown"
    }

    # No useful price data
    if price <= 0:
        return result

    # ---------------------------------------------
    # Compare with lowest tracked price
    # ---------------------------------------------

    if lowest_price > 0:

        result["price_difference"] = round(
            price - lowest_price,
            2
        )

        if price <= lowest_price:
            result["is_lowest_price"] = True
            result["percent_above_lowest"] = 0
        else:
            result["percent_above_lowest"] = round(
                ((price - lowest_price) / lowest_price) * 100,
                2
            )

    # ---------------------------------------------
    # Compare with previous recorded price
    # ---------------------------------------------

    if previous_price is not None and previous_price > 0:

        change_percent = (
            (price - previous_price)
            / previous_price
        ) * 100

        result["price_change_percent"] = round(
            change_percent,
            2
        )

        if price < previous_price:
            result["price_trend"] = "Falling"

        elif price > previous_price:
            result["price_trend"] = "Rising"

        else:
            result["price_trend"] = "Stable"

    elif history_count >= 1:
        result["price_trend"] = "Stable"

    return result

# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

DB_PATH = BASE_DIR / "database" / "huntdeal.db"

if not DB_PATH.exists():
    DB_PATH = BASE_DIR.parent / "database" / "huntdeal.db"


# ============================================================
# FASTAPI APP
# ============================================================

app = FastAPI(
    title="HuntDeal API",
    description="Deal aggregation API for HuntDeal",
    version="1.0.0"
)


# ============================================================
# CORS
# ============================================================

# Allows our future frontend to communicate with this API.

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_connection():
    """
    Create a connection to HuntDeal SQLite database.
    """

    if not DB_PATH.exists():
        raise HTTPException(
            status_code=500,
            detail="HuntDeal database not found."
        )

    conn = sqlite3.connect(DB_PATH)

    # Return rows as dictionaries
    conn.row_factory = sqlite3.Row

    return conn


# ============================================================
# ROOT ENDPOINT
# ============================================================

@app.get("/")
def home():

    return {
        "message": "Welcome to HuntDeal API",
        "status": "running",
        "version": "1.0.0"
    }


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/api/health")
def health_check():

    return {
        "status": "healthy",
        "database": DB_PATH.exists()
    }


# ============================================================
# GET ALL DEALS
# ============================================================

@app.get("/api/deals")
def get_deals():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            p.asin,
            p.title,
            p.brand,
            p.category,
            p.price,
            p.mrp,
            p.discount_percent,
            p.rank,
            p.rating,
            p.review_count,
            p.image_url,
            p.created_at,
            p.updated_at,

            (
                SELECT MIN(ph.price)
                FROM price_history ph
                WHERE ph.asin = p.asin
            ) AS lowest_price,

            (
                SELECT COUNT(*)
                FROM price_history ph
                WHERE ph.asin = p.asin
            ) AS history_count,

            (
                SELECT ph.price
                FROM price_history ph
                WHERE ph.asin = p.asin
                ORDER BY ph.recorded_at DESC
                LIMIT 1 OFFSET 1
            ) AS previous_price

        FROM products p
        ORDER BY p.discount_percent DESC
    """)

    rows = cursor.fetchall()
    conn.close()

    deals = []

    for row in rows:

        lowest_price = row["lowest_price"]
        history_count = row["history_count"]
        previous_price = row["previous_price"]

        # Calculate HuntDeal Score
        deal_score = calculate_deal_score(
            discount=row["discount_percent"],
            rating=row["rating"],
            review_count=row["review_count"],
            price=row["price"],
            lowest_price=lowest_price,
            history_count=history_count
        )

        # Get deal label
        deal_label = get_deal_label(deal_score)

        # Analyze price
        price_intelligence = get_price_intelligence(
            price=row["price"],
            lowest_price=lowest_price,
            previous_price=previous_price,
            history_count=history_count
        )

        deals.append({
            "asin": row["asin"],
            "title": row["title"],
            "brand": row["brand"],
            "category": row["category"],
            "price": row["price"],
            "mrp": row["mrp"],
            "discount_percent": row["discount_percent"],
            "rank": row["rank"],
            "rating": row["rating"],
            "review_count": row["review_count"],
            "image_url": row["image_url"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],

            # HuntDeal Score
            "deal_score": deal_score,
            "deal_label": deal_label,

            # Price Intelligence
            "lowest_price": price_intelligence["lowest_price"],
            "previous_price": price_intelligence["previous_price"],
            "price_difference": price_intelligence["price_difference"],
            "percent_above_lowest": price_intelligence["percent_above_lowest"],
            "price_change_percent": price_intelligence["price_change_percent"],
            "is_lowest_price": price_intelligence["is_lowest_price"],
            "price_trend": price_intelligence["price_trend"],

            "history_count": history_count
        })

    return {
        "count": len(deals),
        "deals": deals
    }


# ============================================================
# GET SINGLE PRODUCT
# ============================================================

@app.get("/api/products/{asin}")
def get_product(asin: str):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            asin,
            title,
            brand,
            category,
            price,
            mrp,
            discount_percent,
            rank,
            rating,
            review_count,
            image_url,
            created_at,
            updated_at
        FROM products
        WHERE asin = ?
    """, (asin,))

    row = cursor.fetchone()

    conn.close()

    if row is None:

        raise HTTPException(
            status_code=404,
            detail="Product not found."
        )

    return {
        "asin": row["asin"],
        "title": row["title"],
        "brand": row["brand"],
        "category": row["category"],
        "price": row["price"],
        "mrp": row["mrp"],
        "discount_percent": row["discount_percent"],
        "rank": row["rank"],
        "rating": row["rating"],
        "review_count": row["review_count"],
        "image_url": row["image_url"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"]
    }


# ============================================================
# GET PRICE HISTORY
# ============================================================

@app.get("/api/products/{asin}/history")
def get_price_history(asin: str):

    conn = get_connection()

    cursor = conn.cursor()

    # First check whether product exists
    cursor.execute("""
        SELECT asin
        FROM products
        WHERE asin = ?
    """, (asin,))

    product = cursor.fetchone()

    if product is None:

        conn.close()

        raise HTTPException(
            status_code=404,
            detail="Product not found."
        )

    # Get historical prices
    cursor.execute("""
        SELECT
            price,
            mrp,
            recorded_at
        FROM price_history
        WHERE asin = ?
        ORDER BY recorded_at ASC
    """, (asin,))

    rows = cursor.fetchall()

    conn.close()

    history = []

    for row in rows:

        history.append({
            "price": row["price"],
            "mrp": row["mrp"],
            "recorded_at": row["recorded_at"]
        })

    return {
        "asin": asin,
        "count": len(history),
        "history": history
    }


# ============================================================
# DATABASE STATISTICS
# ============================================================

@app.get("/api/stats")
def get_stats():

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute(
        "SELECT COUNT(*) FROM products"
    )

    product_count = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM price_history"
    )

    history_count = cursor.fetchone()[0]

    conn.close()

    return {
        "products": product_count,
        "price_history_records": history_count
    }
