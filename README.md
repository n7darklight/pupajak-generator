# Puisi, Pantun, Sajak Generator Web App

This is a simple Flask web app for generating Indonesian puisi, pantun, or sajak using the Google AI Studio Gemma 3 27B API. Users must enter a valid (non-disposable) email to receive an access token, which is required to generate text. Each email can generate up to 10 times. If quota is exceeded, contact info is shown for more credit.

## Features
- Email validation (no disposable/one-time/fake emails)
- Access token sent to valid email
- Limit: 10 generations per email
- Uses Google AI Studio Gemma 3 27B API for text generation
- Contact info shown if quota exceeded

## Usage
1. Run the app: `python app.py`
2. Open in browser: `http://localhost:5000`
3. Enter your email, get access token, and generate puisi, pantun, or sajak by entering a title/theme.

## Contact
For more credits, contact: your@email.com

---
