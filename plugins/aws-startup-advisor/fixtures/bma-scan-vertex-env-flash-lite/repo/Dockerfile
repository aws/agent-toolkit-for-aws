FROM python:3.12-slim
ENV GOOGLE_GENAI_USE_VERTEXAI=true
COPY . /app
RUN pip install -r /app/requirements.txt
CMD ["python", "-m", "app.classify"]
