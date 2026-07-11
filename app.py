from flask import Flask, request, jsonify
from playwright.sync_api import sync_playwright
import time
import os

app = Flask(__name__)

def scrape_daraz(url):
    try:
        start_time = time.time()
        print(f"Scraping: {url[:60]}...")
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
            context = browser.new_context(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
            page = context.new_page()
            
            page.goto(url, wait_until='domcontentloaded', timeout=20000)
            current_url = page.url
            
            if 's.daraz' in current_url:
                page.wait_for_timeout(3000)
                current_url = page.url
            
            page.wait_for_timeout(3000)
            
            data = page.evaluate("""() => {
                const getText = (s) => { const e = document.querySelector(s); return e ? e.textContent.trim() : null; };
                
                let title = getText('h1.pdp-mod-product-badge-title') || getText('h1.pdp-product-title') || getText('h1');
                if (!title) { const m = document.querySelector('meta[property="og:title"]'); if (m) title = m.content; }
                if (title && title.includes(' | ')) title = title.split(' | ')[0].trim();
                
                let price = null;
                for (let s of ['span.pdp-price_color_orange', 'span.pdp-price', '.pdp-price']) {
                    const e = document.querySelector(s);
                    if (e && /[0-9]/.test(e.textContent.trim())) { price = e.textContent.trim(); break; }
                }
                
                if (!price) {
                    const spans = document.querySelectorAll('span');
                    for (let el of spans) {
                        const t = el.textContent.trim();
                        if (t && /[0-9]/.test(t) && t.length < 15) {
                            const st = window.getComputedStyle(el);
                            if (parseFloat(st.fontSize) >= 16 || st.color.includes('245') || t.includes('৳')) { price = t; break; }
                        }
                    }
                }
                
                if (!price) {
                    const txt = document.body.innerText;
                    const m = txt.match(/[৳TK]\\s*[0-9,]+/g);
                    if (m) { const n = [...new Set(m.map(x => parseFloat(x.replace(/[^0-9.]/g, ''))))].sort((a,b) => a-b); if (n.length) price = '৳' + n[0]; }
                }
                
                let origPrice = getText('span.pdp-price_color_lightgray') || getText('del.pdp-price') || getText('del');
                let discount = getText('span.pdp-product-price__discount') || getText('.discount');
                
                if (!discount && price && origPrice) {
                    const p = parseFloat(price.replace(/[^0-9.]/g, ''));
                    const o = parseFloat(origPrice.replace(/[^0-9.]/g, ''));
                    if (p && o && o > p) discount = '-' + Math.round((1-p/o)*100) + '%';
                }
                
                let brand = getText('a.pdp-product-brand');
                if (brand) { brand = brand.replace(/^Brand:\\s*/i, '').split('More')[0].trim(); }
                
                let rating = getText('span.pdp-review-summary__average');
                let reviews = getText('span.pdp-review-summary__count');
                if (reviews) reviews = reviews.replace(/[^0-9]/g, '');
                
                let category = null;
                const bc = document.querySelectorAll('a.pdp-mod-product-breadcrumb-link');
                if (bc.length) category = bc[bc.length-1].textContent.trim();
                
                let image = '';
                const mi = document.querySelector('meta[property="og:image"]');
                if (mi) image = mi.content;
                if (!image) { const img = document.querySelector('img.pdp-mod-common-image'); if (img) image = img.src; }
                
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
            print(f"Done {elapsed:.1f}s | Price: {data.get('price')}")
            return data
            
    except Exception as e:
        print(f"Error: {e}")
        return {'error': str(e)}


@app.route('/')
def home():
    return '''
<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Daraz Viewer</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:Arial,sans-serif;background:#f57224;padding:20px;min-height:100vh}
.container{max-width:600px;margin:0 auto}
h1{color:#fff;text-align:center;margin-bottom:20px}
.search-box{background:#fff;padding:20px;border-radius:12px;margin-bottom:20px}
.input-row{display:flex;gap:10px}
input{flex:1;padding:14px;border:2px solid #ddd;border-radius:8px;font-size:14px}
input:focus{outline:none;border-color:#f57224}
button{padding:14px 20px;background:#f57224;color:#fff;border:none;border-radius:8px;font-weight:bold;cursor:pointer}
.quick-links{margin-top:10px;display:flex;gap:5px}
.quick-btn{background:#eee;border:1px solid #ddd;padding:5px 12px;border-radius:15px;font-size:11px;cursor:pointer}
.quick-btn:hover{background:#f57224;color:#fff}
.loading{text-align:center;padding:30px;display:none;color:#fff}
.spinner{border:4px solid rgba(255,255,255,.3);border-top:4px solid #fff;border-radius:50%;width:40px;height:40px;animation:spin .8s linear infinite;margin:0 auto 15px}
@keyframes spin{0%{transform:rotate(0)}100%{transform:rotate(360deg)}}
.error{background:#fff0f0;padding:12px;border-radius:8px;display:none;color:#d00;margin-bottom:15px}
.product{display:none}
.product-card{background:#fff;border-radius:12px;overflow:hidden}
.img-section{background:#fafafa;padding:20px;text-align:center;position:relative}
.product-img{max-width:100%;max-height:250px;object-fit:contain}
.disc-badge{position:absolute;top:10px;right:10px;background:#f44;color:#fff;padding:5px 10px;border-radius:15px;font-weight:bold;font-size:12px;display:none}
.details{padding:20px}
.brand{color:#f57224;font-size:13px;margin-bottom:5px}
.title{font-size:18px;font-weight:bold;color:#333;margin-bottom:10px}
.price-box{background:#fff5f0;padding:15px;border-radius:10px;margin-bottom:10px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.price{font-size:28px;font-weight:bold;color:#f57224}
.orig-price{color:#999;text-decoration:line-through;font-size:14px;display:none}
.disc-text{color:#f44;font-weight:bold;font-size:14px;display:none}
.stats{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:8px;margin-bottom:10px}
.stat{background:#f8f9fa;padding:10px;border-radius:8px;text-align:center}
.stat-label{font-size:10px;color:#888}
.stat-value{font-size:13px;font-weight:bold;color:#333}
.buy-btn{display:block;text-align:center;background:#f57224;color:#fff;padding:14px;border-radius:10px;text-decoration:none;font-size:16px;font-weight:bold}
.time{text-align:center;margin-top:8px;font-size:11px;color:#888}
</style></head>
<body>
<div class="container"><h1>🛍️ Daraz Product Viewer</h1>
<div class="search-box"><div class="input-row"><input type="text" id="urlInput" placeholder="Paste Daraz link..." autofocus><button onclick="search()">🔍</button></div>
<div class="quick-links"><button class="quick-btn" onclick="quick('https://s.daraz.com.bd/s.bMhlC?cc')">⌚ Watch</button><button class="quick-btn" onclick="quick('https://www.daraz.com.bd/products/realme-c55-8gb-256gb-i405584532.html')">📱 Phone</button></div></div>
<div class="loading" id="loading"><div class="spinner"></div><p>Loading...</p></div>
<div class="error" id="error"></div>
<div class="product" id="product"><div class="product-card"><div class="img-section"><img class="product-img" id="pImg" src="" onerror="this.style.display='none'"><div class="disc-badge" id="pDiscBadge"></div></div>
<div class="details"><div class="brand" id="pBrand"></div><h2 class="title" id="pTitle"></h2>
<div class="price-box"><span class="price" id="pPrice">N/A</span><span class="orig-price" id="pOrig"></span><span class="disc-text" id="pDisc"></span></div>
<div class="stats"><div class="stat"><div class="stat-label">⭐ Rating</div><div class="stat-value" id="pRating">-</div></div><div class="stat"><div class="stat-label">📝 Reviews</div><div class="stat-value" id="pReviews">-</div></div><div class="stat"><div class="stat-label">🏷️ Brand</div><div class="stat-value" id="pBrandVal">-</div></div><div class="stat"><div class="stat-label">📂 Category</div><div class="stat-value" id="pCategory">-</div></div></div>
<a class="buy-btn" id="pBuy" href="#" target="_blank">🛒 Buy Now on Daraz</a><div class="time" id="pTime"></div></div></div></div></div>
<script>
async function search(){const e=document.getElementById("urlInput").value.trim();e&&fetchProduct(e)}
function quick(e){document.getElementById("urlInput").value=e,fetchProduct(e)}
async function fetchProduct(e){const t=Date.now();document.getElementById("loading").style.display="block";document.getElementById("product").style.display="none";document.getElementById("error").style.display="none";try{const o=await fetch("/api/product?url="+encodeURIComponent(e)),n=await o.json(),l=((Date.now()-t)/1e3).toFixed(1);document.getElementById("loading").style.display="none";if(n.error){document.getElementById("error").textContent="❌ "+n.error;document.getElementById("error").style.display="block";return}n.image&&(document.getElementById("pImg").src=n.image,document.getElementById("pImg").style.display="block");document.getElementById("pTitle").textContent=n.title||"N/A";document.getElementById("pPrice").textContent=n.price||"N/A";document.getElementById("pBuy").href=n.url||e;document.getElementById("pTime").textContent="⚡ "+l+"s";n.brand&&"N/A"!==n.brand?(document.getElementById("pBrand").textContent="🏷️ "+n.brand,document.getElementById("pBrandVal").textContent=n.brand):(document.getElementById("pBrand").textContent="",document.getElementById("pBrandVal").textContent="-");document.getElementById("pRating").textContent="N/A"!==n.rating?"⭐ "+n.rating:"-";document.getElementById("pReviews").textContent="N/A"!==n.review_count?n.review_count:"0";document.getElementById("pCategory").textContent="N/A"!==n.category?n.category:"-";n.original_price&&"N/A"!==n.original_price&&n.original_price!==n.price&&(document.getElementById("pOrig").textContent=n.original_price,document.getElementById("pOrig").style.display="inline");n.discount&&"N/A"!==n.discount&&(document.getElementById("pDisc").textContent="🔥 "+n.discount,document.getElementById("pDisc").style.display="inline",document.getElementById("pDiscBadge").textContent=n.discount,document.getElementById("pDiscBadge").style.display="block");document.getElementById("product").style.display="block"}catch(o){document.getElementById("loading").style.display="none",document.getElementById("error").textContent="❌ "+o.message,document.getElementById("error").style.display="block"}}
document.getElementById("urlInput").addEventListener("keypress",function(e){"Enter"===e.key&&search()});
</script></body></html>
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
