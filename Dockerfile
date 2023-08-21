FROM python:3.10-alpine3.18
WORKDIR /app/scripts
COPY . /app
RUN pip install -r ../requirements.txt
CMD ["python", "main.py"]