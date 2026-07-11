from flask import Flask, request, jsonify
from playwright.sync_api import sync_playwright
import time
import os

app = Flask(__name__)

def scrape_daraz(url):
    """Scrape Daraz product details"""
    try:
        start_time = time.time()
        print(f"⚡ Scraping: {url[:60]}...")
        
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
            )
            
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                viewport={'width': 1920, 'height': 1080}
            )
            
            page = context.new_page()
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            """)
            
            print("📄 Loading page...")
            
            # USE domcontentloaded instead of networkidle (FASTER)
            page.goto(url, wait_until='domcontentloaded', timeout=20000)
            current_url = page.url
            
            # Handle short links
            if 's.daraz' in current_url:
                print("🔄 Short link, waiting for redirect...")
                page.wait_for_timeout(4000)
                current_url = page.url
            
            # Wait for price elements to appear
            print("⏳ Waiting for prices...")
            try:
                page.wait_for_selector('body', timeout=5000)
                page.wait_for_timeout(3000)
                
                # Try to find price
                price_found = page.evaluate("""() => {
                    const el = document.querySelector('span.pdp-price_color_orange, span.pdp-price, .pdp-price');
                    return el && el.textContent.trim() && /[0-9]/.test(el.textContent.trim());
                }""")
                
                if not price_found:
                    print("⚠️ Price not visible yet, extra wait...")
                    page.wait_for_timeout(3000)
            except:
                page.wait_for_timeout(3000)
            
            # Extract data
            data = page.evaluate("""() => {
                const getText = (selectors) => {
                    for (let sel of selectors) {
                        const els = document.querySelectorAll(sel);
                        for (let el of els) {
                            const text = el.textContent.trim();
                            if (text && text.length > 0) return text;
                        }
                    }
                    return null;
                };
                
                // Title
                let title = getText(['h1.pdp-mod-product-badge-title', 'h1.pdp-product-title', 'h1']);
                if (!title) {
                    const meta = document.querySelector('meta[property="og:title"]');
                    if (meta) title = meta.content;
                }
                if (title && title.includes(' | ')) title = title.split(' | ')[0].trim();
                
                // Price
                let price = null;
                for (let sel of ['span.pdp-price_color_orange', 'span.pdp-price', '.pdp-price', 'div.pdp-product-price span']) {
                    const els = document.querySelectorAll(sel);
                    for (let el of els) {
                        const t = el.textContent.trim();
                        if (t && /[0-9]/.test(t) && t.length < 20) { price = t; break; }
                    }
                    if (price) break;
                }
                
                if (!price) {
                    const spans = document.querySelectorAll('span, div');
                    for (let el of spans) {
                        const t = el.textContent.trim();
                        if (t && /[0-9]/.test(t) && t.length < 15) {
                            const style = window.getComputedStyle(el);
                            if (parseFloat(style.fontSize) >= 16 || style.color.includes('245') || t.includes('৳')) {
                                price = t;
                                break;
                            }
                        }
                    }
                }
                
                if (!price) {
                    const text = document.body.innerText;
                    const matches = text.match(/[৳TK]\s*[0-9,]+/g);
                    if (matches) {
                        const nums = [...new Set(matches.map(m => parseFloat(m.replace(/[^0-9.]/g, ''))))].sort((a,b) => a-b);
                        if (nums.length > 0) price = '৳' + nums[0];
                    }
                }
                
                // Original Price
                let origPrice = getText(['span.pdp-price_color_lightgray', 'del.pdp-price', 'del']);
                
                // Discount
                let discount = getText(['span.pdp-product-price__discount', '.discount']);
                if (!discount && price && origPrice) {
                    const p = parseFloat(price.replace(/[^0-9.]/g, ''));
                    const o = parseFloat(origPrice.replace(/[^0-9.]/g, ''));
                    if (p && o && o > p) discount = '-' + Math.round((1-p/o)*100) + '%';
                }
                
                // Brand
                let brand = getText(['a.pdp-product-brand', '.pdp-product-brand']);
                if (brand) { brand = brand.replace(/^Brand:\\s*/i, '').split('More')[0].trim(); }
                
                // Rating & Reviews
                let rating = getText(['span.pdp-review-summary__average', '.rating-value']);
                let reviews = getText(['span.pdp-review-summary__count']);
                if (reviews) reviews = reviews.replace(/[^0-9]/g, '');
                
                // Category
                let category = null;
                const bc = document.querySelectorAll('a.pdp-mod-product-breadcrumb-link');
                if (bc.length) category = bc[bc.length-1].textContent.trim();
                
                // Image
                let image = '';
                const mi = document.querySelector('meta[property="og:image"]');
                if (mi) image = mi.content;
                if (!image) {
                    const img = document.querySelector('img.pdp-mod-common-image, .pdp-product-img img');
                    if (img) image = img.src;
                }
                
                return {
                    title: title || 'N/A', price: price || 'N/A',
                    original_price: origPrice || 'N/A', discount: discount || 'N/A',
                    rating: rating || 'N/A', review_count: reviews || 'N/A',
                    brand: brand || 'N/A', category: category || 'N/A', image: image
                };
            }""")
            
            browser.close()
            elapsed = time.time() - start_time
            data['url'] = current_url
            print(f"✅ {elapsed:.1f}s | Price: {data.get('price')}")
            return data
            
    except Exception as e:
        print(f"❌ Error: {e}")
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
        .header p{font-size:14px;opacity:.9;margin-top:5px}
        .search-box{background:#fff;padding:20px;border-radius:15px;box-shadow:0 10px 40px rgba(0,0,0,.15);margin-bottom:20px}
        .input-row{display:flex;gap:10px}
        input{flex:1;padding:14px 18px;border:2px solid #e0e0e0;border-radius:10px;font-size:14px}
        input:focus{outline:none;border-color:#f57224;box-shadow:0 0 0 3px rgba(245,114,36,.1)}
        button{padding:14px 25px;background:linear-gradient(135deg,#f57224,#ff6b35);color:#fff;border:none;border-radius:10px;font-size:15px;font-weight:700;cursor:pointer;white-space:nowrap}
        button:hover{transform:translateY(-2px);box-shadow:0 5px 20px rgba(245,114,36,.4)}
        .quick-links{margin-top:12px;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
        .quick-btn{background:#f5f5f5;border:1px solid #ddd;padding:6px 14px;border-radius:20px;font-size:12px;cursor:pointer}
        .quick-btn:hover{background:#f57224;color:#fff;border-color:#f57224}
        .loading{text-align:center;padding:30px;display:none;color:#fff}
        .spinner{border:4px solid rgba(255,255,255,.3);border-top:4px solid #fff;border-radius:50%;width:45px;height:45px;animation:spin .8s linear infinite;margin:0 auto 15px}
        @keyframes spin{0%{transform:rotate(0)}100%{transform:rotate(360deg)}}
        .error{background:#fff0f0;border-left:4px solid #f44;padding:15px 20px;border-radius:10px;display:none;margin-bottom:20px;color:#d00}
        .product{display:none;animation:slideUp .5s ease}
        @keyframes slideUp{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}
        .product-card{background:#fff;border-radius:15px;box-shadow:0 10px 40px rgba(0,0,0,.15);overflow:hidden}
        .img-section{background:#fafafa;padding:25px;text-align:center;position:relative}
        .product-img{max-width:100%;max-height:300px;object-fit:contain;border-radius:10px}
        .disc-badge{position:absolute;top:15px;right:15px;background:#f44;color:#fff;padding:8px 15px;border-radius:25px;font-weight:700;font-size:14px;display:none}
        .details{padding:25px}
        .brand{color:#f57224;font-weight:600;font-size:14px;margin-bottom:8px}
        .title{font-size:20px;font-weight:700;color:#333;margin-bottom:15px;line-height:1.5}
        .price-box{background:#fff5f0;padding:18px;border-radius:12px;margin-bottom:15px;display:flex;align-items:center;flex-wrap:wrap;gap:12px}
        .price{font-size:32px;font-weight:700;color:#f57224}
        .orig-price{color:#999;text-decoration:line-through;font-size:16px;display:none}
        .disc-text{color:#f44;font-weight:700;font-size:15px;display:none}
        .stats{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:10px;margin-bottom:15px}
        .stat{background:#f8f9fa;padding:12px;border-radius:10px;text-align:center}
        .stat-label{font-size:10px;color:#888;margin-bottom:5px}
        .stat-value{font-size:14px;font-weight:700;color:#333}
        .buy-btn{display:block;text-align:center;background:linear-gradient(135deg,#f57224,#ff6b35);color:#fff;padding:16px;border-radius:12px;text-decoration:none;font-size:17px;font-weight:700}
        .buy-btn:hover{transform:translateY(-2px);box-shadow:0 5px 20px rgba(245,114,36,.4)}
        .time{text-align:center;margin-top:10px;font-size:12px;color:#888}
        @media(max-width:600px){.stats{grid-template-columns:1fr 1fr}.price{font-size:24px}}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🛍️ Daraz Product Viewer</h1>
            <p>Paste any Daraz link & get full product details</p>
        </div>
        <div class="search-box">
            <div class="input-row">
                <input type="text" id="urlInput" placeholder="Paste Daraz link..." autofocus>
                <button onclick="searchProduct()">🔍 Search</button>
            </div>
            <div class="quick-links">
                <span style="font-size:12px;color:#888">Quick:</span>
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
