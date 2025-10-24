import os
import requests
import base64

class FreeImageModels:
    def __init__(self):
        self.models = {
            "stable_diffusion": "runwayml/stable-diffusion-v1-5",
            "flux": "black-forest-labs/FLUX.1-schnell",
            "sdxl": "stabilityai/stable-diffusion-xl-base-1.0",
            "kandinsky": "kandinsky-community/kandinsky-2-2-decoder"
        }
    
    def get_available_models(self):
        """List available models"""
        return list(self.models.keys())
    
    def generate_image(self, prompt, model_name="flux"):
        """Unified image generation"""
        if model_name not in self.models:
            model_name = "flux"
        
        model = self.models[model_name]
        url = f"https://api-inference.huggingface.co/models/{model}"
        
        headers = {"Authorization": f"Bearer ${secrets.HUGGINGFACE}"}

        try:
            response = requests.post(url, headers=headers, json={"inputs": prompt}, timeout=120)
            
            if response.status_code == 200:
                image_data = response.content
                return base64.b64encode(image_data).decode('utf-8')
            else:
                print(f"Model {model_name} failed: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"Error with {model_name}: {str(e)}")
            return None

# Create instance with correct name

free_image_models = FreeImageModels()
