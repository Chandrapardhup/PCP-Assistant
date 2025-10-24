import os
import requests
import base64
import time

class ImageService:
    def __init__(self):
        self.token = os.environ.get("HUGGINGFACE_TOKEN")
        self.models = {
            "stable_diffusion": "runwayml/stable-diffusion-v1-5",
            "flux": "black-forest-labs/FLUX.1-schnell",
            "sdxl": "stabilityai/stable-diffusion-xl-base-1.0"
        }
    
    def generate(self, prompt, model="gpt-image-1"):
        """Generate image from prompt with detailed debugging"""
        try:
            if not self.token:
                print("❌ HUGGINGFACE_TOKEN not found in environment variables")
                return None
            
            if model not in self.models:
                model = "flux"
            
            model_id = self.models[model]
            url = f"https://api-inference.huggingface.co/models/{model_id}"
            headers = {"Authorization": f"Bearer {self.token}"}
            
            print(f"🎨 Attempting to generate image...")
            print(f"   Model: {model} ({model_id})")
            print(f"   Prompt: {prompt}")
            print(f"   Token: {self.token[:10]}...")  # Show first 10 chars of token
            
            # Make request with longer timeout
            response = requests.post(
                url, 
                headers=headers, 
                json={"inputs": prompt}, 
                timeout=120  # 2 minute timeout
            )
            
            print(f"📡 Response Status: {response.status_code}")
            
            if response.status_code == 200:
                image_data = response.content
                if len(image_data) > 100:  # Check if we got actual image data
                    image_b64 = base64.b64encode(image_data).decode('utf-8')
                    print("✅ Image generated successfully!")
                    print(f"   Image size: {len(image_data)} bytes")
                    return image_b64
                else:
                    print("❌ Received empty or invalid image data")
                    return None
                    
            elif response.status_code == 503:
                print("❌ Model is loading, please try again in 30 seconds")
                return None
            elif response.status_code == 401:
                print("❌ Invalid Hugging Face token")
                return None
            elif response.status_code == 404:
                print("❌ Model not found")
                return None
            else:
                print(f"❌ API Error {response.status_code}: {response.text[:200]}")
                return None
                
        except requests.exceptions.Timeout:
            print("❌ Request timeout - model might be loading")
            return None
        except requests.exceptions.ConnectionError:
            print("❌ Connection error - check internet connection")
            return None
        except Exception as e:
            print(f"❌ Unexpected error: {str(e)}")
            return None

# Create global instance
image_service = ImageService()