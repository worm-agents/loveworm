"""Acceso a la API de Tinder Web (api.gotinder.com) reutilizando la sesión del navegador."""
import json
import time

from loveworm.helpers import estilo

API_URL = "https://api.gotinder.com"

# runs inside tinder.com so the request carries the logged-in session token
_FETCH_JS = """
const [url, method, body, done] = arguments;
const token = localStorage.getItem('TinderWeb/APIToken');
const opts = {method, headers: {'X-Auth-Token': token, 'platform': 'web', 'Content-Type': 'application/json'}};
if (body) opts.body = body;
fetch(url, opts)
  .then(r => r.text().then(t => done({status: r.status, body: t})))
  .catch(e => done({status: -1, body: String(e)}));
"""


class TinderApiError(Exception):
    pass


class TinderApi:

    def __init__(self, browser):
        self.browser = browser
        self.browser.set_script_timeout(30)

    def _request(self, method, path, body=None):
        if "tinder.com" not in self.browser.current_url:
            self.browser.get("https://tinder.com/app/recs")
            time.sleep(3)

        payload = json.dumps(body) if body is not None else None
        result = self.browser.execute_async_script(_FETCH_JS, API_URL + path, method, payload)

        if result["status"] != 200:
            raise TinderApiError(f"{method} {path} -> {result['status']}: {result['body'][:200]}")
        return json.loads(result["body"])

    def get_matches(self, messaged, limit=500):
        """messaged=True: chats with messages. messaged=False: new matches without messages."""
        matches = []
        page_token = None
        while len(matches) < limit:
            path = f"/v2/matches?count=60&message={1 if messaged else 0}&locale=en"
            if page_token:
                path += f"&page_token={page_token}"

            data = self._request("GET", path)["data"]
            matches += data.get("matches", [])

            page_token = data.get("next_page_token")
            if not page_token:
                break
            time.sleep(0.3)

        return matches[:limit]

    def get_messages(self, match_id, limit=300):
        """Returns the chat messages oldest first."""
        messages = []
        page_token = None
        while len(messages) < limit:
            path = f"/v2/matches/{match_id}/messages?count=100&locale=en"
            if page_token:
                path += f"&page_token={page_token}"

            data = self._request("GET", path)["data"]
            messages += data.get("messages", [])

            page_token = data.get("next_page_token")
            if not page_token:
                break
            time.sleep(0.3)

        return sorted(messages, key=lambda m: m.get("sent_date", ""))

    def likes_restantes(self):
        """(likes que quedan, epoch en que se recargan o None). Con Tinder Gold vienen como 100."""
        likes = self._request("GET", "/v2/profile?include=likes&locale=en")["data"].get("likes") or {}
        hasta = likes.get("rate_limited_until")
        return likes.get("likes_remaining"), (hasta / 1000 if hasta else None)

    def mi_perfil(self):
        """Tu propio perfil tal como lo ven los demás: nombre, nacimiento, bio, fotos, trabajo, intereses..."""
        return self._request("GET", "/v2/profile?include=user&locale=es")["data"].get("user") or {}

    def send_message(self, match_id, text, estilo_opts=None):
        message = estilo.normalizar(text, estilo_opts)
        return self._request("POST", f"/user/matches/{match_id}", {"message": message})
