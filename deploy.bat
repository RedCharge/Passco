@echo off
echo ===========================================
echo   PASSCO APP - GOOGLE CLOUD RUN DEPLOYMENT
echo ===========================================
echo.

echo Step 1: Setting up Google Cloud project...
gcloud config set project pastquestion-3b0cc
gcloud config set run/region us-central1

echo.
echo Step 2: Building Docker image...
call gcloud builds submit --tag gcr.io/pastquestion-3b0cc/passco-app

echo.
echo Step 3: Deploying to Cloud Run...
call gcloud run deploy passco-app ^
  --image gcr.io/pastquestion-3b0cc/passco-app ^
  --platform managed ^
  --allow-unauthenticated ^
  --memory 2Gi ^
  --cpu 2 ^
  --port 8080 ^
  --timeout 600 ^
  --min-instances 1 ^
  --max-instances 5

echo.
echo Step 4: Getting your live URL...
for /f "tokens=*" %%i in ('gcloud run services describe passco-app --region us-central1 --format="value(status.url)"') do set URL=%%i
echo.
echo ✅ YOUR APP IS LIVE AT:
echo   %URL%
echo.

echo ===========================================
echo    DEPLOYMENT SUCCESSFUL!
echo ===========================================
echo.
pause