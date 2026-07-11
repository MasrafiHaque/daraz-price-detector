from flask import Flask, request, jsonify
from playwright.sync_api import sync_playwright
import time

app = Flask(__name__)

def scrape_daraz(url):
    """Daraz Product Scraper - Full Featured"""
    try:
        start_time = time.time()
        print(f"\n{'='*50}")
        print(f"⚡ Scraping: {url[:70]}...")
        print(f"{'='*50}")
        
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                    '--disable-extensions',
                    '--mute-audio'
                ]
            )
            
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                viewport={'width': 1920, 'height': 1080},
                locale='en-US'
            )
            
            page = context.new_page()
            
            # Anti-detection
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.navigator.chrome = { runtime: {} };
            """)
            
            print("📄 Loading page...")
            
            # Go to URL
            page.goto(url, wait_until='domcontentloaded', timeout=20000)
            
            # Handle short/affiliate link redirect
            current_url = page.url
            if 's.daraz' in current_url or 'short' in current_url or 's.' in current_url[:10]:
                print("🔄 Short link detected, waiting for redirect...")
                page.wait_for_timeout(3000)
                current_url = page.url
                print(f"📍 Redirected to: {current_url[:80]}...")
            
            # Wait for price to load (multiple attempts)
            print("⏳ Waiting for product data...")
            price_loaded = False
            
            for attempt in range(5):
                try:
                    has_price = page.evaluate("""() => {
                        const selectors = [
                            'span.pdp-price_color_orange',
                            'span.pdp-price',
                            'div.pdp-product-price span',
                            '.pdp-price'
                        ];
                        for (let sel of selectors) {
                            const el = document.querySelector(sel);
                            if (el && el.textContent.trim() && /[0-9]/.test(el.textContent.trim())) {
                                return true;
                            }
                        }
                        return false;
                    }""")
                    
                    if has_price:
                        price_loaded = True
                        print(f"✅ Price found after {attempt + 1} attempt(s)")
                        break
                    else:
                        page.wait_for_timeout(1000)
                except:
                    page.wait_for_timeout(1000)
            
            if not price_loaded:
                print("⚠️ Price element not found via selectors, trying text extraction...")
            
            # Extract ALL product data
            data = page.evaluate("""() => {
                // Helper function
                const getText = (selectors) => {
                    for (let sel of selectors) {
                        const el = document.querySelector(sel);
                        if (el && el.textContent.trim()) {
                            return el.textContent.trim();
                        }
                    }
                    return null;
                };
                
                // ===== TITLE =====
                let title = getText([
                    'h1.pdp-mod-product-badge-title',
                    'h1.pdp-product-title',
                    'div.pdp-product-title h1',
                    'h1'
                ]);
                
                if (!title) {
                    const meta = document.querySelector('meta[property="og:title"]');
                    if (meta) title = meta.content;
                }
                
                // Clean title (remove "| Daraz.com.bd")
                if (title && title.includes(' | ')) {
                    title = title.split(' | ')[0].trim();
                }
                
                // ===== PRICE (Multiple methods) =====
                let price = null;
                
                // Method 1: Standard CSS selectors
                const priceSelectors = [
                    'span.pdp-price_color_orange',
                    'span.pdp-price',
                    '.pdp-price_color_orange',
                    '.pdp-price',
                    'div.pdp-product-price span'
                ];
                
                for (let sel of priceSelectors) {
                    const els = document.querySelectorAll(sel);
                    for (let el of els) {
                        const text = el.textContent.trim();
                        if (text && /[0-9]/.test(text) && text.length < 20) {
                            price = text;
                            break;
                        }
                    }
                    if (price) break;
                }
                
                // Method 2: Find by color (orange/red) and font size
                if (!price) {
                    const allElements = document.querySelectorAll('span, div');
                    let bestCandidate = null;
                    let bestScore = 0;
                    
                    for (let el of allElements) {
                        const text = el.textContent.trim();
                        if (text && /^[৳TKtk]?\s*[0-9,]+\s*$/.test(text) && text.length < 15) {
                            const style = window.getComputedStyle(el);
                            const fontSize = parseFloat(style.fontSize);
                            const color = style.color;
                            
                            let score = 0;
                            // Orange color = high score
                            if (color.includes('245, 114') || color.includes('245, 87') || 
                                color.includes('255, 114') || color.includes('255, 87') ||
                                color.includes('orange')) {
                                score += 5;
                            }
                            // Large font = likely price
                            if (fontSize >= 20) score += 3;
                            if (fontSize >= 16) score += 1;
                            // Has TK symbol
                            if (text.includes('৳') || text.includes('TK')) score += 2;
                            
                            if (score > bestScore) {
                                bestScore = score;
                                bestCandidate = text;
                            }
                        }
                    }
                    
                    if (bestCandidate) price = bestCandidate;
                }
                
                // Method 3: Extract from page text
                if (!price) {
                    const bodyText = document.body.innerText;
                    const tkMatches = bodyText.match(/[৳TK]\s*[0-9,]+/g);
                    if (tkMatches && tkMatches.length > 0) {
                        const amounts = [...new Set(tkMatches.map(m => 
                            parseFloat(m.replace(/[^0-9.]/g, ''))
                        ))].sort((a, b) => a - b);
                        
                        if (amounts.length >= 2) {
                            price = '৳' + amounts[0]; // Lowest is current price
                        } else if (amounts.length === 1) {
                            price = '৳' + amounts[0];
                        }
                    }
                }
                
                // ===== ORIGINAL PRICE =====
                let originalPrice = getText([
                    'span.pdp-price_color_lightgray',
                    'del.pdp-price',
                    'span.pdp-price_original',
                    '.pdp-price_original'
                ]);
                
                // Find strikethrough price
                if (!originalPrice) {
                    const delElements = document.querySelectorAll('del, s, strike, span[style*="line-through"]');
                    for (let el of delElements) {
                        const text = el.textContent.trim();
                        if (text && /[0-9]/.test(text) && text !== price && text.length < 20) {
                            originalPrice = text;
                            break;
                        }
                    }
                }
                
                // ===== DISCOUNT =====
                let discount = getText([
                    'span.pdp-product-price__discount',
                    '.pdp-product-price__discount',
                    '.discount',
                    'span[class*="discount"]'
                ]);
                
                // Calculate discount if not found
                if (!discount && price && originalPrice) {
                    const p = parseFloat(price.replace(/[^0-9.]/g, ''));
                    const o = parseFloat(originalPrice.replace(/[^0-9.]/g, ''));
                    if (p && o && o > p) {
                        discount = '-' + Math.round((1 - p / o) * 100) + '%';
                    }
                }
                
                // ===== BRAND =====
                let brand = getText([
                    'a.pdp-product-brand',
                    'span.pdp-product-brand__name',
                    '.pdp-product-brand a',
                    '.pdp-product-brand'
                ]);
                
                // Clean brand text
                if (brand) {
                    brand = brand.replace(/^Brand:\s*/i, '');   // Remove "Brand:"
                    brand = brand.split('More')[0].trim();      // Remove "More Products..."
                    brand = brand.split('  ')[0].trim();        // Remove extra spaces
                    if (brand.length > 30) brand = brand.substring(0, 30);
                    if (brand.toLowerCase() === 'no brand' || brand === '') brand = 'No Brand';
                }
                
                // ===== RATING =====
                let rating = getText([
                    'span.pdp-review-summary__average',
                    '.pdp-review-summary__average',
                    '.rating-value',
                    'div[class*="rating"] span'
                ]);
                
                // ===== REVIEW COUNT =====
                let reviewCount = getText([
                    'span.pdp-review-summary__count',
                    '.pdp-review-summary__count',
                    '.review-count'
                ]);
                if (reviewCount) reviewCount = reviewCount.replace(/[^0-9]/g, '');
                
                // ===== CATEGORY =====
                let category = null;
                const breadcrumbs = document.querySelectorAll(
                    'a.pdp-mod-product-breadcrumb-link, .breadcrumb a, nav[class*="breadcrumb"] a'
                );
                if (breadcrumbs.length > 0) {
                    category = breadcrumbs[breadcrumbs.length - 1].textContent.trim();
                }
                
                // ===== IMAGE =====
                let image = '';
                const metaImg = document.querySelector('meta[property="og:image"]');
                if (metaImg && metaImg.content) {
                    image = metaImg.content;
                }
                if (!image) {
                    const img = document.querySelector(
                        'img.pdp-mod-common-image, .pdp-product-img img, .gallery-preview-panel img'
                    );
                    if (img && img.src) image = img.src;
                }
                
                // ===== REVIEWS (if available) =====
                const reviews = [];
                const reviewElements = document.querySelectorAll(
                    '.pdp-review-item, .review-item, div[class*="review-item"]'
                );
                
                reviewElements.forEach(el => {
                    const reviewer = el.querySelector('.reviewer, .review-user, [class*="user"]');
                    const comment = el.querySelector('.review-content, .review-text, .content');
                    const stars = el.querySelector('.star, .rating, [class*="star"]');
                    
                    if (comment && comment.textContent.trim()) {
                        reviews.push({
                            reviewer: reviewer ? reviewer.textContent.trim() : 'Customer',
                            comment: comment.textContent.trim().substring(0, 150),
                            rating: stars ? stars.textContent.trim() : ''
                        });
                    }
                });
                
                return {
                    title: title || 'N/A',
                    price: price || 'N/A',
                    original_price: originalPrice || 'N/A',
                    discount: discount || 'N/A',
                    rating: rating || 'N/A',
                    review_count: reviewCount || 'N/A',
                    brand: brand || 'N/A',
                    category: category || 'N/A',
                    image: image,
                    reviews: reviews.slice(0, 3)
                };
            }""")
            
            browser.close()
            
            elapsed = time.time() - start_time
            data['url'] = current_url
            
            print(f"""
✅ SCRAPING COMPLETE
⏱ Time: {elapsed:.1f}s
📦 Title: {str(data.get('title'))[:60]}
💰 Price: {data.get('price')}
🏷️ Original: {data.get('original_price')}
🔥 Discount: {data.get('discount')}
⭐ Rating: {data.get('rating')} | Reviews: {data.get('review_count')}
🏭 Brand: {data.get('brand')}
📂 Category: {data.get('category')}
🖼 Image: {data.get('image', '')[:50]}...
💬 Reviews found: {len(data.get('reviews', []))}
{'='*50}
            """)
            
            return data
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return {'error': str(e)}


@app.route('/')
def home():
    return '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Daraz Product Viewer</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
            min-height: 100vh; 
            padding: 20px; 
        }
        .container { max-width: 650px; margin: 0 auto; }
        
        .header { 
            text-align: center; 
            margin-bottom: 25px; 
            color: white; 
        }
        .header h1 { 
            font-size: 28px; 
            text-shadow: 2px 2px 4px rgba(0,0,0,0.2); 
        }
        .header p { 
            font-size: 14px; 
            opacity: 0.9; 
            margin-top: 5px; 
        }
        
        .search-box { 
            background: white; 
            padding: 20px; 
            border-radius: 15px; 
            box-shadow: 0 10px 40px rgba(0,0,0,0.15); 
            margin-bottom: 20px; 
        }
        .input-row { display: flex; gap: 10px; }
        input { 
            flex: 1; 
            padding: 14px 18px; 
            border: 2px solid #e0e0e0; 
            border-radius: 10px; 
            font-size: 14px; 
            transition: all 0.3s; 
        }
        input:focus { 
            outline: none; 
            border-color: #667eea; 
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1); 
        }
        button { 
            padding: 14px 25px; 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
            color: white; 
            border: none; 
            border-radius: 10px; 
            font-size: 15px; 
            font-weight: bold; 
            cursor: pointer; 
            transition: transform 0.2s, box-shadow 0.2s; 
            white-space: nowrap; 
        }
        button:hover { 
            transform: translateY(-2px); 
            box-shadow: 0 5px 20px rgba(102, 126, 234, 0.4); 
        }
        button:active { transform: translateY(0); }
        
        .quick-links { 
            margin-top: 12px; 
            display: flex; 
            gap: 8px; 
            flex-wrap: wrap; 
            align-items: center; 
        }
        .quick-btn { 
            background: #f5f5f5; 
            border: 1px solid #ddd; 
            padding: 6px 14px; 
            border-radius: 20px; 
            font-size: 12px; 
            cursor: pointer; 
            transition: all 0.2s; 
        }
        .quick-btn:hover { 
            background: #667eea; 
            color: white; 
            border-color: #667eea; 
        }
        
        .loading { 
            text-align: center; 
            padding: 30px; 
            display: none; 
            color: white; 
        }
        .spinner { 
            border: 4px solid rgba(255,255,255,0.3); 
            border-top: 4px solid white; 
            border-radius: 50%; 
            width: 45px; 
            height: 45px; 
            animation: spin 0.8s linear infinite; 
            margin: 0 auto 15px; 
        }
        @keyframes spin { 
            0% { transform: rotate(0deg); } 
            100% { transform: rotate(360deg); } 
        }
        
        .error { 
            background: #fff0f0; 
            border-left: 4px solid #ff4444; 
            padding: 15px 20px; 
            border-radius: 10px; 
            display: none; 
            margin-bottom: 20px; 
            color: #d00; 
            font-weight: 500; 
        }
        
        .product { display: none; animation: slideUp 0.5s ease; }
        @keyframes slideUp { 
            from { opacity: 0; transform: translateY(20px); } 
            to { opacity: 1; transform: translateY(0); } 
        }
        
        .product-card { 
            background: white; 
            border-radius: 15px; 
            box-shadow: 0 10px 40px rgba(0,0,0,0.15); 
            overflow: hidden; 
        }
        
        .img-section { 
            background: #fafafa; 
            padding: 25px; 
            text-align: center; 
            position: relative; 
        }
        .product-img { 
            max-width: 100%; 
            max-height: 300px; 
            object-fit: contain; 
            border-radius: 10px; 
        }
        .disc-badge { 
            position: absolute; 
            top: 15px; 
            right: 15px; 
            background: #ff4444; 
            color: white; 
            padding: 8px 15px; 
            border-radius: 25px; 
            font-weight: bold; 
            font-size: 14px; 
            box-shadow: 0 2px 10px rgba(255,68,68,0.3); 
            display: none; 
        }
        
        .details { padding: 25px; }
        .brand { 
            color: #667eea; 
            font-weight: 600; 
            font-size: 14px; 
            margin-bottom: 8px; 
        }
        .title { 
            font-size: 20px; 
            font-weight: bold; 
            color: #333; 
            margin-bottom: 15px; 
            line-height: 1.5; 
        }
        
        .price-box { 
            background: linear-gradient(135deg, #f8f9ff, #f0f0ff); 
            padding: 18px; 
            border-radius: 12px; 
            margin-bottom: 15px; 
            display: flex; 
            align-items: center; 
            flex-wrap: wrap; 
            gap: 12px; 
        }
        .price { 
            font-size: 32px; 
            font-weight: bold; 
            color: #667eea; 
        }
        .orig-price { 
            color: #999; 
            text-decoration: line-through; 
            font-size: 16px; 
            display: none; 
        }
        .disc-text { 
            color: #ff4444; 
            font-weight: bold; 
            font-size: 15px; 
            display: none; 
        }
        
        .stats { 
            display: grid; 
            grid-template-columns: 1fr 1fr 1fr 1fr; 
            gap: 10px; 
            margin-bottom: 15px; 
        }
        .stat { 
            background: #f8f9fa; 
            padding: 12px; 
            border-radius: 10px; 
            text-align: center; 
        }
        .stat-label { 
            font-size: 10px; 
            color: #888; 
            margin-bottom: 5px; 
            text-transform: uppercase; 
        }
        .stat-value { 
            font-size: 14px; 
            font-weight: bold; 
            color: #333; 
        }
        
        .reviews-box { 
            background: #fafafa; 
            border-radius: 10px; 
            padding: 15px; 
            margin-bottom: 15px; 
            display: none; 
        }
        .reviews-title { 
            font-size: 14px; 
            font-weight: bold; 
            color: #333; 
            margin-bottom: 10px; 
        }
        .review-item { 
            background: white; 
            padding: 12px; 
            border-radius: 8px; 
            margin-bottom: 8px; 
            border-left: 3px solid #667eea; 
        }
        .review-header { 
            display: flex; 
            justify-content: space-between; 
            margin-bottom: 5px; 
            font-size: 12px; 
        }
        .reviewer { font-weight: 600; color: #333; }
        .review-stars { color: #f59e0b; }
        .review-text { 
            font-size: 13px; 
            color: #666; 
            line-height: 1.5; 
        }
        
        .buy-btn { 
            display: block; 
            text-align: center; 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
            color: white; 
            padding: 16px; 
            border-radius: 12px; 
            text-decoration: none; 
            font-size: 17px; 
            font-weight: bold; 
            transition: transform 0.2s, box-shadow 0.2s; 
        }
        .buy-btn:hover { 
            transform: translateY(-2px); 
            box-shadow: 0 5px 20px rgba(102, 126, 234, 0.4); 
        }
        
        .time { 
            text-align: center; 
            margin-top: 10px; 
            font-size: 12px; 
            color: #888; 
        }
        
        @media (max-width: 600px) {
            .stats { grid-template-columns: 1fr 1fr; }
            .price { font-size: 24px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🛍️ Daraz Product Viewer</h1>
            <p>Paste any Daraz link & get full product details instantly</p>
        </div>
        
        <div class="search-box">
            <div class="input-row">
                <input type="text" id="urlInput" placeholder="Paste Daraz product or affiliate link here..." autofocus>
                <button onclick="searchProduct()">🔍 Search</button>
            </div>
            <div class="quick-links">
                <span style="font-size:12px; color:#888;">Quick Test:</span>
                <button class="quick-btn" onclick="quickSearch('https://s.daraz.com.bd/s.bMhlC?cc')">⌚ Watch</button>
                <button class="quick-btn" onclick="quickSearch('https://www.daraz.com.bd/products/realme-c55-8gb-256gb-i405584532.html')">📱 Phone</button>
                <button class="quick-btn" onclick="quickSearch('https://www.daraz.com.bd/products/samsung-galaxy-s24-i384567890.html')">📱 Samsung</button>
            </div>
        </div>
        
        <div class="loading" id="loading">
            <div class="spinner"></div>
            <p style="font-size:14px;">Loading product details...</p>
        </div>
        
        <div class="error" id="error"></div>
        
        <div class="product" id="product">
            <div class="product-card">
                <div class="img-section">
                    <img class="product-img" id="pImg" src="" alt="Product Image" onerror="this.style.display='none'">
                    <div class="disc-badge" id="pDiscBadge"></div>
                </div>
                
                <div class="details">
                    <div class="brand" id="pBrand"></div>
                    <h2 class="title" id="pTitle">Loading...</h2>
                    
                    <div class="price-box">
                        <span class="price" id="pPrice">N/A</span>
                        <span class="orig-price" id="pOrig"></span>
                        <span class="disc-text" id="pDisc"></span>
                    </div>
                    
                    <div class="stats">
                        <div class="stat">
                            <div class="stat-label">⭐ Rating</div>
                            <div class="stat-value" id="pRating">-</div>
                        </div>
                        <div class="stat">
                            <div class="stat-label">📝 Reviews</div>
                            <div class="stat-value" id="pReviews">-</div>
                        </div>
                        <div class="stat">
                            <div class="stat-label">🏷️ Brand</div>
                            <div class="stat-value" id="pBrandVal">-</div>
                        </div>
                        <div class="stat">
                            <div class="stat-label">📂 Category</div>
                            <div class="stat-value" id="pCategory">-</div>
                        </div>
                    </div>
                    
                    <div class="reviews-box" id="reviewsBox">
                        <div class="reviews-title">💬 Recent Customer Reviews</div>
                        <div id="reviewsList"></div>
                    </div>
                    
                    <a class="buy-btn" id="pBuy" href="#" target="_blank">
                        🛒 Buy Now on Daraz
                    </a>
                    <div class="time" id="pTime"></div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        async function searchProduct() {
            const url = document.getElementById('urlInput').value.trim();
            if (!url) return alert('Please enter a Daraz URL');
            if (!url.includes('daraz')) return alert('Please enter a valid Daraz URL');
            fetchProduct(url);
        }
        
        function quickSearch(url) {
            document.getElementById('urlInput').value = url;
            fetchProduct(url);
        }
        
        async function fetchProduct(url) {
            const startTime = Date.now();
            
            // Show loading
            document.getElementById('loading').style.display = 'block';
            document.getElementById('product').style.display = 'none';
            document.getElementById('error').style.display = 'none';
            
            try {
                const response = await fetch('/api/product?url=' + encodeURIComponent(url));
                const data = await response.json();
                const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
                
                // Hide loading
                document.getElementById('loading').style.display = 'none';
                
                // Handle error
                if (data.error) {
                    document.getElementById('error').textContent = '❌ ' + data.error;
                    document.getElementById('error').style.display = 'block';
                    return;
                }
                
                // Display product image
                if (data.image) {
                    document.getElementById('pImg').src = data.image;
                    document.getElementById('pImg').style.display = 'block';
                } else {
                    document.getElementById('pImg').style.display = 'none';
                }
                
                // Basic info
                document.getElementById('pTitle').textContent = data.title || 'N/A';
                document.getElementById('pPrice').textContent = data.price || 'N/A';
                document.getElementById('pBuy').href = data.url || url;
                document.getElementById('pTime').textContent = '⚡ Loaded in ' + elapsed + ' seconds';
                
                // Brand
                if (data.brand && data.brand !== 'N/A' && data.brand !== 'No Brand') {
                    document.getElementById('pBrand').textContent = '🏷️ ' + data.brand;
                    document.getElementById('pBrandVal').textContent = data.brand;
                } else {
                    document.getElementById('pBrand').textContent = '';
                    document.getElementById('pBrandVal').textContent = 'No Brand';
                }
                
                // Rating
                document.getElementById('pRating').textContent = 
                    data.rating && data.rating !== 'N/A' ? '⭐ ' + data.rating : '-';
                
                // Reviews count
                document.getElementById('pReviews').textContent = 
                    data.review_count && data.review_count !== 'N/A' ? data.review_count : '0';
                
                // Category
                document.getElementById('pCategory').textContent = 
                    data.category && data.category !== 'N/A' ? data.category : '-';
                
                // Original price
                if (data.original_price && data.original_price !== 'N/A' && 
                    data.original_price !== data.price) {
                    document.getElementById('pOrig').textContent = data.original_price;
                    document.getElementById('pOrig').style.display = 'inline';
                } else {
                    document.getElementById('pOrig').style.display = 'none';
                }
                
                // Discount
                if (data.discount && data.discount !== 'N/A' && data.discount !== '0%') {
                    document.getElementById('pDisc').textContent = '🔥 ' + data.discount;
                    document.getElementById('pDisc').style.display = 'inline';
                    document.getElementById('pDiscBadge').textContent = data.discount;
                    document.getElementById('pDiscBadge').style.display = 'block';
                } else {
                    document.getElementById('pDisc').style.display = 'none';
                    document.getElementById('pDiscBadge').style.display = 'none';
                }
                
                // Reviews
                if (data.reviews && data.reviews.length > 0) {
                    document.getElementById('reviewsBox').style.display = 'block';
                    document.getElementById('reviewsList').innerHTML = data.reviews.map(r => `
                        <div class="review-item">
                            <div class="review-header">
                                <span class="reviewer">👤 ${r.reviewer || 'Customer'}</span>
                                <span class="review-stars">${r.rating ? '⭐ ' + r.rating : ''}</span>
                            </div>
                            <div class="review-text">${r.comment || ''}</div>
                        </div>
                    `).join('');
                } else {
                    document.getElementById('reviewsBox').style.display = 'none';
                }
                
                // Show product
                document.getElementById('product').style.display = 'block';
                document.getElementById('product').scrollIntoView({ behavior: 'smooth', block: 'start' });
                
            } catch (err) {
                document.getElementById('loading').style.display = 'none';
                document.getElementById('error').textContent = '❌ Network error: ' + err.message;
                document.getElementById('error').style.display = 'block';
                console.error('Fetch error:', err);
            }
        }
        
        // Enter key support
        document.getElementById('urlInput').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') searchProduct();
        });
        
        // Auto-focus on load
        window.addEventListener('load', function() {
            document.getElementById('urlInput').focus();
        });
    </script>
</body>
</html>
    '''


@app.route('/api/product')
def api_product():
    """API endpoint for product scraping"""
    url = request.args.get('url', '').strip()
    
    if not url:
        return jsonify({'error': 'URL parameter is required'}), 400
    
    if 'daraz' not in url.lower():
        return jsonify({'error': 'Only Daraz links are supported'}), 400
    
    result = scrape_daraz(url)
    return jsonify(result)


@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Endpoint not found'}), 404


@app.errorhandler(500)
def server_error(e):
    return jsonify({'error': 'Internal server error'}), 500


if __name__ == '__main__':
    print("""
╔══════════════════════════════════════════════╗
║     🛍️  DARAZ PRODUCT VIEWER                ║
║     🚀  Playwright Scraper                  ║
║     📍  http://127.0.0.1:5000                ║
║     ⚡  Fast & Reliable                      ║
╚══════════════════════════════════════════════╝
    """)
    if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port, threaded=True)
