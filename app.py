from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
import re
import json
import time
import os

app = Flask(__name__)

def get_real_url(short_url):
    """Short link থেকে আসল URL বের করা"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        resp = requests.get(short_url, headers=headers, allow_redirects=True, timeout=15)
        final_url = resp.url
        
        # যদি এখনও short link থাকে, আরেকবার follow
        if 's.daraz' in final_url:
            resp2 = requests.get(final_url, headers=headers, allow_redirects=True, timeout=15)
            final_url = resp2.url
        
        print(f"🔗 Final URL: {final_url[:80]}")
        return final_url
    except Exception as e:
        print(f"Redirect error: {e}")
        return short_url

def scrape_daraz(url):
    """Fast scrape without Playwright"""
    try:
        start_time = time.time()
        
        # Step 1: Get real URL from short link
        if 's.daraz' in url or 'short' in url or len(url) < 50:
            print("🔄 Resolving short link...")
            url = get_real_url(url)
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,bn;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Referer': 'https://www.google.com/',
            'Cache-Control': 'no-cache'
        }
        
        session = requests.Session()
        session.get('https://www.daraz.com.bd/', headers=headers, timeout=10)
        
        print(f"📄 Fetching: {url[:80]}...")
        response = session.get(url, headers=headers, timeout=15)
        
        if response.status_code == 404:
            # Try alternative URL format
            alt_url = url.replace('/products/', '/product/')
            response = session.get(alt_url, headers=headers, timeout=15)
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        data = {
            'title': 'N/A',
            'price': 'N/A',
            'original_price': 'N/A',
            'discount': 'N/A',
            'rating': 'N/A',
            'review_count': 'N/A',
            'brand': 'N/A',
            'category': 'N/A',
            'image': '',
            'url': response.url
        }
        
        # Method 1: JSON-LD Structured Data
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                if not script.string:
                    continue
                ld = json.loads(script.string)
                if isinstance(ld, list):
                    ld = ld[0] if ld else {}
                
                if ld.get('@type') == 'Product' or ld.get('name'):
                    data['title'] = ld.get('name', data['title'])
                    if ' | ' in data['title']:
                        data['title'] = data['title'].split(' | ')[0].strip()
                    
                    # Image
                    img = ld.get('image', '')
                    if isinstance(img, list) and img:
                        data['image'] = img[0]
                    elif isinstance(img, str):
                        data['image'] = img
                    
                    # Price
                    offers = ld.get('offers', {})
                    if isinstance(offers, dict):
                        price = offers.get('price')
                        if price:
                            data['price'] = f'৳{price}'
                    
                    # Brand
                    brand = ld.get('brand', {})
                    if isinstance(brand, dict):
                        data['brand'] = brand.get('name', data['brand'])
                    elif isinstance(brand, str):
                        data['brand'] = brand
                    
                    print(f"✅ JSON-LD: {data['title'][:50]}")
                    break
            except:
                continue
        
        # Method 2: Meta Tags
        if data['title'] == 'N/A':
            meta_title = soup.select_one('meta[property="og:title"]')
            if meta_title:
                title = meta_title.get('content', '')
                if ' | ' in title:
                    title = title.split(' | ')[0].strip()
                data['title'] = title
        
        if not data['image']:
            meta_img = soup.select_one('meta[property="og:image"]')
            if meta_img:
                data['image'] = meta_img.get('content', '')
        
        # Method 3: CSS Selectors
        if data['price'] == 'N/A':
            for sel in ['span.pdp-price_color_orange', 'span.pdp-price', '.pdp-price']:
                elem = soup.select_one(sel)
                if elem:
                    text = elem.get_text(strip=True)
                    if text and re.search(r'\d', text):
                        data['price'] = text
                        break
        
        if data['price'] == 'N/A':
            # Find any span with TK symbol
            all_text = soup.get_text()
            matches = re.findall(r'[৳TK]\s*[\d,]+', all_text)
            if matches:
                nums = sorted(set(float(re.sub(r'[^\d.]', '', m)) for m in matches))
                if nums:
                    data['price'] = f'৳{int(nums[0])}'
        
        # Original Price
        for sel in ['span.pdp-price_color_lightgray', 'del.pdp-price', 'del']:
            elem = soup.select_one(sel)
            if elem:
                data['original_price'] = elem.get_text(strip=True)
                break
        
        # Discount
        for sel in ['span.pdp-product-price__discount', '.discount']:
            elem = soup.select_one(sel)
            if elem:
                data['discount'] = elem.get_text(strip=True)
                break
        
        if data['discount'] == 'N/A' and data['price'] != 'N/A' and data['original_price'] != 'N/A':
            try:
                p = float(re.sub(r'[^\d.]', '', data['price']))
                o = float(re.sub(r'[^\d.]', '', data['original_price']))
                if o > p:
                    data['discount'] = f"-{round((1-p/o)*100)}%"
            except:
                pass
        
        # Rating
        for sel in ['span.pdp-review-summary__average', '.rating-value']:
            elem = soup.select_one(sel)
            if elem:
                data['rating'] = elem.get_text(strip=True)
                break
        
        # Review Count
        for sel in ['span.pdp-review-summary__count', '.review-count']:
            elem = soup.select_one(sel)
            if elem:
                data['review_count'] = re.sub(r'[^\d]', '', elem.get_text(strip=True))
                break
        
        # Brand
        if data['brand'] == 'N/A':
            for sel in ['a.pdp-product-brand', '.pdp-product-brand']:
                elem = soup.select_one(sel)
                if elem:
                    brand = elem.get_text(strip=True)
                    brand = re.sub(r'^Brand:\s*', '', brand)
                    brand = brand.split('More')[0].strip()
                    data['brand'] = brand[:30] if len(brand) > 30 else brand
                    break
        
        # Category
        breadcrumbs = soup.select('a.pdp-mod-product-breadcrumb-link, .breadcrumb a')
        if breadcrumbs:
            data['category'] = breadcrumbs[-1].get_text(strip=True)
        
        elapsed = time.time() - start_time
        print(f"✅ {elapsed:.1f}s | Price: {data['price']} | {data['discount']}")
        
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
        *{margin:0;padding:0;box-sizing:border-box}
        body{font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;background:linear-gradient(135deg,#f57224,#ff6b35);min-height:100vh;padding:20px}
        .container{max-width:650px;margin:0 auto}
        .header{text-align:center;margin-bottom:25px;color:#fff}
        .header h1{font-size:28px;text-shadow:2px 2px 4px rgba(0,0,0,.2)}
        .search-box{background:#fff;padding:20px;border-radius:15px;box-shadow:0 10px 40px rgba(0,0,0,.15);margin-bottom:20px}
        .input-row{display:flex;gap:10px}
        input{flex:1;padding:14px 18px;border:2px solid #e0e0e0;border-radius:10px;font-size:14px}
        input:focus{outline:none;border-color:#f57224}
        button{padding:14px 25px;background:linear-gradient(135deg,#f57224,#ff6b35);color:#fff;border:none;border-radius:10px;font-size:15px;font-weight:700;cursor:pointer;white-space:nowrap}
        button:hover{transform:translateY(-2px)}
        .quick-links{margin-top:12px;display:flex;gap:8px;flex-wrap:wrap}
        .quick-btn{background:#f5f5f5;border:1px solid #ddd;padding:6px 14px;border-radius:20px;font-size:12px;cursor:pointer}
        .quick-btn:hover{background:#f57224;color:#fff}
        .loading{text-align:center;padding:30px;display:none;color:#fff}
        .spinner{border:4px solid rgba(255,255,255,.3);border-top:4px solid #fff;border-radius:50%;width:45px;height:45px;animation:spin .8s linear infinite;margin:0 auto 15px}
        @keyframes spin{0%{transform:rotate(0)}100%{transform:rotate(360deg)}}
        .error{background:#fff0f0;border-left:4px solid #f44;padding:15px;border-radius:10px;display:none;margin-bottom:20px;color:#d00}
        .product{display:none;animation:slideUp .5s ease}
        @keyframes slideUp{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}
        .product-card{background:#fff;border-radius:15px;box-shadow:0 10px 40px rgba(0,0,0,.15);overflow:hidden}
        .img-section{background:#fafafa;padding:25px;text-align:center;position:relative}
        .product-img{max-width:100%;max-height:300px;object-fit:contain;border-radius:10px}
        .disc-badge{position:absolute;top:15px;right:15px;background:#f44;color:#fff;padding:8px 15px;border-radius:25px;font-weight:700;font-size:14px;display:none}
        .details{padding:25px}
        .brand{color:#f57224;font-weight:600;font-size:14px;margin-bottom:8px}
        .title{font-size:20px;font-weight:700;color:#333;margin-bottom:15px}
        .price-box{background:#fff5f0;padding:18px;border-radius:12px;margin-bottom:15px;display:flex;align-items:center;flex-wrap:wrap;gap:12px}
        .price{font-size:32px;font-weight:700;color:#f57224}
        .orig-price{color:#999;text-decoration:line-through;font-size:16px;display:none}
        .disc-text{color:#f44;font-weight:700;font-size:15px;display:none}
        .stats{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:10px;margin-bottom:15px}
        .stat{background:#f8f9fa;padding:12px;border-radius:10px;text-align:center}
        .stat-label{font-size:10px;color:#888}
        .stat-value{font-size:14px;font-weight:700;color:#333}
        .buy-btn{display:block;text-align:center;background:linear-gradient(135deg,#f57224,#ff6b35);color:#fff;padding:16px;border-radius:12px;text-decoration:none;font-size:17px;font-weight:700}
        .time{text-align:center;margin-top:10px;font-size:12px;color:#888}
    </style>
</head>
<body>
    <div class="container">
        <div class="header"><h1>🛍️ Daraz Product Viewer</h1></div>
        <div class="search-box">
            <div class="input-row">
                <input type="text" id="urlInput" placeholder="Paste Daraz link..." autofocus>
                <button onclick="searchProduct()">🔍 Search</button>
            </div>
            <div class="quick-links">
                <button class="quick-btn" onclick="quickSearch('https://s.daraz.com.bd/s.bMhlC?cc')">⌚ Watch</button>
                <button class="quick-btn" onclick="quickSearch('https://www.daraz.com.bd/products/realme-c55-8gb-256gb-i405584532.html')">📱 Phone</button>
            </div>
        </div>
        <div class="loading" id="loading"><div class="spinner"></div><p>Loading...</p></div>
        <div class="error" id="error"></div>
        <div class="product" id="product">
            <div class="product-card">
                <div class="img-section">
                    <img class="product-img" id="pImg" src="" onerror="this.style.display='none'">
                    <div class="disc-badge" id="pDiscBadge"></div>
                </div>
                <div class="details">
                    <div class="brand" id="pBrand"></div>
                    <h2 class="title" id="pTitle"></h2>
                    <div class="price-box">
                        <span class="price" id="pPrice">N/A</span>
                        <span class="orig-price" id="pOrig"></span>
                        <span class="disc-text" id="pDisc"></span>
                    </div>
                    <div class="stats">
                        <div class="stat"><div class="stat-label">⭐ Rating</div><div class="stat-value" id="pRating">-</div></div>
                        <div class="stat"><div class="stat-label">📝 Reviews</div><div class="stat-value" id="pReviews">-</div></div>
                        <div class="stat"><div class="stat-label">🏷️ Brand</div><div class="stat-value" id="pBrandVal">-</div></div>
                        <div class="stat"><div class="stat-label">📂 Category</div><div class="stat-value" id="pCategory">-</div></div>
                    </div>
                    <a class="buy-btn" id="pBuy" href="#" target="_blank">🛒 Buy Now on Daraz</a>
                    <div class="time" id="pTime"></div>
                </div>
            </div>
        </div>
    </div>
    <script>
        async function searchProduct(){const e=document.getElementById("urlInput").value.trim();e&&fetchProduct(e)}
        function quickSearch(e){document.getElementById("urlInput").value=e,fetchProduct(e)}
        async function fetchProduct(e){const t=Date.now();document.getElementById("loading").style.display="block";document.getElementById("product").style.display="none";document.getElementById("error").style.display="none";try{const o=await fetch("/api/product?url="+encodeURIComponent(e)),n=await o.json(),l=((Date.now()-t)/1e3).toFixed(1);document.getElementById("loading").style.display="none";if(n.error){document.getElementById("error").textContent="❌ "+n.error;document.getElementById("error").style.display="block";return}n.image?(document.getElementById("pImg").src=n.image,document.getElementById("pImg").style.display="block"):document.getElementById("pImg").style.display="none";document.getElementById("pTitle").textContent=n.title||"N/A";document.getElementById("pPrice").textContent=n.price||"N/A";document.getElementById("pBuy").href=n.url||e;document.getElementById("pTime").textContent="⚡ "+l+"s";n.brand&&"N/A"!==n.brand?(document.getElementById("pBrand").textContent="🏷️ "+n.brand,document.getElementById("pBrandVal").textContent=n.brand):(document.getElementById("pBrand").textContent="",document.getElementById("pBrandVal").textContent="-");document.getElementById("pRating").textContent="N/A"!==n.rating?"⭐ "+n.rating:"-";document.getElementById("pReviews").textContent="N/A"!==n.review_count?n.review_count:"0";document.getElementById("pCategory").textContent="N/A"!==n.category?n.category:"-";n.original_price&&"N/A"!==n.original_price&&n.original_price!==n.price?(document.getElementById("pOrig").textContent=n.original_price,document.getElementById("pOrig").style.display="inline"):document.getElementById("pOrig").style.display="none";n.discount&&"N/A"!==n.discount?(document.getElementById("pDisc").textContent="🔥 "+n.discount,document.getElementById("pDisc").style.display="inline",document.getElementById("pDiscBadge").textContent=n.discount,document.getElementById("pDiscBadge").style.display="block"):(document.getElementById("pDisc").style.display="none",document.getElementById("pDiscBadge").style.display="none");document.getElementById("product").style.display="block"}catch(o){document.getElementById("loading").style.display="none",document.getElementById("error").textContent="❌ "+o.message,document.getElementById("error").style.display="block"}}
        document.getElementById("urlInput").addEventListener("keypress",function(e){"Enter"===e.key&&searchProduct()});
    </script>
</body>
</html>
    '''


@app.route('/api/product')
def api_product():
    url = request.args.get('url', '')
    if not url: return jsonify({'error': 'URL required'}), 400
    if 'daraz' not in url.lower(): return jsonify({'error': 'Daraz links only'}), 400
    return jsonify(scrape_daraz(url))


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port, threaded=True)
