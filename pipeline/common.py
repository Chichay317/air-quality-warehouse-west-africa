import os
import time

import psycopg
import requests
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True))          
BASE = "https://api.openaq.org"
PAGE = 1000


def get(path, **params):
    key = os.getenv("OPENAQ_API_KEY")
    if not key:
        raise RuntimeError("OPENAQ_API_KEY not found. Check that .env is in the project folder.")
    for attempt in range(1, 6):
        wait = 15 * 2 ** (attempt - 1)        
        try:
            r = requests.get(BASE + path, params=params, headers={"X-API-Key": key}, timeout=60)
        except (requests.Timeout, requests.ConnectionError) as e:
            problem = f"network problem ({type(e).__name__})"   
        else:
            time.sleep(1.1)                               
            if r.status_code == 429:
                problem, wait = "rate limit reached", int(float(r.headers.get("x-ratelimit-reset", 60)))
            elif r.status_code == 408 or r.status_code >= 500:
                problem = f"OpenAQ answered {r.status_code}"  
            else:
                r.raise_for_status()                         
                return r.json()
        if attempt < 5:
            print(f"  {problem}, waiting {wait} s ...")
            time.sleep(wait)
    raise RuntimeError(f"gave up on {path} after 5 attempts: {problem}")


def get_all(path, **params):
    page, results = 1, []
    while True:
        batch = get(path, limit=PAGE, page=page, **params)["results"]
        results += batch
        if len(batch) < PAGE:
            return results
        page += 1


def connect():
    password = os.getenv("POSTGRES_PASSWORD")
    if not password:
        raise RuntimeError("POSTGRES_PASSWORD not found. Check that .env is in the project folder.")
    return psycopg.connect(host="localhost", port=int(os.getenv("POSTGRES_PORT", 5433)),
                           dbname="air_quality", user="aq", password=password)