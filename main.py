from flask import Flask, request, jsonify
from base64 import b64encode, b64decode
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from curl_cffi import requests
import json
import random
import time
import string
from urllib.parse import unquote

app = Flask(__name__)

STATIC_KEY = bytes.fromhex("e044ac6cda6be680b412e4437a20b9541709228fbbed7bf8af6731a01f9f0bca")
STATIC_IV = b"1234567890123456"
XMIDAS_TOKEN = "ae7c5c58eef7eb132575e9e9130f1bd700b5855d6f939e1eca3080808f209a581cd2acf22552228b5dfe2e278031a4d2"
CHARACTER_API_URL = "https://www.midasbuy.com/interface/getCharac"
REDEEM_API_URL = "https://www.midasbuy.com/interface/shelfProto/shelves_svr/QueryRedeemCodeInfo"

HEADERS = {
    'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    'Accept': "application/json, text/plain, */*",
    'Content-Type': "application/json",
    'Origin': "https://www.midasbuy.com",
    'Referer': "https://www.midasbuy.com/midasbuy/us/redeem/pubgm?from=self.midasbuy_saas",
    'Accept-Language': "en-US,en;q=0.9",
    'Accept-Encoding': "gzip, deflate, br",
    'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    'Sec-Ch-Ua-Mobile': '?0',
    'Sec-Ch-Ua-Platform': '"Windows"',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-origin',
}

def get_session_key(token):
    raw = bytes.fromhex(token.strip())
    cipher = AES.new(STATIC_KEY, AES.MODE_CBC, STATIC_IV)
    return unpad(cipher.decrypt(raw), AES.block_size)

def encrypt_payload(data, session_key):
    plaintext = json.dumps(data).encode()
    cipher = AES.new(session_key, AES.MODE_CBC, STATIC_IV)
    ct = cipher.encrypt(pad(plaintext, AES.block_size))
    return b64encode(ct).decode()

def generate_params():
    device_id = "015464057398" + ''.join([str(random.randint(0, 9)) for _ in range(18)])
    timestamp = int(time.time() * 1000) + random.randint(-3600000, 3600000)
    user_id = ''.join([str(random.randint(0, 9)) for _ in range(random.choice([17, 18, 19, 20]))])
    pagetoken = b64encode(f"www.midasbuy.com_{timestamp}_{user_id}".encode()).decode()
    tdrc_fp = ''.join([str(random.randint(0, 9)) for _ in range(35)])
    muid = "U" + ''.join([random.choice(string.ascii_lowercase + string.digits) for _ in range(12)])
    
    return device_id, pagetoken, tdrc_fp, muid, user_id

def lookup_pubg_id(pubg_id):
    session_key = get_session_key(XMIDAS_TOKEN)
    device_id, pagetoken, tdrc_fp, muid, _ = generate_params()
    
    exp_params = b64encode(json.dumps({
        "exp_id": "", "exp_group_id": "", "scene_id": "midasbuy.new_ui",
        "device_id": device_id, "shop_code": "midasbuy", "muid": muid
    }).encode()).decode()
    
    payload = {
        "appid": "1450015065", "midas_sdk": "0", "currency_type": "USD",
        "country": "US", "midasbuyArea": "NorthAmerica", "sc": "",
        "from": "self.midasbuy_saas", "task_token": "",
        "pf": "mds_pc_browser-v3-android-midasweb-midasbuy-self.midasbuy_saas",
        "zoneid": "1", "_id": f"0.{random.random()}",
        "drm_info": f"groupid=check_in&area=NorthAmerica&country=US&muid={muid}&version=3.0&midasbuyArea=NorthAmerica",
        "shopcode": "midasbuy",
        "cgi_extend": f"device_id={device_id}&pagetoken={pagetoken}&tdrc_fp={tdrc_fp}&muid={muid}",
        "buyType": "redeem",
        "cgi_extend_obj": {"device_id": device_id, "pagetoken": pagetoken, "tdrc_fp": tdrc_fp, "muid": muid},
        "expParams": exp_params, "openid": pubg_id
    }
    
    encrypted_msg = encrypt_payload(payload, session_key)
    
    response = requests.post(CHARACTER_API_URL, 
                            json={
                                "encrypt_msg": encrypted_msg,
                                "ctoken_ver": "1.0.1",
                                "ctoken": XMIDAS_TOKEN
                            }, 
                            headers=HEADERS, 
                            impersonate="chrome120",
                            timeout=30)
    
    result = response.json()
    
    if result.get("ret") == 0:
        info = result["info"]
        return {
            "zone_id": info.get("zoneid"),
            "open_id": info.get("openid"),
            "character_name": unquote(info.get("charac_name", "")),
            "active_country": info.get("active_country"),
            "register_country": info.get("register_country"),
            "is_banned": info.get("is_ban"),
            "success": True
        }
    return {"success": False, "error": result.get("msg", "Account not found"), "ret": result.get("ret")}

def lookup_redeem_code(redeem_code, open_id):
    session_key = get_session_key(XMIDAS_TOKEN)
    device_id, pagetoken, tdrc_fp, muid, user_id = generate_params()
    user_ip = f"{random.randint(1,255)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(0,255)}"
    
    exp_params = b64encode(json.dumps({
        "exp_id": "",
        "exp_group_id": "",
        "scene_id": "midasbuy.new_ui",
        "device_id": device_id,
        "shop_code": "midasbuy",
        "muid": muid
    }, separators=(',', ':')).encode()).decode()
    
    payload = {
        "appid": "1450015065",
        "midas_sdk": "0",
        "currency_type": "USD",
        "country": "US",
        "midasbuyArea": "NorthAmerica",
        "sc": "",
        "from": "",
        "task_token": "",
        "pf": "mds_pc_browser-v3-android-midasweb-midasbuy-self",
        "zoneid": "1",
        "_id": f"0.{random.random()}",
        "drm_info": f"groupid=check_in&area=NorthAmerica&country=US&muid={muid}&version=3.0&midasbuyArea=NorthAmerica",
        "shopcode": "midasbuy",
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
        "offer_id": "1450015065",
        "platform": "android",
        "server_id": "1",
        "region": "US",
        "open_id": open_id,
        "muid": muid,
        "flexible_return_url": "https://www.midasbuy.com/h5/overseah5/views/riskcontrol/landing.html",
        "user_ip": user_ip,
        "role_id": "",
        "language": "en",
        "shop_code": "midasbuy",
        "trpcPath": "/trpc.mbusiness.shelves_svr.Shelves/QueryRedeemCodeInfo"
    }
    
    encrypted_msg = encrypt_payload(payload, session_key)
    
    response = requests.post(REDEEM_API_URL, 
                            json={
                                "encrypt_msg": encrypted_msg,
                                "ctoken_ver": "1.0.1",
                                "ctoken": XMIDAS_TOKEN
                            }, 
                            headers=HEADERS, 
                            impersonate="chrome120",
                            timeout=30)
    
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
    else:
        return {"success": False, "error": result.get("msg", "Unknown error"), "ret": result.get("ret")}

@app.route('/', methods=['GET'])
def docs():
    """API Documentation endpoint"""
    return jsonify({
        "service": "PUBG Mobile Redeem Code LOOKUP API",
        "version": "1.0.0",
        "region": "US (North America)",
        "currency": "USD",
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
                    }
                },
                "examples": {
                    "GET": "/playerInfo?pubg_id=1234567890",
                    "POST_JSON": {
                        "method": "POST",
                        "url": "/playerInfo",
                        "headers": {"Content-Type": "application/json"},
                        "body": {"pubg_id": "1234567890"}
                    },
                    "POST_FORM": {
                        "method": "POST",
                        "url": "/playerInfo",
                        "body": "pubg_id=1234567890"
                    }
                },
                "response": {
                    "success": {
                        "data": {
                            "zone_id": "string",
                            "open_id": "string",
                            "character_name": "string",
                            "active_country": "string",
                            "register_country": "string",
                            "is_banned": "boolean"
                        }
                    },
                    "error": {
                        "error": "string",
                        "ret": "number (optional)"
                    }
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
                    }
                },
                "examples": {
                    "GET": "/codeInfo?open_id=1234567890&redeem_code=CODE123",
                    "POST_JSON": {
                        "method": "POST",
                        "url": "/codeInfo",
                        "headers": {"Content-Type": "application/json"},
                        "body": {"open_id": "1234567890", "redeem_code": "CODE123"}
                    },
                    "POST_FORM": {
                        "method": "POST",
                        "url": "/codeInfo",
                        "body": "open_id=1234567890&redeem_code=CODE123"
                    }
                },
                "response": {
                    "success": {
                        "data": {
                            "redeem_code_info": {
                                "game_name": "string",
                                "coin_name": "string",
                                "app_id": "string",
                                "region": "string",
                                "products": [
                                    {
                                        "name": "string",
                                        "amount": "number",
                                        "product_id": "string",
                                        "price_usd": "number"
                                    }
                                ]
                            },
                            "vip_info": "array",
                            "player_country": "string"
                        }
                    },
                    "error": {
                        "error": "string",
                        "ret": "number (optional)"
                    }
                }
            }
        }}), 200

@app.route('/playerInfo', methods=['GET', 'POST'])
def get_player_info():
    """
    Get player information by PUBG ID
    Supports both GET and POST methods
    
    GET: /playerInfo?pubg_id=1234567890
    POST: /playerInfo with JSON body {"pubg_id": "1234567890"}
          or form data pubg_id=1234567890
    """
    try:
        # Extract pubg_id from request
        if request.method == 'GET':
            pubg_id = request.args.get('pubg_id')
        else:
            if request.is_json:
                pubg_id = request.json.get('pubg_id')
            else:
                pubg_id = request.form.get('pubg_id')
        
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
        
        # Look up character info
        result = lookup_pubg_id(pubg_id)
        
        if result.get("success"):
            return jsonify({
                "success": True,
                "data": result
            }), 200
        else:
            return jsonify({
                "success": False,
                "error": result.get("error", "Account not found"),
                "ret": result.get("ret")
            }), 404
            
    except Exception as e:
        return jsonify({
            "success": False,
            "error": f"Internal server error: {str(e)}"
        }), 500

@app.route('/codeInfo', methods=['GET', 'POST'])
def get_code_info():
    """
    Get redeem code information
    Supports both GET and POST methods
    
    GET: /codeInfo?open_id=1234567890&redeem_code=CODE123
    POST: /codeInfo with JSON body {"open_id": "1234567890", "redeem_code": "CODE123"}
          or form data open_id=1234567890&redeem_code=CODE123
    """
    try:
        # Extract parameters from request
        if request.method == 'GET':
            open_id = request.args.get('open_id')
            redeem_code = request.args.get('redeem_code')
        else:
            if request.is_json:
                data = request.json
                open_id = data.get('open_id')
                redeem_code = data.get('redeem_code')
            else:
                open_id = request.form.get('open_id')
                redeem_code = request.form.get('redeem_code')
        
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
        
        # Look up redeem code info
        result = lookup_redeem_code(redeem_code, open_id)
        
        if result.get("success"):
            return jsonify({
                "success": True,
                "data": result
            }), 200
        else:
            return jsonify({
                "success": False,
                "error": result.get("error", "Redeem code not found"),
                "ret": result.get("ret")
            }), 404
            
    except Exception as e:
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
    print("PUBG Mobile Redeem Code API Server")
    
    app.run(host='0.0.0.0', port=5000, debug=True)
