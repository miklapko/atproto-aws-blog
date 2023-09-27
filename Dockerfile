FROM python:alpine3.18

WORKDIR /

COPY ./bot.py /bot.py
COPY ./requirements.txt /requirements.txt

RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "./bot.py"]
