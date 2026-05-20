from bs4 import BeautifulSoup
import re

def stripHTML(html:str) -> str:
    noHTML = BeautifulSoup(html, "html.parser")
    return noHTML.get_text(separator = ' ')
    
def normalizeText(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()

def buildCleanedText(job:dict) -> str:
    stripped = stripHTML(job['description'])
    cleanedText = normalizeText(stripped)
    posting = f"""
    Title: {job['title']}
    Company:{job['company']}
    Location: {job['location']}
    Description: {cleanedText}"""
    return posting
