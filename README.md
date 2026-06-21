# Lesewerkstatt

Application web de lecture allemande assistée — mono-utilisateur.

Ajoutez une source (URL, texte collé ou PDF), le serveur extrait le texte,
appelle un LLM Infomaniak pour produire un glossaire (mots difficiles → FR + lemme + note),
et l'affiche dans un lecteur où l'on **touche un mot pour voir sa traduction**.

## Stack

- **Backend** : FastAPI + SQLite (Python 3.12)
- **Frontend** : HTML/CSS/JS vanilla (PWA)
- **LLM** : Infomaniak AI Tools (compatible OpenAI), modèle Gemma 31B
- **Déploiement** : Docker, derrière Nginx + Basic Auth

## Développement local

```bash
# Créer un .env depuis le template
cp .env.example .env
# Remplir LLM_BASE_URL, LLM_API_KEY, etc.

# Installer les dépendances
pip install -r requirements.txt

# Lancer
uvicorn app.main:app --reload --port 8000
```

## Docker

```bash
docker build -t lesewerkstatt .
docker run -d --name lesewerkstatt --restart unless-stopped \
  --env-file .env \
  -p 127.0.0.1:8042:8000 \
  -v $(pwd)/data:/data \
  lesewerkstatt
```

## Déploiement (VPS Infomaniak)

1. DNS : A record `lese.example.com` → `<IP_VM>`
2. Cloner le dépôt, remplir `.env`
3. `docker build` + `docker run` (port loopback libre, volume `data/`)
4. `curl http://127.0.0.1:8042/healthz` → `{"ok":true}`
5. `htpasswd -c /etc/nginx/.htpasswd-lese admin`
6. Copier `deploy/lese.example.com.nginx` → `/etc/nginx/sites-available/`
7. `ln -s … sites-enabled/`, `nginx -t`, `systemctl reload nginx`
8. `certbot --nginx -d lese.example.com`
9. Tester : URL admin.ch, PDF DigiSanté, collage NZZ
10. Installer la PWA sur Android

## API

| Méthode | Route | Rôle |
|---|---|---|
| `GET` | `/healthz` | Health check |
| `GET` | `/api/sources` | Liste des sources (sans texte) |
| `GET` | `/api/sources/{id}` | Source complète + glossaire |
| `POST` | `/api/sources` | Ajout (URL / texte / PDF) |
| `DELETE` | `/api/sources/{id}` | Supprime une source |
| `GET` | `/api/words` | Mots gardés |
| `POST` | `/api/words` | Ajouter un mot |
| `DELETE` | `/api/words/{surface}` | Retirer un mot |
| `GET` | `/api/words/export` | Export Anki (TSV) |
