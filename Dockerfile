FROM python:3.8-slim
WORKDIR /ouranos
COPY requirements.txt ./
RUN pip3 install -r requirements.txt
COPY . .
ENTRYPOINT ["python3", "launcher.py"]