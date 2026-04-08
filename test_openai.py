import os
import openai

print("OPENAI_API_KEY:", os.getenv("OPENAI_API_KEY"))  # Should print your key

openai.api_key = os.getenv("OPENAI_API_KEY")
try:
    models = openai.Model.list()
    print("Models available:", [m.id for m in models.data])
except Exception as e:
    print("Error:", e)