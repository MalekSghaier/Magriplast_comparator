"""
Test OpenAI API Key and Model Access
"""
import httpx
import json
import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")

print(f"🔑 Testing API Key: {api_key[:20]}...")

payload = {
    "model": "gpt-4o",
    "max_tokens": 50,
    "temperature": 0.0,
    "messages": [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Say 'API key works!' in JSON format: {\"status\": \"working\"}"}
    ]
}

try:
    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "content-type": "application/json",
            },
            json=payload,
        )
        
        print(f"📡 Status Code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            print(f"✅ API Key Works!")
            print(f"📝 Response: {content}")
        else:
            print(f"❌ Error: {response.status_code}")
            print(f"📄 Response: {response.text}")
            
except Exception as e:
    print(f"❌ Exception: {e}")
