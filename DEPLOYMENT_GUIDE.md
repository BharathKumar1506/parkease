# ParkEase — Deployment Guide (Render, Free)

Deploy the whole app (backend + frontend) as ONE service on Render.
MongoDB Atlas is already in the cloud, so nothing to do there.

Final result: a public link like
  https://parkease.onrender.com/frontend/ParkEase.html
that works on ANY device, ANY network — no more localhost / same-WiFi.

────────────────────────────────────────────────────────
STEP 1 — Put the project on GitHub
────────────────────────────────────────────────────────
1. Create a free GitHub account if you don't have one.
2. Create a new repository, e.g. "parkease".
3. Upload the project (the folder that contains backend/ and frontend/).
   Easiest: on the repo page, "Add file" → "Upload files" → drag the
   backend and frontend folders + render.yaml + .gitignore → Commit.

   IMPORTANT: do NOT upload backend/.env (it has your password).
   The .gitignore already excludes it. You'll set those values in Render.

────────────────────────────────────────────────────────
STEP 2 — Allow Atlas to accept connections from anywhere
────────────────────────────────────────────────────────
1. Go to MongoDB Atlas → your cluster → "Network Access".
2. Add IP Address → "Allow access from anywhere" (0.0.0.0/0) → Confirm.
   (Render's servers use changing IPs, so this is required.)

────────────────────────────────────────────────────────
STEP 3 — Create the Render web service
────────────────────────────────────────────────────────
1. Go to https://render.com → sign up (free, no card) → "New +" → "Web Service".
2. Connect your GitHub and pick the "parkease" repo.
3. Render may auto-read render.yaml. If it asks manually, set:
     Root Directory : backend
     Runtime        : Python 3
     Build Command  : pip install -r requirements.txt
     Start Command  : uvicorn main:app --host 0.0.0.0 --port $PORT
     Instance Type  : Free
4. Add Environment Variables (Environment tab):
     MONGO_URI       = mongodb+srv://parkease:parkease123@cluster0.zgk0sht.mongodb.net/parkease?retryWrites=true&w=majority&appName=Cluster0
     ADMIN_USERNAME  = admin
     ADMIN_PASSWORD  = parkease@123
5. Click "Create Web Service". First build takes ~3–5 minutes.

────────────────────────────────────────────────────────
STEP 4 — Open your live app
────────────────────────────────────────────────────────
Render gives you a URL like  https://parkease.onrender.com
Open:  https://parkease.onrender.com/frontend/ParkEase.html

- API docs:        https://parkease.onrender.com/docs
- Admin panel:     https://parkease.onrender.com/frontend/admin.html

The QR login + payment now encode the public URL automatically, so you can
scan from any phone on mobile data — no same-WiFi needed.

────────────────────────────────────────────────────────
NOTES
────────────────────────────────────────────────────────
• Free tier sleeps after 15 min idle. First visit then takes ~40s to wake.
  This is normal — just refresh once. Fine for demos.
• To change admin password, edit the Render env var and redeploy.
• Every time you push to GitHub, Render auto-redeploys.

────────────────────────────────────────────────────────
RESUME LINE
────────────────────────────────────────────────────────
"Deployed full-stack app on Render with MongoDB Atlas; single-service
 architecture serving API + static frontend, live at <your-url>."
