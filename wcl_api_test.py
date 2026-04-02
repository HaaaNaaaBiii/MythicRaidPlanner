import requests
from requests.auth import HTTPBasicAuth

# 你的 WCL API 憑證 (請妥善保存，未來如果是發布給別人用，建議寫在 .env 檔裡)
CLIENT_ID = 'a15fb0e5-e5b7-4b18-ad20-13fa2ac45d0d'
CLIENT_SECRET = 'yR75c14r0JO4yiPLoNFOQs6zqDgX53vEy4ws1TEJ'

def get_access_token():
    """步驟 1：使用 Client ID & Secret 換取 OAuth Token"""
    print("正在向 WCL 獲取 Access Token...")
    token_url = "https://www.warcraftlogs.com/oauth/token"
    
    # 使用 Client Credentials 模式
    data = {'grant_type': 'client_credentials'}
    auth = HTTPBasicAuth(CLIENT_ID, CLIENT_SECRET)
    
    response = requests.post(token_url, data=data, auth=auth)
    
    if response.status_code == 200:
        token = response.json().get('access_token')
        print("✅ 成功獲取 Token！\n")
        return token
    else:
        raise Exception(f"❌ 獲取 Token 失敗: {response.status_code} - {response.text}")

def fetch_report_data(report_id, token):
    """步驟 2：使用 Token 發送 GraphQL 查詢，撈取日誌資料"""
    print(f"正在撈取日誌 [{report_id}] 的資料...")
    api_url = "https://www.warcraftlogs.com/api/v2/client"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # 這是一段基礎的 GraphQL 語法：查詢報告標題，以及所有「成功擊殺(Kill)」的戰鬥
    query = """
    query($code: String!) {
        reportData {
            report(code: $code) {
                title
                fights(killType: Kills) {
                    id
                    name
                    difficulty
                    kill
                }
            }
        }
    }
    """
    
    variables = {"code": report_id}
    response = requests.post(api_url, json={'query': query, 'variables': variables}, headers=headers)
    
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"❌ GraphQL API 錯誤: {response.status_code} - {response.text}")

if __name__ == "__main__":
    try:
        # 1. 取得 Token
        my_token = get_access_token()
        
        # 2. 測試撈取資料 (這裡我隨便拿了一份公開的 WCL ID 當範例)
        # 你可以換成你們團隊自己日誌網址中的英數字串
        test_report_id = "2mYrpayGhN1PLRfF" 
        
        data = fetch_report_data(test_report_id, my_token)
        
        # 3. 印出結果
        report_info = data['data']['reportData']['report']
        print(f"📋 報告標題: {report_info['title']}")
        print("-" * 30)
        print("⚔️ 成功擊殺的首領:")
        
        for fight in report_info['fights']:
            # 難度對應: 3=普通, 4=英雄, 5=傳奇
            diff_text = "傳奇" if fight['difficulty'] == 5 else ("英雄" if fight['difficulty'] == 4 else "普通")
            print(f"  - [{diff_text}] {fight['name']} (Fight ID: {fight['id']})")
            
    except Exception as e:
        print(e)