# Cloud Run image: ADK API server + the Gemini CLI (Node) in one container. Not built or deployed in this repo's CI.
#   gcloud run deploy gemini-cli-agent --source . --region us-central1 --set-env-vars GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_LOCATION=global
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git nodejs npm && rm -rf /var/lib/apt/lists/* && npm i -g @google/gemini-cli
WORKDIR /app
COPY requirements.txt . 
RUN pip install --no-cache-dir -r requirements.txt
COPY common common
COPY agents agents
RUN useradd -m agent && chown -R agent /app
USER agent
ENV PORT=8080
CMD ["sh", "-c", "adk api_server agents --host 0.0.0.0 --port $PORT"]
