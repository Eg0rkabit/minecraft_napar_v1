"""Unambiguous owner controls run locally, without a model round trip."""
import re


def parse_control(text):
    text=re.sub(r'[.!?,]+$', '', text.strip().casefold()).strip()
    if text in ('стоп','stop','стой','остановись','не иди за мной','не следуй за мной'):
        return 'stop'
    text=re.sub(r'^(?:пожалуйста[, ]+|можешь +|давай +)', '', text)
    text=re.sub(r'[, ]+пожалуйста$', '', text)
    if text in ('останься','останься на сервере','оставайся на сервере','не выходи','не выходи с сервера','жди меня на сервере'):
        return 'stay'
    if text in ('выходи после меня','выходи вместе со мной','можешь выходить после меня','не оставайся на сервере'):
        return 'auto_leave'
    if re.fullmatch(r'(?:иди|идти|ходи|беги|следуй|пойд[её]м|пошли) за мной|follow me',text):
        return 'follow'
    return None

