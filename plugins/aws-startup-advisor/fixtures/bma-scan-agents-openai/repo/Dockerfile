FROM python:3.12-slim
COPY . /srv
WORKDIR /srv
RUN pip install -r requirements.txt
CMD ["python", "-m", "support.app"]
