from flask import Flask, request, jsonify
from base64 import b64encode, b64decode
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from curl_cffi import requests
import json
import random
import time
import string
import re
import hashlib
import os
from urllib.parse import unquote

app = Flask(__name__)

# ─── Constants ──────────────────────────────────────────────────────

STATIC_KEY = bytes.fromhex("e044ac6cda6be680b412e4437a20b9541709228fbbed7bf8af6731a01f9f0bca")
STATIC_IV = b"1234567890123456"
APPID = "1450015065"
SHOP_CODE = "midasbuy"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

XMIDAS_SDK_URL = "https://www.midasbuy.com/xmidas-sdk.js"
CHARACTER_API_URL = "https://www.midasbuy.com/interface/getCharac"
REDEEM_API_URL = "https://www.midasbuy.com/interface/shelfProto/shelves_svr/QueryRedeemCodeInfo"

COUNTRY_INFO = {
    "us": {"currency": "USD", "area": "NorthAmerica", "group_id": "pubg_utp_new"},
    "bd": {"currency": "BDT", "area": "SouthEastAsia", "group_id": "pubg_utp_new"},
    "tr": {"currency": "TRY", "area": "Europe", "group_id": "pubg_utp_new"},
    "gb": {"currency": "GBP", "area": "Europe", "group_id": "pubg_utp_new"},
    "pk": {"currency": "PKR", "area": "SouthEastAsia", "group_id": "pubg_utp_new"},
    "id": {"currency": "IDR", "area": "SouthEastAsia", "group_id": "pubg_utp_new"},
    "th": {"currency": "THB", "area": "SouthEastAsia", "group_id": "pubg_utp_new"},
    "my": {"currency": "MYR", "area": "SouthEastAsia", "group_id": "pubg_utp_new"},
    "ph": {"currency": "PHP", "area": "SouthEastAsia", "group_id": "pubg_utp_new"},
    "sg": {"currency": "SGD", "area": "SouthEastAsia", "group_id": "pubg_utp_new"},
    "sa": {"currency": "SAR", "area": "MiddleEast", "group_id": "pubg_utp_new"},
    "ae": {"currency": "AED", "area": "MiddleEast", "group_id": "pubg_utp_new"},
}

DEFAULT_COUNTRY = "us"

# ─── Headers ────────────────────────────────────────────────────────

def get_headers(referer: str = None):
    headers = {
        'User-Agent': UA,
        'Accept': "application/json, text/plain, */*",
        'Content-Type': "application/json",
        'Origin': "https://www.midasbuy.com",
        'Accept-Language': "en-US,en;q=0.9",
        'Accept-Encoding': "gzip, deflate, br",
        'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Platform': '"Windows"',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-origin',
    }
    if referer:
        headers['Referer'] = referer
    return headers

# ─── Crypto helpers ────────────────────────────────────────────────

def aes_decrypt(ciphertext: bytes, key: bytes, iv: bytes) -> bytes:
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return unpad(cipher.decrypt(ciphertext), AES.block_size)

def aes_encrypt_b64(plaintext: bytes, key: bytes, iv: bytes) -> str:
    cipher = AES.new(key, AES.MODE_CBC, iv)
    encrypted = cipher.encrypt(pad(plaintext, AES.block_size))
    return b64encode(encrypted).decode()

def session_key_from_ctoken(ctoken_hex: str) -> bytes:
    return aes_decrypt(bytes.fromhex(ctoken_hex), STATIC_KEY, STATIC_IV)

def make_encrypted_body(payload: dict, session_key: bytes, ctoken: str) -> str:
    """Create encrypted body exactly like the bot script"""
    # Convert to JSON with no spaces and ensure_ascii=False
    plaintext = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    encrypted = aes_encrypt_b64(plaintext, session_key, STATIC_IV)
    
    # Create the final JSON
    return json.dumps({
        "encrypt_msg": encrypted,
        "ctoken_ver": "1.0.1",
        "ctoken": ctoken
    }, separators=(",", ":"))

# ─── Random ID generators ──────────────────────────────────────────

def gen_device_id() -> str:
    return "".join(str(random.randint(0, 9)) for _ in range(31))

def gen_tdrc_fp() -> str:
    return "".join(str(random.randint(0, 9)) for _ in range(35))

def gen_muid() -> str:
    return "U" + ''.join([random.choice(string.ascii_lowercase + string.digits) for _ in range(12)])

def gen_user_id() -> str:
    return ''.join([str(random.randint(0, 9)) for _ in range(random.choice([17, 18, 19, 20]))])

def make_pagetoken(ts_ms: int, open_id: str = "") -> str:
    return b64encode(f"www.midasbuy.com_{ts_ms}_{open_id}".encode()).decode()

def make_exp_params(device_id: str, muid: str) -> str:
    return b64encode(json.dumps(
        {"exp_id": "", "exp_group_id": "", "scene_id": "midasbuy.new_ui",
         "device_id": device_id, "shop_code": SHOP_CODE, "muid": muid},
        separators=(",", ":"),
    ).encode()).decode()

def make_drm_info(muid: str, country: str, area: str, group_id: str) -> str:
    return (
        f"groupid=check_in&group_id={group_id}"
        f"&area={area}&country={country.upper()}"
        f"&muid={muid}&version=3.0&midasbuyArea={area}"
    )

def get_country_info(country_code: str) -> dict:
    return COUNTRY_INFO.get(country_code.lower(), COUNTRY_INFO[DEFAULT_COUNTRY])

# ─── Proxy helper ──────────────────────────────────────────────────

def parse_proxy_url(proxy_str: str) -> str:
    """
    Parse proxy string and return a proper proxy URL for requests.
    Supports formats:
    1. user:pass@host:port
    2. host:port:user:pass
    3. http://user:pass@host:port
    """
    if not proxy_str:
        return None
    
    proxy_str = proxy_str.strip()
    
    # If it already has http:// or https://, return as-is
    if proxy_str.startswith(('http://', 'https://')):
        return proxy_str
    
    # Format 1: user:pass@host:port
    if '@' in proxy_str:
        parts = proxy_str.split('@')
        if len(parts) == 2:
            auth = parts[0]
            host_port = parts[1]
            user_pass = auth.split(':', 1)
            if len(user_pass) == 2:
                user = user_pass[0]
                password = user_pass[1]
                return f"http://{user}:{password}@{host_port}"
    
    # Format 2: host:port:user:pass
    if ':' in proxy_str:
        parts = proxy_str.split(':')
        if len(parts) >= 4:
            host = parts[0]
            port = parts[1]
            user = parts[2]
            password = ':'.join(parts[3:])  # In case password contains colons
            
            # Validate port is a number
            try:
                int(port)
                return f"http://{user}:{password}@{host}:{port}"
            except ValueError:
                pass
    
    # If we can't parse it, return as-is (might still work)
    return f"http://{proxy_str}"

def create_session(proxy_url: str = None):
    """Create a session with optional proxy support"""
    session = requests.Session(impersonate="chrome120")
    if proxy_url:
        proxy_url = parse_proxy_url(proxy_url)
        if proxy_url:
            session.proxies = {
                'http': proxy_url,
                'https': proxy_url
            }
    return session

# ─── Get fresh ctoken from page ────────────────────────────────────

def get_fresh_ctoken(session, country: str) -> dict:
    """Fetch a fresh ctoken from the MidasBuy page - exactly like bot script"""
    buy_page_url = f"https://www.midasbuy.com/midasbuy/{country}/buy/pubgm?from=self.midasbuy_saas"
    
    # First try to get ctoken from the page
    r = session.get(buy_page_url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }, timeout=15)
    
    # Look for xMidasToken in various forms (same as bot script)
    m_tok = re.search(r'id="xMidasToken"[^>]*value="([^"]+)"', r.text)
    if not m_tok:
        m_tok = re.search(r'value="([0-9a-f]{90,})"[^>]*id="xMidasToken"', r.text)
    if not m_tok:
        m_tok = re.search(r'xMidasTokenInput\.value\s*=\s*"([^"]+)"', r.text)
    
    # If not found, fetch from xmidas-sdk.js (same as bot script)
    if not m_tok:
        r2 = session.get(XMIDAS_SDK_URL, headers={
            "User-Agent": UA, "Referer": buy_page_url}, timeout=15)
        m_tok = re.search(r'xMidasTokenInput\.value\s*=\s*"([^"]+)"', r2.text)
    
    if not m_tok:
        raise RuntimeError("Could not extract ctoken from page or SDK")
    
    ctoken = m_tok.group(1)
    sk = session_key_from_ctoken(ctoken)
    server_country = session.cookies.get("country", domain="www.midasbuy.com")
    
    return {
        "ctoken": ctoken,
        "sk": sk,
        "server_country": server_country,
        "url": buy_page_url
    }

# ─── Main lookup functions ─────────────────────────────────────────

def lookup_pubg_id(pubg_id: str, country: str = "us", proxy_url: str = None) -> dict:
    """Look up PUBG player info using fresh token with optional proxy"""
    try:
        # Create session with optional proxy
        session = create_session(proxy_url)
        
        # Generate IDs
        device_id = gen_device_id()
        tdrc_fp = gen_tdrc_fp()
        muid = gen_muid()
        
        # Set initial cookies
        session.cookies.set("midasbuyDeviceId", device_id, domain="www.midasbuy.com")
        session.cookies.set("UUID", tdrc_fp, domain="www.midasbuy.com")
        session.cookies.set("country", country, domain="www.midasbuy.com")
        session.cookies.set("select_country", country, domain="www.midasbuy.com")
        session.cookies.set("shopcode", SHOP_CODE, domain="www.midasbuy.com")
        session.cookies.set("select_cookie", "1", domain="www.midasbuy.com")
        session.cookies.set("cookie_control", "1|1|1", domain="www.midasbuy.com")
        
        # Get fresh ctoken
        ct = get_fresh_ctoken(session, country)
        ctoken = ct["ctoken"]
        sk = ct["sk"]
        
        # Use server country if available
        if ct.get("server_country"):
            country = ct["server_country"].lower()
        
        ci = get_country_info(country)
        currency = ci["currency"]
        area = ci["area"]
        group_id = ci["group_id"]
        
        # Build payload - exactly like bot script's base_payload
        ts = int(time.time() * 1000)
        pagetoken = make_pagetoken(ts)
        exp_params = make_exp_params(device_id, muid)
        drm_info = make_drm_info(muid, country, area, group_id)
        
        payload = {
            "appid": APPID,
            "midas_sdk": "0",
            "currency_type": currency,
            "country": country.upper(),
            "midasbuyArea": area,
            "sc": "",
            "from": "self.midasbuy_saas",
            "task_token": "",
            "pf": "mds_pc_browser-v3-android-midasweb-midasbuy-self.midasbuy_saas",
            "zoneid": "1",
            "_id": f"0.{random.random()}",
            "drm_info": drm_info,
            "shopcode": SHOP_CODE,
            "cgi_extend": f"device_id={device_id}&pagetoken={pagetoken}&tdrc_fp={tdrc_fp}&muid={muid}",
            "cgi_extend_obj": {
                "device_id": device_id,
                "pagetoken": pagetoken,
                "tdrc_fp": tdrc_fp,
                "muid": muid
            },
            "buyType": "redeem",
            "expParams": exp_params,
            "openid": pubg_id
        }
        
        # Create encrypted body
        encrypted_body = make_encrypted_body(payload, sk, ctoken)
        
        # Make request with proper headers
        buy_ref = f"https://www.midasbuy.com/midasbuy/{country}/buy/pubgm?from=self.midasbuy_saas"
        response = session.post(
            CHARACTER_API_URL,
            data=encrypted_body,
            headers={
                **get_headers(buy_ref),
                "Content-Type": "application/json"
            },
            timeout=30
        )
        
        result = response.json()
        
        if result.get("ret") == 0:
            info = result.get("info", {})
            return {
                "success": True,
                "zone_id": info.get("zoneid"),
                "open_id": info.get("openid"),
                "character_name": unquote(info.get("charac_name", "")),
                "active_country": info.get("active_country"),
                "register_country": info.get("register_country"),
                "is_banned": bool(info.get("is_ban")),
                "country_used": country,
                "proxy_used": bool(proxy_url)
            }
        
        return {
            "success": False,
            "error": result.get("msg", "Account not found"),
            "ret": result.get("ret"),
            "country_used": country,
            "proxy_used": bool(proxy_url)
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": f"Request failed: {str(e)}",
            "proxy_used": bool(proxy_url)
        }

def lookup_redeem_code(redeem_code: str, open_id: str, country: str = "us", proxy_url: str = None) -> dict:
    """Look up redeem code info using fresh token with optional proxy"""
    try:
        # Create session with optional proxy
        session = create_session(proxy_url)
        
        # Generate IDs
        device_id = gen_device_id()
        tdrc_fp = gen_tdrc_fp()
        muid = gen_muid()
        user_ip = f"{random.randint(1,255)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(0,255)}"
        
        # Set cookies
        session.cookies.set("midasbuyDeviceId", device_id, domain="www.midasbuy.com")
        session.cookies.set("UUID", tdrc_fp, domain="www.midasbuy.com")
        session.cookies.set("country", country, domain="www.midasbuy.com")
        session.cookies.set("select_country", country, domain="www.midasbuy.com")
        session.cookies.set("shopcode", SHOP_CODE, domain="www.midasbuy.com")
        session.cookies.set("select_cookie", "1", domain="www.midasbuy.com")
        session.cookies.set("cookie_control", "1|1|1", domain="www.midasbuy.com")
        
        # Get fresh ctoken
        ct = get_fresh_ctoken(session, country)
        ctoken = ct["ctoken"]
        sk = ct["sk"]
        
        # Use server country if available
        if ct.get("server_country"):
            country = ct["server_country"].lower()
        
        ci = get_country_info(country)
        currency = ci["currency"]
        area = ci["area"]
        group_id = ci["group_id"]
        
        # Build payload
        ts = int(time.time() * 1000)
        pagetoken = make_pagetoken(ts, open_id)
        exp_params = make_exp_params(device_id, muid)
        drm_info = make_drm_info(muid, country, area, group_id)
        
        payload = {
            "appid": APPID,
            "midas_sdk": "0",
            "currency_type": currency,
            "country": country.upper(),
            "midasbuyArea": area,
            "sc": "",
            "from": "",
            "task_token": "",
            "pf": "mds_pc_browser-v3-android-midasweb-midasbuy-self",
            "zoneid": "1",
            "_id": f"0.{random.random()}",
            "drm_info": drm_info,
            "shopcode": SHOP_CODE,
            "cgi_extend": f"device_id={device_id}&pagetoken={pagetoken}&tdrc_fp={tdrc_fp}&muid={muid}",
            "buyType": "redeem",
            "cgi_extend_obj": {
                "device_id": device_id,
                "pagetoken": pagetoken,
                "tdrc_fp": tdrc_fp,
                "muid": muid
            },
            "expParams": exp_params,
            "redeem_code": redeem_code,
            "subchannel": "MIDASBUY_REDEEM",
            "direct_redeem": "1",
            "offer_id": APPID,
            "platform": "android",
            "server_id": "1",
            "region": country.upper(),
            "open_id": open_id,
            "muid": muid,
            "flexible_return_url": "https://www.midasbuy.com/h5/overseah5/views/riskcontrol/landing.html",
            "user_ip": user_ip,
            "role_id": "",
            "language": "en",
            "shop_code": SHOP_CODE,
            "trpcPath": "/trpc.mbusiness.shelves_svr.Shelves/QueryRedeemCodeInfo"
        }
        
        # Create encrypted body
        encrypted_body = make_encrypted_body(payload, sk, ctoken)
        
        # Make request
        buy_ref = f"https://www.midasbuy.com/midasbuy/{country}/buy/pubgm?from=self.midasbuy_saas"
        response = session.post(
            REDEEM_API_URL,
            data=encrypted_body,
            headers={
                **get_headers(buy_ref),
                "Content-Type": "application/json"
            },
            timeout=30
        )
        
        result = response.json()
        
        if result.get("ret") == 0:
            info = result.get("redeem_code_info", {})
            products = []
            for p in info.get("products", []):
                products.append({
                    "name": p.get("name", "N/A"),
                    "amount": p.get("game_coins_num", "N/A"),
                    "product_id": p.get("product_id", "N/A"),
                    "price_usd": p.get("price_usd")
                })
            
            vip_info = result.get("common_model_view_data", {}).get("model_view_vip_product", {})
            vip_products = []
            for vp in vip_info.get("vip_products", []):
                vip_products.append({
                    "product_id": vp.get("product_id", "N/A"),
                    "max_gift_coin": vp.get("max_gift_coin", "N/A"),
                    "min_gift_coin": vp.get("mini_gift_coin", "N/A")
                })
            
            return {
                "success": True,
                "country_used": country,
                "proxy_used": bool(proxy_url),
                "redeem_code_info": {
                    "game_name": info.get("game_name", "N/A"),
                    "coin_name": info.get("coin_name", "N/A"),
                    "app_id": info.get("app_id", "N/A"),
                    "region": info.get("region", "N/A"),
                    "products": products
                },
                "vip_info": vip_products,
                "player_country": result.get("playerCountryCode")
            }
        
        return {
            "success": False,
            "error": result.get("msg", "Unknown error"),
            "ret": result.get("ret"),
            "country_used": country,
            "proxy_used": bool(proxy_url)
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": f"Request failed: {str(e)}",
            "proxy_used": bool(proxy_url)
        }

# ─── Flask Routes ──────────────────────────────────────────────────

@app.route('/', methods=['GET'])
def docs():
    """API Documentation endpoint"""
    return jsonify({
        "service": "PUBG Mobile Redeem Code API",
        "version": "2.2.0",
        "description": "Uses fresh ctoken generation from MidasBuy page with proxy support",
        "region": "Auto-detected from MidasBuy",
        "features": [
            "Fresh token generation for each request",
            "Optional proxy support",
            "Multiple country support",
            "Automatic country detection"
        ],
        "endpoints": {
            "/": {
                "methods": ["GET"],
                "description": "API documentation (this page)"
            },
            "/playerInfo": {
                "methods": ["GET", "POST"],
                "description": "Get player information by PUBG ID",
                "parameters": {
                    "pubg_id": {
                        "type": "string",
                        "required": True,
                        "description": "PUBG Mobile player ID (numeric)"
                    },
                    "country": {
                        "type": "string",
                        "required": False,
                        "description": "Country code (us, bd, tr, etc.)",
                        "default": "us"
                    },
                    "proxy": {
                        "type": "string",
                        "required": False,
                        "description": "Proxy URL (optional). Formats: user:pass@host:port OR host:port:user:pass",
                        "examples": [
                            "user:pass@proxy.example.com:8080",
                            "proxy.example.com:8080:user:pass",
                            "http://user:pass@proxy.example.com:8080"
                        ]
                    }
                },
                "examples": {
                    "GET": "/playerInfo?pubg_id=1234567890&country=us",
                    "GET with proxy": "/playerInfo?pubg_id=1234567890&country=us&proxy=user:pass@proxy.example.com:8080"
                }
            },
            "/codeInfo": {
                "methods": ["GET", "POST"],
                "description": "Get redeem code information",
                "parameters": {
                    "open_id": {
                        "type": "string",
                        "required": True,
                        "description": "Player's Open ID from /playerInfo endpoint"
                    },
                    "redeem_code": {
                        "type": "string",
                        "required": True,
                        "description": "Redeem code to lookup"
                    },
                    "country": {
                        "type": "string",
                        "required": False,
                        "description": "Country code (us, bd, tr, etc.)",
                        "default": "us"
                    },
                    "proxy": {
                        "type": "string",
                        "required": False,
                        "description": "Proxy URL (optional). Formats: user:pass@host:port OR host:port:user:pass",
                        "examples": [
                            "user:pass@proxy.example.com:8080",
                            "proxy.example.com:8080:user:pass"
                        ]
                    }
                },
                "examples": {
                    "GET": "/codeInfo?open_id=1234567890&redeem_code=CODE123&country=us",
                    "GET with proxy": "/codeInfo?open_id=1234567890&redeem_code=CODE123&country=us&proxy=user:pass@proxy.example.com:8080"
                }
            }
        }
    }), 200

@app.route('/playerInfo', methods=['GET', 'POST'])
def get_player_info():
    """Get player information by PUBG ID with optional proxy"""
    try:
        # Extract pubg_id from request
        if request.method == 'GET':
            pubg_id = request.args.get('pubg_id')
            country = request.args.get('country', 'us')
            proxy = request.args.get('proxy')
        else:
            if request.is_json:
                data = request.json
                pubg_id = data.get('pubg_id')
                country = data.get('country', 'us')
                proxy = data.get('proxy')
            else:
                pubg_id = request.form.get('pubg_id')
                country = request.form.get('country', 'us')
                proxy = request.form.get('proxy')
        
        # Validation
        if not pubg_id:
            return jsonify({
                "success": False,
                "error": "Missing pubg_id parameter"
            }), 400
        
        if not pubg_id.isdigit():
            return jsonify({
                "success": False,
                "error": "Invalid PUBG ID! Must be numeric"
            }), 400
        
        # Look up character info with optional proxy
        result = lookup_pubg_id(pubg_id, country, proxy)
        
        if result.get("success"):
            return jsonify({
                "success": True,
                "data": result
            }), 200
        else:
            return jsonify({
                "success": False,
                "error": result.get("error", "Account not found"),
                "ret": result.get("ret"),
                "country_used": result.get("country_used"),
                "proxy_used": result.get("proxy_used", False)
            }), 404
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": f"Internal server error: {str(e)}"
        }), 500

@app.route('/codeInfo', methods=['GET', 'POST'])
def get_code_info():
    """Get redeem code information with optional proxy"""
    try:
        # Extract parameters from request
        if request.method == 'GET':
            open_id = request.args.get('open_id')
            redeem_code = request.args.get('redeem_code')
            country = request.args.get('country', 'us')
            proxy = request.args.get('proxy')
        else:
            if request.is_json:
                data = request.json
                open_id = data.get('open_id')
                redeem_code = data.get('redeem_code')
                country = data.get('country', 'us')
                proxy = data.get('proxy')
            else:
                open_id = request.form.get('open_id')
                redeem_code = request.form.get('redeem_code')
                country = request.form.get('country', 'us')
                proxy = request.form.get('proxy')
        
        # Validation
        if not open_id:
            return jsonify({
                "success": False,
                "error": "Missing open_id parameter"
            }), 400
        
        if not redeem_code:
            return jsonify({
                "success": False,
                "error": "Missing redeem_code parameter"
            }), 400
        
        # Look up redeem code info with optional proxy
        result = lookup_redeem_code(redeem_code, open_id, country, proxy)
        
        if result.get("success"):
            return jsonify({
                "success": True,
                "data": result
            }), 200
        else:
            return jsonify({
                "success": False,
                "error": result.get("error", "Redeem code not found"),
                "ret": result.get("ret"),
                "country_used": result.get("country_used"),
                "proxy_used": result.get("proxy_used", False)
            }), 404
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": f"Internal server error: {str(e)}"
        }), 500

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "success": False,
        "error": "Endpoint not found"
    }), 404

@app.errorhandler(405)
def method_not_allowed(error):
    return jsonify({
        "success": False,
        "error": "Method not allowed"
    }), 405

if __name__ == "__main__":
    print("=" * 60)
    print("PUBG Mobile Redeem Code API Server (v2.2 - Proxy Support)")
    print("=" * 60)
    print("Features:")
    print("  - Fresh ctoken generation for each request")
    print("  - Optional proxy support")
    print("  - Multiple country support")
    print("  - Automatic country detection")
    print("=" * 60)
    print("\nProxy formats supported:")
    print("  1. user:pass@host:port")
    print("  2. host:port:user:pass")
    print("  3. http://user:pass@host:port")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5000, debug=True)
