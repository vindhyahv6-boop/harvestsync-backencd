# HarvestSync: Backend and Database (Member 3)

Flask + SQLite backend. Connects Member 1's yield model, Member 2's risk module and the frontend.

## Folder contents
- app.py            main backend (APIs and database)
- yield_client.py   calls Member 1's model: https://harvestsync-ai.onrender.com/predict
- risk.py           Member 2's risk assessment
- requirements.txt  packages to install
- static/index.html simple built-in test page (optional; keep it inside a folder named static,
                    next to app.py. If it is missing the backend still runs and shows a status message)
- frontend/App.jsx  updated React frontend that calls this backend

## Run the backend
    pip install -r requirements.txt
    python app.py
Open http://localhost:5000 to check it is running.

## Deploy on Render
Build command: pip install -r requirements.txt
Start command: gunicorn app:app

## Connect the frontend (for the frontend owner)
1. Copy frontend/App.jsx into your React project's src folder, replacing the existing App.jsx.
2. At the top of App.jsx, set the API link to the deployed backend:
   const API = "https://YOUR-BACKEND.onrender.com";
3. Test: register a farmer, add a buyer order, open the dashboard.

Note: Member 1's service sleeps when idle, so the first prediction can take up to a minute.
Supported values (Member 1's model):
  Crops: Tomato, Potato, Onion, Maize, Rice
  Soil: Red, Black, Alluvial, Loamy
  Irrigation: Drip, Rainfed, Canal
The backend rejects anything else with a clear error message.

## API endpoints
GET/POST /api/farmers, /api/crops, /api/harvests, /api/orders
POST /api/predict/<crop_id>   runs yield and risk prediction and saves it
GET  /api/predictions
GET  /api/supply-gap          compares predicted supply with open buyer orders
POST /api/seed                loads demo data
GET  /api/health
