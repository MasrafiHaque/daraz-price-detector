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
            browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                viewport={'width': 1920, 'height': 1080},
                locale='en-US'
            )
            page = context.new_page()
            
            # RESOLVE SHORT LINK FIRST
            print("Resolving URL...")
            page.goto(url, wait_until='domcontentloaded', timeout=15000)
            page.wait_for_timeout(2000)
            
            # Follow redirects
            current_url = page.url
            if 's.daraz' in current_url or 'short' in current_url:
                print(f"Short link detected: {current_url[:50]}")
                # Wait for redirect
                page.wait_for_timeout(5000)
                current_url = page.url
                
                # If still short link, try to extract product URL
                if 's.daraz' in current_url:
                    print("Trying to extract product ID...")
                    try:
                        # Click or get the redirect URL
                        final_url = page.evaluate("""() => {
                            const links = document.querySelectorAll('a[href*="products"]');
                            if (links.length > 0) return links[0].href;
                            return window.location.href;
                        }""")
                        if final_url and 'products' in final_url:
                            page.goto(final_url, wait_until='domcontentloaded', timeout=15000)
                            current_url = page.url
                    except:
                        pass
            
            print(f"Final URL: {current_url[:80]}")
            
            # WAIT FOR PRODUCT DATA
            print("Waiting for product data...")
            page.wait_for_timeout(5000)
            
            # Try to wait for price element
            try:
                page.wait_for_selector('span.pdp-price, h1', timeout=8000)
                print("Page elements found!")
            except:
                print("Timeout, continuing anyway...")
                page.wait_for_timeout(2000)
            
            # EXTRACT DATA
            data = page.evaluate("""() => {
                // Get any text from selector
                const $ = (sel) => {
                    const el = document.querySelector(sel);
                    return el ? el.textContent.trim() : null;
                };
                
                // Get all text matching selectors
                const $$ = (sel) => {
                    return Array.from(document.querySelectorAll(sel)).map(el => el.textContent.trim()).filter(t => t);
                };
                
                // TITLE
                let title = $('h1.pdp-mod-product-badge-title') || 
                           $('h1.pdp-product-title') || 
                           $('h1') ||
                           document.querySelector('meta[property="og:title"]')?.content;
                
                if (title && title.includes(' | ')) title = title.split(' | ')[0].trim();
                
                // PRICE - Try ALL methods
                let price = null;
                
                // 1. Standard selectors
                const priceSelectors = [
                    'span.pdp-price_color_orange',
                    'span.pdp-price',
                    '.pdp-price_color_orange',
                    '.pdp-price',
                    'div.pdp-product-price span',
                    'span[class*="price"]:not([class*="original"])'
                ];
                
                for (let sel of priceSelectors) {
                    const els = document.querySelectorAll(sel);
                    for (let el of els) {
                        const t = el.textContent.trim();
                        if (t && /[0-9]/.test(t) && t.length < 20 && !t.includes('Save') && !t.includes('OFF')) {
                            price = t;
                            break;
                        }
                    }
                    if (price) break;
                }
                
                // 2. Find any orange/large text with numbers
                if (!price) {
                    const allElements = document.querySelectorAll('*');
                    for (let el of allElements) {
                        if (el.children.length === 0) {
                            const t = el.textContent.trim();
                            if (t && /^[৳TKtk]?\s*[0-9,]+\s*$/.test(t) && t.length < 12) {
                                const style = window.getComputedStyle(el);
                                const fontSize = parseFloat(style.fontSize);
                                const color = style.color;
                                
                                // Check if it looks like a price
                                if (fontSize >= 14 && (
                                    color.includes('245') || color.includes('255, 87') || 
                                    color.includes('255, 68') || t.includes('৳') || t.includes('TK')
                                )) {
                                    price = t;
                                    break;
                                }
                            }
                        }
                    }
                }
                
                // 3. Scan ALL text for TK amounts
                if (!price) {
                    const body = document.body.innerText;
                    const matches = body.match(/[৳TKtk]\s*[0-9,]+\s*/g);
                    if (matches && matches.length > 0) {
                        const amounts = matches.map(m => parseFloat(m.replace(/[^0-9.]/g, '')));
                        const unique = [...new Set(amounts)].sort((a, b) => a - b);
                        if (unique.length >= 2) {
                            price = '৳' + unique[0];
                        } else if (unique.length === 1) {
                            price = '৳' + unique[0];
                        }
                    }
                }
                
                // ORIGINAL PRICE
                let origPrice = $('span.pdp-price_color_lightgray') || 
                               $('del.pdp-price') || 
                               $('span.pdp-price_original') ||
                               $('del');
                
                // If no orig price found, try to find strikethrough price
                if (!origPrice && price) {
                    const delEls = document.querySelectorAll('del, s, strike, span[style*="line-through"]');
                    for (let el of delEls) {
                        const t = el.textContent.trim();
                        if (t && /[0-9]/.test(t) && t !== price) {
                            origPrice = t;
                            break;
                        }
                    }
                }
                
                // DISCOUNT
                let discount = $('span.pdp-product-price__discount') || 
                              $('.pdp-product-price__discount') ||
                              $('.discount');
                
                // Calculate if not found
                if (!discount && price && origPrice) {
                    const p = parseFloat(price.replace(/[^0-9.]/g, ''));
                    const o = parseFloat(origPrice.replace(/[^0-9.]/g, ''));
                    if (p && o && o > p) {
                        discount = '-' + Math.round((1 - p/o) * 100) + '%';
                    }
                }
                
                // BRAND
                let brand = $('a.pdp-product-brand') || $('.pdp-product-brand');
                if (brand) {
                    brand = brand.replace(/^Brand:\s*/i, '');
                    brand = brand.split('More')[0].trim();
                    if (brand.length > 25) brand = brand.substring(0, 25);
                }
                
                // RATING & REVIEWS
                let rating = $('span.pdp-review-summary__average') || $('.rating-value');
                let reviews = $('span.pdp-review-summary__count');
                if (reviews) reviews = reviews.replace(/[^0-9]/g, '');
                
                // CATEGORY
                const breadcrumbs = $$('a.pdp-mod-product-breadcrumb-link');
                const category = breadcrumbs.length > 0 ? breadcrumbs[breadcrumbs.length - 1] : null;
                
                // IMAGE
                let image = document.querySelector('meta[property="og:image"]')?.content || '';
                if (!image) {
                    const img = document.querySelector('img.pdp-mod-common-image, .pdp-product-img img');
                    if (img) image = img.src;
                }
                
                return {
                    title: title || 'N/A',
                    price: price || 'N/A',
                    original_price: origPrice || 'N/A',
                    discount: discount || 'N/A',
                    rating: rating || 'N/A',
                    review_count: reviews || 'N/A',
                    brand: brand || 'N/A',
                    category: category || 'N/A',
                    image: image
                };
            }""")
            
            browser.close()
            elapsed = time.time() - start_time
            data['url'] = current_url
            print(f"✅ {elapsed:.1f}s | Price: {data.get('price')} | {data.get('discount')}")
            return data
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return {'error': str(e)}


@app.route('/')
def home():
    return '''<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Daraz Viewer</title><style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:Arial,sans-serif;background:#f57224;padding:20px}.container{max-width:600px;margin:0 auto}h1{color:#fff;text-align:center;margin-bottom:20px}.search-box{background:#fff;padding:20px;border-radius:12px;margin-bottom:20px}.input-row{display:flex;gap:10px}input{flex:1;padding:14px;border:2px solid #ddd;border-radius:8px;font-size:14px}input:focus{outline:none;border-color:#f57224}button{padding:14px 20px;background:#f57224;color:#fff;border:none;border-radius:8px;font-weight:bold;cursor:pointer}.quick-links{margin-top:10px;display:flex;gap:5px}.quick-btn{background:#eee;border:1px solid #ddd;padding:5px 12px;border-radius:15px;font-size:11px;cursor:pointer}.quick-btn:hover{background:#f57224;color:#fff}.loading{text-align:center;padding:30px;display:none;color:#fff}.spinner{border:4px solid rgba(255,255,255,.3);border-top:4px solid #fff;border-radius:50%;width:40px;height:40px;animation:spin .8s linear infinite;margin:0 auto 15px}@keyframes spin{0%{transform:rotate(0)}100%{transform:rotate(360deg)}}.error{background:#fff0f0;padding:12px;border-radius:8px;display:none;color:#d00;margin-bottom:15px}.product{display:none}.product-card{background:#fff;border-radius:12px;overflow:hidden}.img-section{background:#fafafa;padding:20px;text-align:center;position:relative}.product-img{max-width:100%;max-height:250px;object-fit:contain}.disc-badge{position:absolute;top:10px;right:10px;background:#f44;color:#fff;padding:5px 10px;border-radius:15px;font-weight:bold;font-size:12px;display:none}.details{padding:20px}.brand{color:#f57224;font-size:13px;margin-bottom:5px}.title{font-size:18px;font-weight:bold;color:#333;margin-bottom:10px}.price-box{background:#fff5f0;padding:15px;border-radius:10px;margin-bottom:10px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}.price{font-size:28px;font-weight:bold;color:#f57224}.orig-price{color:#999;text-decoration:line-through;font-size:14px;display:none}.disc-text{color:#f44;font-weight:bold;font-size:14px;display:none}.stats{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:8px;margin-bottom:10px}.stat{background:#f8f9fa;padding:10px;border-radius:8px;text-align:center}.stat-label{font-size:10px;color:#888}.stat-value{font-size:13px;font-weight:bold;color:#333}.buy-btn{display:block;text-align:center;background:#f57224;color:#fff;padding:14px;border-radius:10px;text-decoration:none;font-size:16px;font-weight:bold}.time{text-align:center;margin-top:8px;font-size:11px;color:#888}</style></head><body><div class="container"><h1>🛍️ Daraz Product Viewer</h1><div class="search-box"><div class="input-row"><input type="text" id="urlInput" placeholder="Paste Daraz link..." autofocus><button onclick="search()">🔍</button></div><div class="quick-links"><button class="quick-btn" onclick="quick('https://s.daraz.com.bd/s.bMhlC?cc')">⌚ Watch</button><button class="quick-btn" onclick="quick('https://www.daraz.com.bd/products/realme-c55-8gb-256gb-i405584532.html')">📱 Phone</button></div></div><div class="loading" id="loading"><div class="spinner"></div><p>Loading...</p></div><div class="error" id="error"></div><div class="product" id="product"><div class="product-card"><div class="img-section"><img class="product-img" id="pImg" src="" onerror="this.style.display='none'"><div class="disc-badge" id="pDiscBadge"></div></div><div class="details"><div class="brand" id="pBrand"></div><h2 class="title" id="pTitle"></h2><div class="price-box"><span class="price" id="pPrice">N/A</span><span class="orig-price" id="pOrig"></span><span class="disc-text" id="pDisc"></span></div><div class="stats"><div class="stat"><div class="stat-label">⭐ Rating</div><div class="stat-value" id="pRating">-</div></div><div class="stat"><div class="stat-label">📝 Reviews</div><div class="stat-value" id="pReviews">-</div></div><div class="stat"><div class="stat-label">🏷️ Brand</div><div class="stat-value" id="pBrandVal">-</div></div><div class="stat"><div class="stat-label">📂 Category</div><div class="stat-value" id="pCategory">-</div></div></div><a class="buy-btn" id="pBuy" href="#" target="_blank">🛒 Buy Now on Daraz</a><div class="time" id="pTime"></div></div></div></div></div><script>async function search(){const e=document.getElementById("urlInput").value.trim();e&&fetchProduct(e)}function quick(e){document.getElementById("urlInput").value=e,fetchProduct(e)}async function fetchProduct(e){const t=Date.now();document.getElementById("loading").style.display="block";document.getElementById("product").style.display="none";document.getElementById("error").style.display="none";try{const o=await fetch("/api/product?url="+encodeURIComponent(e)),n=await o.json(),l=((Date.now()-t)/1e3).toFixed(1);document.getElementById("loading").style.display="none";if(n.error){document.getElementById("error").textContent="❌ "+n.error;document.getElementById("error").style.display="block";return}n.image&&(document.getElementById("pImg").src=n.image,document.getElementById("pImg").style.display="block");document.getElementById("pTitle").textContent=n.title||"N/A";document.getElementById("pPrice").textContent=n.price||"N/A";document.getElementById("pBuy").href=n.url||e;document.getElementById("pTime").textContent="⚡ "+l+"s";n.brand&&"N/A"!==n.brand?(document.getElementById("pBrand").textContent="🏷️ "+n.brand,document.getElementById("pBrandVal").textContent=n.brand):(document.getElementById("pBrand").textContent="",document.getElementById("pBrandVal").textContent="-");document.getElementById("pRating").textContent="N/A"!==n.rating?"⭐ "+n.rating:"-";document.getElementById("pReviews").textContent="N/A"!==n.review_count?n.review_count:"0";document.getElementById("pCategory").textContent="N/A"!==n.category?n.category:"-";n.original_price&&"N/A"!==n.original_price&&n.original_price!==n.price&&(document.getElementById("pOrig").textContent=n.original_price,document.getElementById("pOrig").style.display="inline");n.discount&&"N/A"!==n.discount&&(document.getElementById("pDisc").textContent="🔥 "+n.discount,document.getElementById("pDisc").style.display="inline",document.getElementById("pDiscBadge").textContent=n.discount,document.getElementById("pDiscBadge").style.display="block");document.getElementById("product").style.display="block"}catch(o){document.getElementById("loading").style.display="none",document.getElementById("error").textContent="❌ "+o.message,document.getElementById("error").style.display="block"}}document.getElementById("urlInput").addEventListener("keypress",function(e){"Enter"===e.key&&search()});</script></body></html>'''


@app.route('/api/product')
def api_product():
    url = request.args.get('url', '')
    if not url: return jsonify({'error': 'URL required'}), 400
    return jsonify(scrape_daraz(url))


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port, threaded=True)
