# Deploying O-Voice Studio to Vercel

Your project is now fully configured and ready to be deployed to Vercel.

---

## Method 1: Deploy via GitHub (Recommended & Easiest)

This is the standard, 1-click deployment method for Vercel:

1. **Create a new repository on GitHub:**
   - Go to [github.com/new](https://github.com/new)
   - Name your repository (e.g. `ovoiceover` or `voice-studio`)
   - Leave "Initialize with README" unchecked and click **Create repository**

2. **Push your code to GitHub:**
   Open a terminal in this folder and run:
   ```bash
   git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPOSITORY.git
   git push -u origin main
   ```

3. **Deploy on Vercel:**
   - Go to [vercel.com](https://vercel.com) and log in.
   - Click **"Add New..."** -> **"Project"**.
   - Select your GitHub repository and click **"Import"**.
   - Under **Environment Variables**, you can optionally add:
     - `UNREALSPEECH_API_KEY`: *(your Unreal Speech API key)*
     *(Note: If you don't add it here, you can simply paste it directly into the Studio settings modal inside the app).*
   - Click **"Deploy"**.

Your live URL will be ready in under 1 minute (e.g. `https://your-project.vercel.app`)!

---

## Method 2: Deploy via Vercel CLI

If you prefer deploying directly from your terminal:

1. Open Command Prompt (`cmd.exe`) in this folder.
2. Run:
   ```bash
   npx vercel
   ```
3. Follow the quick prompts:
   - Set up and deploy: **y**
   - Which scope: *(select your account)*
   - Link to existing project: **n**
   - Project name: **ovoiceover**
   - In which directory is your code located: **./**
   - Want to modify these settings: **n**

To deploy to production after testing:
```bash
npx vercel --prod
```

---

## Project Structure on Vercel

- **`public/`**: Static frontend files (`index.html`, `css/app.css`, `js/app.js`, `assets/silence_frames.bin`) served instantly via Vercel Global Edge CDN.
- **`api/index.py`**: Python serverless function that handles script segmentation, parallel Unreal Speech synthesis, and silence stitching.
- **`vercel.json`**: Configures route rewrites and sets execution timeout to 60s for long audio generations.
- **`requirements.txt`**: Automatically installed by Vercel during build (`fastapi`, `pydantic`, `requests`, `uvicorn`).
